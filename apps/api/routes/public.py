from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from shiju.contracts import GeneratePoemRequest, JobKind, RewritePoemRequest

from ..job_repository import IdempotencyConflict, JobNotFound
from ..schemas import GenerateJobModel, RewriteJobModel


router = APIRouter(prefix="/v1/poetry/jobs", tags=["poetry-tools"])


def _authorize(request: Request, authorization: str | None) -> None:
    expected = f"Bearer {request.app.state.settings.agent_token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _submit(request: Request, kind: str, payload: dict, idempotency_key: str | None):
    repository = request.app.state.jobs
    try:
        job = repository.submit(kind, payload, idempotency_key=idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    request.app.state.gpu_provider.ensure_running()
    return {
        "job_id": job.id,
        "status": job.status,
        "waiting_for_worker": not repository.has_live_worker(),
    }


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_poem(
    body: GenerateJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _authorize(request, authorization)
    try:
        contract = GeneratePoemRequest.from_mapping(body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.GENERATE.value, contract.to_dict(), idempotency_key)


@router.post("/rewrite", status_code=status.HTTP_202_ACCEPTED)
def rewrite_poem_lines(
    body: RewriteJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _authorize(request, authorization)
    try:
        contract = RewritePoemRequest.from_mapping(body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.REWRITE.value, contract.to_dict(), idempotency_key)


@router.get("/{job_id}")
def get_poetry_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    _authorize(request, authorization)
    try:
        return request.app.state.jobs.get(job_id).to_dict()
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc

