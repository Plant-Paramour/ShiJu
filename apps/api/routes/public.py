from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import json
import time

from shiju.contracts import GeneratePoemRequest, JobKind, RewritePoemRequest

from ..job_repository import IdempotencyConflict, JobNotFound
from ..schemas import CandidateEvaluationModel, GenerateJobModel, RewriteJobModel
from ..auth import bearer_token, decode_token


router = APIRouter(prefix="/v1/poetry/jobs", tags=["poetry-tools"])


def _authorize(request: Request, authorization: str | None) -> str | None:
    expected = f"Bearer {request.app.state.settings.agent_token}"
    if authorization and hmac.compare_digest(authorization, expected):
        return None
    payload = decode_token(bearer_token(authorization), request.app.state.settings.auth_secret)
    user = request.app.state.users.get(str(payload["sub"])) if payload else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return user["id"]


def _submit(request: Request, kind: str, payload: dict, idempotency_key: str | None, user_id: str | None):
    repository = request.app.state.jobs
    try:
        job = repository.submit(kind, payload, idempotency_key=idempotency_key, user_id=user_id)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    request.app.state.gpu_provider.ensure_running()
    return {
        "job_id": job.id,
        "status": job.status,
        "waiting_for_worker": not repository.has_live_worker(),
    }


def _job_response(request: Request, job) -> dict:
    value = job.to_dict(include_request=True)
    value["waiting_for_worker"] = job.status == "queued" and not request.app.state.jobs.has_live_worker()
    return value


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_poem(
    body: GenerateJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    user_id = _authorize(request, authorization)
    try:
        contract = GeneratePoemRequest.from_mapping(body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.GENERATE.value, contract.to_dict(), idempotency_key, user_id)


@router.post("/rewrite", status_code=status.HTTP_202_ACCEPTED)
def rewrite_poem_lines(
    body: RewriteJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    user_id = _authorize(request, authorization)
    try:
        contract = RewritePoemRequest.from_mapping(body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.REWRITE.value, contract.to_dict(), idempotency_key, user_id)


@router.get("")
def list_poetry_jobs(
    request: Request,
    authorization: str | None = Header(default=None),
    conversation_id: str | None = None,
    active_only: bool = False,
):
    user_id = _authorize(request, authorization)
    if user_id is None:
        return {"items": []}
    jobs = request.app.state.jobs.list_for_user(
        user_id,
        conversation_id,
        active_only=active_only,
    )
    return {"items": [_job_response(request, job) for job in jobs]}


@router.get("/{job_id}")
def get_poetry_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user_id = _authorize(request, authorization)
    try:
        job = request.app.state.jobs.get(job_id)
        if user_id and job.user_id != user_id:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_response(request, job)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/{job_id}/state")
def get_poetry_job_state(job_id: str, request: Request, authorization: str | None = Header(default=None)):
    user_id = _authorize(request, authorization)
    try:
        job = request.app.state.jobs.get(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    if user_id and job.user_id != user_id: raise HTTPException(status_code=404, detail="job not found")
    return request.app.state.jobs.snapshot(job_id)


@router.get("/{job_id}/snapshot")
def get_poetry_job_snapshot(job_id: str, request: Request, authorization: str | None = Header(default=None)):
    return get_poetry_job_state(job_id, request, authorization)


@router.put("/{job_id}/candidates/{ordinal}/evaluation")
def save_candidate_evaluation(
    job_id: str,
    ordinal: int,
    body: CandidateEvaluationModel,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user_id = _authorize(request, authorization)
    if user_id is None:
        raise HTTPException(status_code=403, detail="用户作品评分需要登录账户")
    try:
        evaluation = request.app.state.jobs.save_candidate_evaluation(
            job_id,
            ordinal,
            body.evaluation,
            user_id=user_id,
        )
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "ordinal": ordinal, "evaluation": evaluation}


@router.get("/{job_id}/events")
def poetry_job_events(job_id: str, request: Request, authorization: str | None = Header(default=None), after: int = 0):
    user_id = _authorize(request, authorization)
    try:
        job = request.app.state.jobs.get(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    if user_id and job.user_id != user_id: raise HTTPException(status_code=404, detail="job not found")
    from apps.api.event_repository import EventRepository
    events = EventRepository(request.app.state.jobs.database)
    def stream():
        cursor = after; deadline = time.time() + 25
        while time.time() < deadline:
            batch = events.list_job_events(job_id, after=cursor)
            if batch:
                for event in batch:
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event['payload'], ensure_ascii=False)}\n\n"
                if any(event["event_type"] in {"job.completed", "job.failed"} for event in batch):
                    return
                continue
            yield ": keep-alive\n\n"; time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
