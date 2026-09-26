from __future__ import annotations

import json
import time

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .auth import current_user
from ..schemas import ConversationAutoCreateModel, ConversationCreateModel, ConversationMessageEditModel, ConversationPatchModel, FolderCreateModel, FolderPatchModel
from ..event_repository import EventRepository

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def _conversation_owner(request: Request, conversation_id: str, actor: dict) -> str:
    owner_id = request.app.state.users.resolve_conversation_access(conversation_id, actor["id"])
    if owner_id is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return owner_id


@router.get("")
def list_conversations(request: Request, authorization: str | None = Header(default=None), include_deleted: bool = False, sort: str = "updated"):
    user = current_user(request, authorization)
    return {"items": request.app.state.users.list_conversations(user["id"], include_deleted=include_deleted, sort=sort)}


@router.post("", status_code=201)
def create_conversation(
    body: ConversationCreateModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    return request.app.state.users.create_conversation(user["id"], body.title)


@router.post("/auto", status_code=201)
def create_auto_conversation(
    body: ConversationAutoCreateModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """创建直连生成会话，并复用普通 Agent 会话的摘要标题逻辑。"""
    user = current_user(request, authorization)
    conversation = request.app.state.users.create_conversation(user["id"], body.message[:15])
    service = request.app.state.agent_service
    title_generator = getattr(service, "generate_conversation_title", None)
    title = title_generator(body.message) if callable(title_generator) else body.message[:15]
    request.app.state.users.rename_conversation(conversation["id"], user["id"], title)
    conversation["title"] = title[:15] or "新建对话"
    return conversation


@router.post("/{conversation_id}/auto-title")
def auto_title_conversation(
    conversation_id: str,
    body: ConversationAutoCreateModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    if request.app.state.users.get_conversation(conversation_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    service = request.app.state.agent_service
    title_generator = getattr(service, "generate_conversation_title", None)
    title = title_generator(body.message) if callable(title_generator) else body.message[:15]
    request.app.state.users.rename_conversation(conversation_id, user["id"], title)
    return {"id": conversation_id, "title": title[:15] or "新建对话"}


@router.get("/folders")
def folders(request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization); return {"items": request.app.state.users.list_folders(user["id"])}


@router.post("/folders", status_code=201)
def create_folder(body: FolderCreateModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization); return request.app.state.users.create_folder(user["id"], body.name)


@router.patch("/folders/{folder_id}")
def patch_folder(folder_id: str, body: FolderPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.update_folder(folder_id, user["id"], body.name): raise HTTPException(status_code=404, detail="folder not found")
    return {"id": folder_id, "name": body.name}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    conversation = request.app.state.users.get_conversation(conversation_id, owner_id)
    branches = request.app.state.users.list_branches(conversation_id, owner_id)
    active_branch = next((item for item in branches if item["is_active"]), None)
    head_message_id = active_branch.get("head_message_id") if active_branch else None
    if active_branch and not request.app.state.users.message_exists(head_message_id, conversation_id):
        head_message_id = active_branch.get("root_message_id")
    conversation["messages"] = request.app.state.users.list_path_messages(conversation_id, owner_id, head_message_id)
    conversation["branches"] = branches
    conversation["active_branch_id"] = next((item["id"] for item in branches if item["is_active"]), None)
    conversation["branch_path"] = conversation["messages"]
    conversation["pending_proposal"] = _pending_proposal(request, conversation_id, owner_id)
    conversation["conversation_proposal"] = _pending_proposal(request, conversation_id, owner_id, include_submitted=True)
    return conversation


def _pending_proposal(request: Request, conversation_id: str, user_id: str, *, include_submitted: bool = False) -> dict | None:
    with request.app.state.jobs.database.connect() as connection:
        row = connection.execute(
            "SELECT proposal_id, kind, payload_json, submitted_job_id, assistant_message_id FROM agent_proposals "
            "WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
    if row is None or (row["submitted_job_id"] and not include_submitted):
        return None
    payload = json.loads(row["payload_json"])
    assistant_message_id = row["assistant_message_id"]
    if not assistant_message_id:
        with request.app.state.jobs.database.connect() as connection:
            events = connection.execute(
                "SELECT t.assistant_message_id, e.payload_json FROM agent_events e "
                "JOIN agent_turns t ON t.id=e.turn_id "
                "WHERE t.conversation_id=? AND e.event_type='tool.completed' "
                "ORDER BY e.created_at DESC",
                (conversation_id,),
            ).fetchall()
        for event in events:
            event_payload = json.loads(event["payload_json"])
            result = (event_payload.get("output") or {}).get("result") or {}
            if result.get("proposal_id") == row["proposal_id"]:
                assistant_message_id = event["assistant_message_id"]
                break
    return {
        "proposal_id": row["proposal_id"],
        "kind": row["kind"],
        "proposal": payload,
        "editable_prompt": payload.get("requirement", ""),
        "candidate_count": payload.get("candidate_count", 1),
        "assistant_message_id": assistant_message_id,
        "submitted_job_id": row["submitted_job_id"],
    }


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    branches = request.app.state.users.list_branches(conversation_id, owner_id)
    active = next((item for item in branches if item["is_active"]), None)
    return {"items": request.app.state.users.list_path_messages(conversation_id, owner_id, active.get("head_message_id") if active else None)}


@router.patch("/{conversation_id}")
def patch_conversation(conversation_id: str, body: ConversationPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    ok = True
    if body.title is not None: ok = request.app.state.users.rename_conversation(conversation_id, user["id"], body.title) and ok
    if body.folder_id is not None or body.clear_folder: ok = request.app.state.users.move_conversation(conversation_id, user["id"], None if body.clear_folder else body.folder_id) and ok
    if not ok: raise HTTPException(status_code=404, detail="conversation not found")
    return request.app.state.users.get_conversation(conversation_id, user["id"])


@router.post("/{conversation_id}/messages/{message_id}/edit")
def edit_message(
    conversation_id: str,
    message_id: str,
    body: ConversationMessageEditModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    if request.app.state.users.get_message(message_id, conversation_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="user message not found")
    return {"conversation_id": conversation_id, "message_id": message_id, "content": body.content, "preserved": True}


@router.get("/{conversation_id}/tree")
def conversation_tree(conversation_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    branches = request.app.state.users.list_branches(conversation_id, owner_id)
    messages = request.app.state.users.list_message_tree(conversation_id, owner_id)
    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "roots": [item["id"] for item in messages if not item.get("parent_message_id")],
        "branches": branches,
        "active_branch_id": next((item["id"] for item in branches if item["is_active"]), None),
    }


@router.post("/{conversation_id}/branches/{branch_id}/activate")
def activate_branch(conversation_id: str, branch_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    if not request.app.state.users.activate_branch(branch_id, conversation_id, owner_id):
        raise HTTPException(status_code=404, detail="branch not found")
    return {"conversation_id": conversation_id, "active_branch_id": branch_id}


@router.post("/{conversation_id}/messages/{message_id}/activate-branch")
def activate_branch_for_message(conversation_id: str, message_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    branch_id = request.app.state.users.activate_branch_for_message(message_id, conversation_id, owner_id)
    if branch_id is None:
        raise HTTPException(status_code=404, detail="branch not found for message")
    return {"conversation_id": conversation_id, "active_branch_id": branch_id}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.soft_delete_conversation(conversation_id, user["id"]): raise HTTPException(status_code=404, detail="conversation not found")
    return {"status": "deleted"}


@router.post("/{conversation_id}/restore")
def restore_conversation(conversation_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.restore_conversation(conversation_id, user["id"]): raise HTTPException(status_code=404, detail="conversation not found")
    return {"status": "restored"}


@router.get("/{conversation_id}/state")
def conversation_state(conversation_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    jobs = request.app.state.jobs.list_for_user(owner_id, conversation_id)
    branches = request.app.state.users.list_branches(conversation_id, owner_id)
    active = next((item for item in branches if item["is_active"]), None)
    return {"conversation_id": conversation_id, "messages": request.app.state.users.list_path_messages(conversation_id, owner_id, active.get("head_message_id") if active else None), "jobs": [request.app.state.jobs.snapshot(job.id) for job in jobs]}


@router.get("/{conversation_id}/events")
def conversation_events(conversation_id: str, request: Request, authorization: str | None = Header(default=None), after: int = 0):
    user = current_user(request, authorization)
    owner_id = _conversation_owner(request, conversation_id, user)
    events = EventRepository(request.app.state.jobs.database)

    def stream():
        cursor = after
        deadline = time.time() + 25
        while time.time() < deadline:
            batch = events.list_agent_events(conversation_id, after=cursor)
            if batch:
                for event in batch:
                    cursor = max(cursor, int(event["seq"]))
                    yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event['payload'], ensure_ascii=False)}\n\n"
                return
            yield ": keep-alive\n\n"
            time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
