from __future__ import annotations

import json
import time

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .auth import current_user
from ..schemas import ConversationCreateModel, ConversationPatchModel, FolderCreateModel, FolderPatchModel
from ..event_repository import EventRepository

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


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
    conversation = request.app.state.users.get_conversation(conversation_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation["messages"] = request.app.state.users.list_messages(conversation_id, user["id"])
    return conversation


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization)
    if request.app.state.users.get_conversation(conversation_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"items": request.app.state.users.list_messages(conversation_id, user["id"])}


@router.patch("/{conversation_id}")
def patch_conversation(conversation_id: str, body: ConversationPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    ok = True
    if body.title is not None: ok = request.app.state.users.rename_conversation(conversation_id, user["id"], body.title) and ok
    if body.folder_id is not None or body.clear_folder: ok = request.app.state.users.move_conversation(conversation_id, user["id"], None if body.clear_folder else body.folder_id) and ok
    if not ok: raise HTTPException(status_code=404, detail="conversation not found")
    return request.app.state.users.get_conversation(conversation_id, user["id"])


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
    if request.app.state.users.get_conversation(conversation_id, user["id"]) is None: raise HTTPException(status_code=404, detail="conversation not found")
    jobs = request.app.state.jobs.list_for_user(user["id"], conversation_id)
    return {"conversation_id": conversation_id, "messages": request.app.state.users.list_messages(conversation_id, user["id"]), "jobs": [request.app.state.jobs.snapshot(job.id) for job in jobs]}


@router.get("/{conversation_id}/events")
def conversation_events(conversation_id: str, request: Request, authorization: str | None = Header(default=None), after: int = 0):
    user = current_user(request, authorization)
    if request.app.state.users.get_conversation(conversation_id, user["id"]) is None: raise HTTPException(status_code=404, detail="conversation not found")
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
