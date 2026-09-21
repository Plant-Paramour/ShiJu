from __future__ import annotations

import json
import threading
import time
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from apps.agent.openai_client import ChatModelError

from ..schemas import AgentChatModel, AgentProposalSubmitModel
from .auth import current_user
from ..event_repository import EventRepository
from ..job_repository import IdempotencyConflict
from shiju.contracts import GeneratePoemRequest, RewritePoemRequest


router = APIRouter(prefix="/v1/agent", tags=["agent"])


@router.post("/proposals/{proposal_id}/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_proposal(
    proposal_id: str,
    body: AgentProposalSubmitModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user = current_user(request, authorization, required=True)
    conversation = request.app.state.users.get_conversation(body.conversation_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    with request.app.state.jobs.database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM agent_proposals WHERE proposal_id=? AND conversation_id=? AND user_id=?",
            (proposal_id, body.conversation_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    if row["submitted_job_id"]:
        job = request.app.state.jobs.get(row["submitted_job_id"])
        return request.app.state.jobs.snapshot(job.id)

    payload = json.loads(row["payload_json"])
    payload.update(
        {
            "requirement": body.requirement,
            "candidate_count": body.candidate_count,
            "meter_type": body.meter_type,
            "form_name": body.form_name,
            "rhyme_dict_name": body.rhyme_dict_name,
            "strict_polyphonic": body.strict_polyphonic,
            "num_lines": body.num_lines,
            "task_options": body.task_options,
        }
    )
    try:
        if row["kind"] == "rewrite":
            normalized = RewritePoemRequest.from_mapping(payload).to_dict()
        else:
            normalized = GeneratePoemRequest.from_mapping(payload).to_dict()
        job = request.app.state.jobs.submit(
            row["kind"],
            normalized,
            idempotency_key=proposal_id,
            user_id=user["id"],
            conversation_id=body.conversation_id,
        )
    except (ValueError, IdempotencyConflict) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with request.app.state.jobs.database.connect() as connection:
        connection.execute(
            "UPDATE agent_proposals SET payload_json=?,submitted_job_id=?,updated_at=? WHERE proposal_id=?",
            (json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), job.id, time.time(), proposal_id),
        )
    request.app.state.gpu_provider.ensure_running()
    result = request.app.state.jobs.snapshot(job.id)
    result["waiting_for_worker"] = not request.app.state.jobs.has_live_worker()
    return result


@router.post("/chat/stream")
def chat_stream(body: AgentChatModel, request: Request, authorization: str | None = Header(default=None)):
    service = request.app.state.agent_service
    if service is None: raise HTTPException(status_code=503, detail="Agent 未启用或缺少大模型配置")
    user = current_user(request, authorization, required=False)
    conversation_id = body.conversation_id
    if user:
        if conversation_id is None: conversation_id = request.app.state.users.create_conversation(user["id"], body.message[:80])["id"]
        elif request.app.state.users.get_conversation(conversation_id, user["id"]) is None: raise HTTPException(status_code=404, detail="conversation not found")
    events = EventRepository(request.app.state.jobs.database)

    def stream():
        turn_id = None; user_message_id = None; assistant_message_id = None
        try:
            history = None
            if user and conversation_id:
                history = [m for m in request.app.state.users.list_messages(conversation_id, user["id"]) if m.get("status") == "completed"]
                user_message = request.app.state.users.add_message(conversation_id, user["id"], "user", body.message)
                pending = request.app.state.users.add_message(conversation_id, user["id"], "assistant", "", status="pending")
                user_message_id = user_message["id"]; assistant_message_id = pending["id"]
            turn_id = events.start_turn(user_id=user["id"] if user else None, conversation_id=conversation_id, user_message_id=user_message_id, assistant_message_id=assistant_message_id)
            started = events.append_agent_event(turn_id, "turn.started", {"conversation_id": conversation_id})
            yield f"id: {started['seq']}\nevent: turn.started\ndata: {json.dumps(started['payload'], ensure_ascii=False)}\n\n"
            if hasattr(service, "respond_stream"):
                stream_events = service.respond_stream(body.message, conversation_id or body.session_id, history=history, user_id=user["id"] if user else None, conversation_id=conversation_id)
            else:
                try:
                    result = service.respond(body.message, conversation_id or body.session_id, history=history, user_id=user["id"] if user else None, conversation_id=conversation_id)
                except TypeError:
                    result = service.respond(body.message, conversation_id or body.session_id)
                stream_events = iter((
                    {"event_type": "assistant.delta", "payload": {"text": result.get("reply", "")}},
                    *({"event_type": "job.submitted", "payload": job} for job in result.get("jobs") or []),
                    {"event_type": "turn.completed", "payload": {"reply": result.get("reply", ""), "jobs": result.get("jobs") or []}},
                ))
            reply_parts: list[str] = []
            submitted_jobs: list[dict] = []
            for item in stream_events:
                event_type = item["event_type"]
                payload = dict(item.get("payload") or {})
                if event_type == "assistant.delta":
                    reply_parts.append(str(payload.get("text") or ""))
                elif event_type == "job.submitted":
                    submitted_jobs.append(payload)
                    if user and payload.get("job_id"):
                        request.app.state.jobs.assign_context(payload["job_id"], user["id"], conversation_id)
                elif event_type == "turn.completed":
                    reply = str(payload.get("reply") or "".join(reply_parts))
                    jobs = payload.get("jobs") or submitted_jobs
                    job_id = jobs[-1].get("job_id") if jobs else None
                    if user and conversation_id and assistant_message_id:
                        request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content=reply, status="completed", job_id=job_id)
                    payload = {"job_id": job_id, "conversation_id": conversation_id, "session_id": payload.get("session_id")}
                    event = events.append_agent_event(turn_id, event_type, payload)
                    events.finish_turn(turn_id)
                    yield f"id: {event['seq']}\nevent: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    return
                event = events.append_agent_event(turn_id, event_type, payload)
                yield f"id: {event['seq']}\nevent: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            if turn_id:
                failed = events.append_agent_event(turn_id, "turn.failed", {"error": str(exc)}); events.finish_turn(turn_id, "failed")
                if user and conversation_id and assistant_message_id:
                    try: request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content=f"生成失败：{exc}", status="failed")
                    except Exception: pass
                yield f"id: {failed['seq']}\nevent: turn.failed\ndata: {json.dumps(failed['payload'], ensure_ascii=False)}\n\n"
            else:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat")
def chat(
    body: AgentChatModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    service = request.app.state.agent_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent 未启用或缺少大模型配置",
        )
    user = current_user(request, authorization, required=False)
    conversation_id = body.conversation_id
    pending_message_id: str | None = None
    turn_id: str | None = None
    event_store = EventRepository(request.app.state.jobs.database)
    try:
        history = None
        if user:
            if conversation_id is None:
                conversation = request.app.state.users.create_conversation(user["id"], body.message[:80])
                conversation_id = conversation["id"]
            elif request.app.state.users.get_conversation(conversation_id, user["id"]) is None:
                raise HTTPException(status_code=404, detail="conversation not found")
            history = [
                message
                for message in request.app.state.users.list_messages(
                    conversation_id, user["id"]
                )
                if message.get("status") == "completed"
            ]
            user_message = request.app.state.users.add_message(conversation_id, user["id"], "user", body.message)
            pending = request.app.state.users.add_message(
                conversation_id,
                user["id"],
                "assistant",
                "AI 正在生成回复……",
                status="pending",
            )
            pending_message_id = pending["id"]
            turn_id = event_store.start_turn(user_id=user["id"], conversation_id=conversation_id, user_message_id=user_message["id"], assistant_message_id=pending_message_id)
            event_store.append_agent_event(turn_id, "turn.started", {"conversation_id": conversation_id})
        try:
            result = service.respond(
                body.message,
                conversation_id or body.session_id,
                history=history,
                user_id=user["id"] if user else None,
                conversation_id=conversation_id,
            )
        except TypeError:
            result = service.respond(body.message, conversation_id or body.session_id)
        if user:
            for job in result.get("jobs") or []:
                request.app.state.jobs.assign_context(job["job_id"], user["id"], conversation_id)
            if result.get("job_id") and not result.get("jobs"):
                request.app.state.jobs.assign_context(result["job_id"], user["id"], conversation_id)
        if user and conversation_id:
            request.app.state.users.update_message(
                pending_message_id,
                conversation_id,
                user["id"],
                content=result["reply"],
                status="completed",
                job_id=result.get("job_id"),
            )
            result = {**result, "conversation_id": conversation_id}
        if turn_id:
            event_store.append_agent_event(turn_id, "assistant.delta", {"text": result.get("reply", "")})
            for job in result.get("jobs") or []: event_store.append_agent_event(turn_id, "job.submitted", job)
            event_store.append_agent_event(turn_id, "turn.completed", {"job_id": result.get("job_id")})
            event_store.finish_turn(turn_id)
        return result
    except ChatModelError as exc:
        if turn_id: event_store.append_agent_event(turn_id, "turn.failed", {"error": str(exc)}); event_store.finish_turn(turn_id, "failed")
        _mark_failed(request, user, conversation_id, pending_message_id, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        _mark_failed(request, user, conversation_id, pending_message_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _mark_failed(request, user, conversation_id, pending_message_id, str(exc))
        raise


def _mark_failed(request, user, conversation_id, message_id, error: str) -> None:
    if not user or not conversation_id or not message_id:
        return
    request.app.state.users.update_message(
        message_id,
        conversation_id,
        user["id"],
        content=f"回复失败：{error}",
        status="failed",
    )
