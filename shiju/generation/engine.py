from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import GeneratePoemRequest, RewritePoemRequest
from ..data import RhymeLexicon
from ..domain import REWRITE_MARKER
from ..rewriting.parser import PoemParseError, parse_poem
from ..rewriting.planner import RewritePlan
from ..rewriting.prompt import build_rewrite_messages
from ..rewriting.protocol import (
    RewriteProtocolError,
    build_display_text,
    parse_rewrite_protocol,
)
from ..tasks import (
    HanpaiOptions,
    PailvOptions,
    TangOptions,
    TaskContext,
    TaskRequest,
    default_task_registry,
)
from ..vocab import VocabIndex
from .model_runner import ModelRunner
from .protocol import GenerationProtocolError, parse_generation_protocol
from .result import GenerationCandidate
from .session import ActivationMarkerDeadline


class ModelProtocolFailure(RuntimeError):
    code = "MODEL_PROTOCOL_ERROR"


class GenerationEngine:
    """Stateless request facade around a resident model and cached vocab indexes."""

    def __init__(
        self,
        runner: ModelRunner,
        *,
        rhyme_dir: str | Path = "Rhyme",
        meter_source: str | Path = "Songci_Meter",
        boundary_coherence_penalty: float = 50.0,
    ):
        self.runner = runner
        self.rhyme_dir = Path(rhyme_dir)
        self.meter_source = Path(meter_source)
        self.boundary_coherence_penalty = boundary_coherence_penalty
        self._resources: dict[str, tuple[RhymeLexicon, VocabIndex]] = {}

    def generate_poem(
        self,
        request: GeneratePoemRequest,
        *,
        use_constraints: bool = True,
        on_candidate_event=None,
    ) -> dict[str, Any]:
        runtime, vocab = self._runtime_for(request)
        prompt = self.runner.render_chat(
            runtime.messages,
            enable_thinking=request.use_thinking,
        )
        prompt_length = self._prompt_length(prompt)
        candidates = []
        for ordinal in range(1, request.candidate_count + 1):
            last_error = None
            for attempt in range(1, 4):
                if on_candidate_event: on_candidate_event("candidate.started", {"ordinal": ordinal, "attempt": attempt})
                processors = None
                if use_constraints:
                    processors = (runtime.create_processor(vocab, self.runner.tokenizer, prompt_length),)
                partial = ""
                def on_text(piece: str) -> None:
                    nonlocal partial
                    partial += piece
                    if on_candidate_event:
                        on_candidate_event("candidate.delta", {"ordinal": ordinal, "attempt": attempt, "delta": piece, "partial_text": partial})
                if hasattr(self.runner, "generate_streaming"):
                    raw = self.runner.generate_streaming(prompt, request.sampling, logits_processors=processors, on_text=on_text)
                else:
                    raw = self.runner.generate(prompt, request.sampling, logits_processors=processors)
                    on_text(raw)
                try:
                    parsed = parse_generation_protocol(raw)
                except GenerationProtocolError as exc:
                    last_error = exc
                    if on_candidate_event: on_candidate_event("candidate.retry", {"ordinal": ordinal, "attempt": attempt, "error": str(exc)})
                    continue
                candidate = {"raw_output": raw, "text": runtime.process_output(raw), "title": parsed.title, "content": parsed.content}
                candidates.append(candidate)
                if on_candidate_event: on_candidate_event("candidate.completed", {"ordinal": ordinal, "attempt": attempt, **candidate})
                break
            else:
                if on_candidate_event: on_candidate_event("candidate.failed", {"ordinal": ordinal, "error": str(last_error)})
                raise ModelProtocolFailure(f"候选 {ordinal} 连续三次未遵守生成协议: {last_error}") from last_error
        return {
            "status": "succeeded",
            "candidates": candidates,
            "config": request.to_dict(),
        }

    def rewrite_poem(self, request: RewritePoemRequest, *, on_candidate_event=None) -> dict[str, Any]:
        parsed = parse_poem(request.original_text)
        if request.meter_type == "排律" and request.num_lines is None:
            request = RewritePoemRequest(
                **{
                    **request.to_dict(),
                    "target_line_numbers": request.target_line_numbers,
                    "sampling": request.sampling,
                    "num_lines": len(parsed.lines),
                }
            )
        runtime, vocab = self._runtime_for(request)
        plan = RewritePlan.build(request, runtime)
        messages = build_rewrite_messages(request, plan.poem)
        prompt = self.runner.render_chat(messages, enable_thinking=False)
        prompt_length = self._prompt_length(prompt)

        candidates: list[dict[str, Any]] = []
        for ordinal in range(1, request.candidate_count + 1):
            last_error: Exception | None = None
            for attempt in range(3):
                attempt_number = attempt + 1
                if on_candidate_event: on_candidate_event("candidate.started", {"ordinal": ordinal, "attempt": attempt_number})
                active_messages = messages
                if attempt:
                    active_messages = [
                        messages[0],
                        {
                            "role": "user",
                            "content": messages[1]["content"] + (
                                "\n\n上一次响应未遵守格式。必须只输出一行 [plan] 规划，"
                                "随后输出 [rewrite] 和包含固定原句的完整诗稿。"
                            ),
                        },
                    ]
                    prompt = self.runner.render_chat(active_messages, enable_thinking=False)
                    prompt_length = self._prompt_length(prompt)
                processor = runtime.create_processor(
                    vocab,
                    self.runner.tokenizer,
                    prompt_length,
                    controller=plan.create_controller(),
                    activation_marker=REWRITE_MARKER,
                )
                deadline = ActivationMarkerDeadline(
                    self.runner.tokenizer,
                    prompt_length,
                    REWRITE_MARKER,
                    max_tokens=128,
                )
                partial = ""
                def on_text(piece: str) -> None:
                    nonlocal partial
                    partial += piece
                    if on_candidate_event: on_candidate_event("candidate.delta", {"ordinal": ordinal, "attempt": attempt_number, "delta": piece, "partial_text": partial})
                if hasattr(self.runner, "generate_streaming"):
                    raw = self.runner.generate_streaming(prompt, request.sampling, logits_processors=(processor,), stopping_criteria=(deadline,), on_text=on_text)
                else:
                    raw = self.runner.generate(prompt, request.sampling, logits_processors=(processor,), stopping_criteria=(deadline,))
                    on_text(raw)
                try:
                    protocol = parse_rewrite_protocol(raw)
                    replacements = plan.replacements_from_text(protocol.rewrite_text)
                    full_text = plan.apply(replacements)
                except (RewriteProtocolError, PoemParseError) as exc:
                    last_error = exc
                    if on_candidate_event: on_candidate_event("candidate.retry", {"ordinal": ordinal, "attempt": attempt_number, "error": str(exc)})
                    continue
                candidate = {
                        "revision_note": protocol.revision_note,
                        "replacements": {
                            str(number): text for number, text in replacements.items()
                        },
                        "full_text": full_text,
                        "display_text": build_display_text(
                            protocol.revision_note,
                            full_text,
                        ),
                        "validation": {
                            "scope": "rewritten_lines",
                            "structure": 100,
                            "tonal": 100,
                            "rhyme": 100,
                        },
                        "raw_output": raw,
                    }
                candidates.append(candidate)
                if on_candidate_event: on_candidate_event("candidate.completed", {"ordinal": ordinal, "attempt": attempt_number, "title": request.theme, "content": full_text, **candidate})
                break
            else:
                if on_candidate_event: on_candidate_event("candidate.failed", {"ordinal": ordinal, "attempt": 3, "error": str(last_error)})
                raise ModelProtocolFailure(
                    f"模型连续三次未遵守重写协议: {last_error}"
                ) from last_error

        primary = candidates[0]
        return {
            "status": "succeeded",
            **{key: value for key, value in primary.items() if key != "raw_output"},
            "candidates": candidates,
            "config": request.to_dict(),
        }

    def _runtime_for(self, request: GeneratePoemRequest | RewritePoemRequest):
        lexicon, vocab = self._resources_for(request.rhyme_dict_name)
        options = request.task_options
        task_request = TaskRequest(
            meter_type=request.meter_type,
            form_name=request.form_name,
            theme=request.theme,
            rhyme_dict_name=request.rhyme_dict_name,
            requirement=request.requirement,
            task_type=(request.task_type if isinstance(request, GeneratePoemRequest) else "instruction"),
            use_thinking=(request.use_thinking if isinstance(request, GeneratePoemRequest) else False),
            strict_polyphonic=request.strict_polyphonic,
            cipai_data_path=(
                request.cipai_data_path
                if isinstance(request, GeneratePoemRequest)
                else "PoeTone-main/data/cipai_data.json"
            ),
            num_lines=request.num_lines,
            hanpai=HanpaiOptions(**options) if request.meter_type == "汉俳" else HanpaiOptions(),
            tang=(
                TangOptions(allow_aojiu=bool(options.get("allow_aojiu", False)))
                if request.meter_type == "唐诗"
                else TangOptions()
            ),
            pailv=(
                PailvOptions(allow_aojiu=bool(options.get("allow_aojiu", True)))
                if request.meter_type == "排律"
                else PailvOptions()
            ),
        )
        context = TaskContext(
            tokenizer=self.runner.tokenizer,
            vocab=vocab,
            lexicon=lexicon,
            meter_source=self.meter_source,
            boundary_coherence_penalty=self.boundary_coherence_penalty,
        )
        return default_task_registry().create(task_request, context), vocab

    def _resources_for(self, rhyme_dict_name: str) -> tuple[RhymeLexicon, VocabIndex]:
        cached = self._resources.get(rhyme_dict_name)
        if cached is not None:
            return cached
        lexicon = RhymeLexicon(self.rhyme_dir / f"{rhyme_dict_name}.json")
        vocab = VocabIndex(self.runner.tokenizer, lexicon)
        self._resources[rhyme_dict_name] = (lexicon, vocab)
        return lexicon, vocab

    def _prompt_length(self, prompt: str) -> int:
        encoded = self.runner.tokenizer(prompt, return_tensors="pt")
        return encoded.input_ids.shape[1]
