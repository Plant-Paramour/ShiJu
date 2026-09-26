from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import json
import time

from shiju.contracts import GeneratePoemRequest, JobKind, RewritePoemRequest
from shiju.data import MeterTemplateRepository, RhymeLexicon
from shiju.tasks import parse_pailv_format, parse_tang_format
from shiju.rewriting.validation import validate_rewrite_context
from shiju.rewriting.parser import parse_poem

from ..job_repository import IdempotencyConflict, JobNotFound
from ..schemas import CandidateEvaluationModel, GenerateJobModel, RewriteJobModel, PartialGenerateJobModel
from ..auth import bearer_token, decode_token


router = APIRouter(prefix="/v1/poetry/jobs", tags=["poetry-tools"])


def _poetry_shape(request: Request, payload: dict) -> tuple[int, int, dict[int, int], str | None]:
    """返回句数、句长、押韵句号和韵声；所有错误在入队前变成 422。"""
    meter_type = str(payload.get("meter_type") or "")
    form_name = str(payload.get("form_name") or "")
    if meter_type == "唐诗":
        length, count, rhyme_type = parse_tang_format(form_name)
        return count, length, {line: 1 for line in ({1, 2, 4} if count == 4 else {1, 2, 4, 6, 8})}, "仄" if "仄" in rhyme_type else "平"
    if meter_type == "排律":
        length, count = parse_pailv_format(form_name, payload.get("num_lines"))
        return count, length, {line: 1 for line in range(1, count + 1) if line == 1 or line % 2 == 0}, "平"
    if meter_type == "宋词":
        template = MeterTemplateRepository(request.app.state.project_root / "Songci_Meter").get(form_name, payload.get("variant_name"))
        return len(template.lines), max(line.layout.length for line in template.lines), {
            index + 1: line.rhyme_group for index, line in enumerate(template.lines) if line.rhyme_group is not None
        }, "仄" if "仄" in template.rhyme_type else "平"
    if meter_type == "汉俳":
        pattern = str((payload.get("task_options") or {}).get("line_pattern", "5-7-5")).replace("五", "5").replace("七", "7")
        lengths = [int(item) for item in pattern.replace("－", "-").split("-") if item.isdigit()]
        if lengths not in ([5, 7, 5], [3, 5, 3]):
            raise ValueError("汉俳格式仅支持 5-7-5 或 3-5-3")
        return len(lengths), max(lengths), {}, None
    raise ValueError(f"不支持的诗体: {meter_type}")


def _validate_and_lock_payload(request: Request, payload: dict, *, partial: bool = False) -> dict:
    count, default_length, rhyme_lines, rhyme_tone = _poetry_shape(request, payload)
    fixed = {str(key): str(value).strip() for key, value in (payload.get("fixed_lines") or {}).items()}
    for key, text in fixed.items():
        if not key.isdigit() or not 1 <= int(key) <= count:
            raise ValueError(f"指定句序号超出范围: {key}（{payload.get('form_name')} 共 {count} 句）")
        if not text:
            raise ValueError(f"第 {key} 句不能为空")
        if payload.get("meter_type") != "宋词" and len(text) != default_length:
            raise ValueError(f"第 {key} 句应为 {default_length} 字，实际为 {len(text)} 字")

    book = str(payload.get("rhyme_dict_name") or "Xinyun")
    lexicon = RhymeLexicon(request.app.state.project_root / "Rhyme" / f"{book}.json")
    requested = {str(key): str(value) for key, value in (payload.get("rhyme_parts") or {}).items()}
    valid_groups = {str(group) for group in rhyme_lines.values()}
    locked: dict[str, str] = {}
    for line, text in fixed.items():
        if int(line) not in rhyme_lines or not rhyme_tone:
            continue
        character = next((char for char in reversed(text) if "\u4e00" <= char <= "\u9fff"), "")
        parts = set(lexicon.get_rhyme_part_by_tone(character, rhyme_tone)) if character else set()
        if not parts:
            raise ValueError(f"第 {line} 句末字“{character}”没有可用于{rhyme_tone}韵的韵部")
        if len(parts) == 1:
            locked[str(rhyme_lines[int(line)])] = next(iter(parts))
    for group, part in requested.items():
        if group not in valid_groups:
            raise ValueError(f"{payload.get('form_name')} 不存在韵组 {group}")
        if group in locked:
            continue
        if str(part).lower() != "random" and not any(item_part == part and (not rhyme_tone or tone == rhyme_tone) for _, item_part, tone in lexicon.iter_rhyme_entries()):
            raise ValueError(f"韵部 {part} 没有可用于{rhyme_tone or '当前'}韵的字")

    # 固定句落在押韵句上时，以固定句末字为最高优先级，覆盖用户选择。
    if locked:
        payload["rhyme_mode"] = "fixed"
        payload["rhyme_parts"] = {**requested, **locked}
    payload["fixed_lines"] = fixed
    return payload


def _meter_catalog(request: Request):
    """返回前端方案编辑器可选的宋词词牌及其变体。"""
    from pathlib import Path
    configured = getattr(getattr(request.app.state, "settings", None), "meter_source", None)
    base = Path(configured) if configured else Path(__file__).resolve().parents[3] / "Songci_Meter"
    if not base.is_absolute(): base = Path(__file__).resolve().parents[3] / base
    items = []
    if base.is_dir():
        for path in sorted(base.glob("*.json")):
            if path.name.lower() == "index.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    variants = [str(item.get("name")) for item in (data.get("variants") or []) if isinstance(item, dict) and item.get("name")]
                    name = str(data.get("name") or path.stem)
                elif isinstance(data, list):
                    variants = [str(item.get("name")) for item in data if isinstance(item, dict) and item.get("name")]
                    name = path.stem
                else:
                    continue
                items.append({"name": name, "variants": variants})
            except (OSError, ValueError, TypeError):
                continue
    return {"items": items}


