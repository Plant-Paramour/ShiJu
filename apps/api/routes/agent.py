from __future__ import annotations

import json
import queue
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
    if body.theme is not None:
        payload["theme"] = body.theme
    if body.rhyme_mode is not None:
        payload["rhyme_mode"] = body.rhyme_mode
    if body.rhyme_parts is not None:
        payload["rhyme_parts"] = body.rhyme_parts
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
        if conversation_id is None:
            conversation = request.app.state.users.create_conversation(user["id"], body.message[:80])
            conversation_id = conversation["id"]
            title_generator = getattr(service, "generate_conversation_title", None)
            title = title_generator(body.message) if callable(title_generator) else body.message[:15]
            request.app.state.users.rename_conversation(conversation_id, user["id"], title)
        elif request.app.state.users.get_conversation(conversation_id, user["id"]) is None: raise HTTPException(status_code=404, detail="conversation not found")
    events = EventRepository(request.app.state.jobs.database)

    def stream():
        turn_id = None
        user_message_id = None
        assistant_message_id = None
        worker_started = False
        try:
            history = None
            if user and conversation_id:
                history = [m for m in request.app.state.users.list_messages(conversation_id, user["id"]) if m.get("status") == "completed"]
                user_message = request.app.state.users.add_message(
                    conversation_id,
                    user["id"],
                    "user",
                    body.message,
                    parent_message_id=body.parent_message_id,
                )
                pending = request.app.state.users.add_message(conversation_id, user["id"], "assistant", "", status="pending")
                user_message_id = user_message["id"]; assistant_message_id = pending["id"]
            turn_id = events.start_turn(user_id=user["id"] if user else None, conversation_id=conversation_id, user_message_id=user_message_id, assistant_message_id=assistant_message_id)
            event_queue: queue.Queue[tuple[str, dict | None]] = queue.Queue()

            def publish(event_type: str, payload: dict) -> None:
                event = events.append_agent_event(turn_id, event_type, payload)
                event_queue.put(("event", {"seq": event["seq"], "event_type": event_type, "payload": payload}))

            def run_turn() -> None:
                reply_parts: list[str] = []
                submitted_jobs: list[dict] = []
                try:
                    publish("turn.started", {"conversation_id": conversation_id, "user_message_id": user_message_id, "assistant_message_id": assistant_message_id})
                    if hasattr(service, "respond_stream"):
                        stream_events = service.respond_stream(body.message, conversation_id or body.session_id, history=history, user_id=user["id"] if user else None, conversation_id=conversation_id, model=body.model)
                    else:
                        try:
                            result = service.respond(body.message, conversation_id or body.session_id, history=history, user_id=user["id"] if user else None, conversation_id=conversation_id, model=body.model)
                        except TypeError:
                            result = service.respond(body.message, conversation_id or body.session_id)
                        stream_events = iter((
                            {"event_type": "assistant.delta", "payload": {"text": result.get("reply", "")}},
                            *({"event_type": "job.submitted", "payload": job} for job in result.get("jobs") or []),
                            {"event_type": "turn.completed", "payload": {"reply": result.get("reply", ""), "jobs": result.get("jobs") or []}},
                        ))
                    for item in stream_events:
                        event_type = item["event_type"]
                        payload = dict(item.get("payload") or {})
                        if event_type == "assistant.delta":
                            reply_parts.append(str(payload.get("text") or ""))
                            if user and conversation_id and assistant_message_id:
                                request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content="".join(reply_parts), status="pending")
                        elif event_type == "job.submitted":
                            submitted_jobs.append(payload)
                            if user and payload.get("job_id"):
                                request.app.state.jobs.assign_context(payload["job_id"], user["id"], conversation_id)
                        elif event_type == "tool.completed":
                            result = payload.get("output", {}).get("result", {})
                            proposal_id = result.get("proposal_id")
                            if proposal_id and assistant_message_id:
                                with request.app.state.jobs.database.connect() as connection:
                                    connection.execute(
                                        "UPDATE agent_proposals SET assistant_message_id=?, updated_at=? WHERE proposal_id=?",
                                        (assistant_message_id, time.time(), proposal_id),
                                    )
                        elif event_type == "turn.completed":
                            reply = str(payload.get("reply") or "".join(reply_parts))
                            jobs = payload.get("jobs") or submitted_jobs
                            job_id = jobs[-1].get("job_id") if jobs else None
                            if user and conversation_id and assistant_message_id:
                                request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content=reply, status="completed", job_id=job_id)
                            payload = {"job_id": job_id, "conversation_id": conversation_id, "session_id": payload.get("session_id")}
                            publish(event_type, payload)
                            events.finish_turn(turn_id)
                            return
                        publish(event_type, payload)
                except Exception as exc:
                    failed_payload = {"error": str(exc)}
                    try:
                        publish("turn.failed", failed_payload)
                        events.finish_turn(turn_id, "failed")
                        if user and conversation_id and assistant_message_id:
                            partial = "".join(reply_parts)
                            content = f"{partial}\n\n生成失败：{exc}" if partial else f"生成失败：{exc}"
                            request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content=content, status="failed")
                    except Exception:
                        pass
                finally:
                    event_queue.put(("done", None))

            threading.Thread(target=run_turn, name=f"agent-turn-{turn_id[:8]}", daemon=True).start()
            worker_started = True
            while True:
                kind, item = event_queue.get()
                if kind == "done":
                    return
                yield f"id: {item['seq']}\nevent: {item['event_type']}\ndata: {json.dumps(item['payload'], ensure_ascii=False)}\n\n"
        except GeneratorExit:
            # SSE 客户端断开只代表订阅结束，后台轮次继续执行并持久化结果。
            return
        except Exception as exc:
            # 生成线程已启动时，任何订阅端异常都不能回写为失败。
            if worker_started:
                return
            if turn_id:
                failed = events.append_agent_event(turn_id, "turn.failed", {"error": str(exc)}); events.finish_turn(turn_id, "failed")
                if user and conversation_id and assistant_message_id:
                    try:
                        request.app.state.users.update_message(assistant_message_id, conversation_id, user["id"], content=f"生成失败：{exc}", status="failed")
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
            user_message = request.app.state.users.add_message(
                conversation_id,
                user["id"],
                "user",
                body.message,
                parent_message_id=body.parent_message_id,
            )
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
                model=body.model,
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