@router.get("/meters")
def list_meters(request: Request):
    return _meter_catalog(request)


@router.get("/rhyme-part")
def lookup_rhyme_part(text: str, rhyme_book: str = "Xinyun", request: Request = None):
    """查询句末字可能的韵部，供部分生成面板锁定用户指定的韵脚。"""
    if not text.strip():
        return {"parts": []}
    project_root = request.app.state.project_root
    lexicon = RhymeLexicon(project_root / "Rhyme" / f"{rhyme_book}.json")
    character = next((char for char in reversed(text.strip()) if "\u4e00" <= char <= "\u9fff"), "")
    return {"character": character, "parts": sorted(set(lexicon.get_rhyme_part(character))) if character else []}


@router.get("/v1/poetry/meters")
def list_meters_alias(request: Request):
    return _meter_catalog(request)


def _authorize(request: Request, authorization: str | None) -> str | None:
    expected = f"Bearer {request.app.state.settings.agent_token}"
    if authorization and hmac.compare_digest(authorization, expected):
        return None
    payload = decode_token(bearer_token(authorization), request.app.state.settings.auth_secret)
    user = request.app.state.users.get(str(payload["sub"])) if payload else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return user["id"]


def _submit(request: Request, kind: str, payload: dict, idempotency_key: str | None, user_id: str | None, conversation_id: str | None = None):
    if conversation_id and (not user_id or request.app.state.users.get_conversation(conversation_id, user_id) is None):
        raise HTTPException(status_code=404, detail="conversation not found")
    repository = request.app.state.jobs
    try:
        job = repository.submit(kind, payload, idempotency_key=idempotency_key, user_id=user_id, conversation_id=conversation_id)
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
    conversation_id: str | None = None,
):
    user_id = _authorize(request, authorization)
    try:
        payload = _validate_and_lock_payload(request, body.model_dump(mode="json"))
        contract = GeneratePoemRequest.from_mapping(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.GENERATE.value, contract.to_dict(), idempotency_key, user_id, conversation_id)


@router.post("/rewrite", status_code=status.HTTP_202_ACCEPTED)
def rewrite_poem_lines(
    body: RewriteJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conversation_id: str | None = None,
):
    user_id = _authorize(request, authorization)
    try:
        payload = _validate_and_lock_payload(request, body.model_dump(mode="json"), partial=True)
        contract = RewritePoemRequest.from_mapping(payload)
        validate_rewrite_context(contract, request.app.state.project_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submit(request, JobKind.REWRITE.value, contract.to_dict(), idempotency_key, user_id, conversation_id)


@router.post("/partial-generate", status_code=status.HTTP_202_ACCEPTED)
def partial_generate(
    body: PartialGenerateJobModel,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conversation_id: str | None = None,
):
    user_id = _authorize(request, authorization)
    payload = body.model_dump(mode="json")
    if payload.get("original_text"):
        poem = parse_poem(payload["original_text"])
        targets = set(payload.get("target_line_numbers") or [])
        payload["fixed_lines"] = {
            str(line.number): line.text for line in poem.lines if line.number not in targets
        }
        try:
            payload = _validate_and_lock_payload(request, payload, partial=True)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        contract = RewritePoemRequest.from_mapping(payload)
        validate_rewrite_context(contract, request.app.state.project_root)
        normalized = contract.to_dict()
    else:
        if not payload.get("fixed_lines"):
            raise HTTPException(
                status_code=422,
                detail="部分生成必须至少指定一句需要原样保留的句子",
            )
        # 补全没有原诗上下文时复用整首生成契约，只复制允许的字段。
        # PartialGenerateJobModel 会自动带上 original_text 等改写字段，不能直接把
        # model_dump() 传给 GeneratePoemRequest，否则会触发 unexpected keyword 500。
        generate_fields = {
            "meter_type", "form_name", "variant_name", "rhyme_dict_name",
            "rhyme_mode", "rhyme_parts", "requirement", "theme", "num_lines",
            "strict_polyphonic", "candidate_count", "task_options", "sampling",
            "fixed_lines",
        }
        try:
            payload = _validate_and_lock_payload(request, payload, partial=True)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        normalized = GeneratePoemRequest.from_mapping(
            {key: value for key, value in payload.items() if key in generate_fields}
        ).to_dict()
    if not normalized.get("fixed_lines"):
        raise HTTPException(
            status_code=422,
            detail="部分生成必须至少指定一句需要原样保留的句子",
        )
    return _submit(request, JobKind.PARTIAL_GENERATE.value, normalized, idempotency_key, user_id, conversation_id)


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


@router.delete("/{job_id}")
def cancel_poetry_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    user_id = _authorize(request, authorization)
    try:
        job = request.app.state.jobs.cancel(job_id, user_id=user_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_response(request, job)


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
                if any(event["event_type"] in {"job.completed", "job.failed", "job.cancelled"} for event in batch):
                    return
                continue
            yield ": keep-alive\n\n"; time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
