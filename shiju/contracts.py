from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class JobKind(str, Enum):
    GENERATE = "generate"
    PARTIAL_GENERATE = "partial_generate"
    # Legacy wire name kept for already queued jobs and old clients.
    REWRITE = "rewrite"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContractError(ValueError):
    """Raised when a public request does not satisfy the tool contract."""


@dataclass(frozen=True)
class SamplingOptions:
    max_new_tokens: int = 4096
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    min_p: float = 0.0

    def __post_init__(self) -> None:
        if self.max_new_tokens <= 0:
            raise ContractError("max_new_tokens 必须大于 0")
        if self.temperature <= 0:
            raise ContractError("temperature 必须大于 0")
        if not 0 < self.top_p <= 1:
            raise ContractError("top_p 必须在 (0, 1] 范围内")
        if self.top_k < 0:
            raise ContractError("top_k 不能小于 0")
        if not 0 <= self.min_p <= 1:
            raise ContractError("min_p 必须在 [0, 1] 范围内")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "SamplingOptions":
        return cls(**dict(value or {}))


@dataclass(frozen=True)
class GeneratePoemRequest:
    meter_type: str
    form_name: str
    theme: str
    variant_name: str | None = None
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    task_type: str = "instruction"
    use_thinking: bool = False
    cipai_data_path: str = "PoeTone-main/data/cipai_data.json"
    num_lines: int | None = None
    strict_polyphonic: bool = False
    candidate_count: int = 1
    task_options: dict[str, Any] = field(default_factory=dict)
    rhyme_mode: str = "auto"
    rhyme_parts: dict[str, str] = field(default_factory=dict)
    # Compatibility only. New callers must use PartialGeneratePoemRequest.
    fixed_lines: dict[str, str] = field(default_factory=dict)
    sampling: SamplingOptions = field(default_factory=SamplingOptions)

    def __post_init__(self) -> None:
        for name in ("meter_type", "form_name", "theme", "rhyme_dict_name"):
            if not str(getattr(self, name)).strip():
                raise ContractError(f"{name} 不能为空")
        if not 1 <= self.candidate_count <= 5:
            raise ContractError("candidate_count 必须在 1 到 5 之间")
        if self.rhyme_mode not in {"auto", "fixed", "random"}:
            raise ContractError("rhyme_mode 必须是 auto、fixed 或 random")
        if self.rhyme_mode == "fixed" and not self.rhyme_parts:
            raise ContractError("fixed 模式至少要指定一个 rhyme_parts 韵组")
        if any(not str(key).strip() or not str(value).strip() for key, value in self.rhyme_parts.items()):
            raise ContractError("rhyme_parts 的韵组和韵部不能为空")
        for number, text in self.fixed_lines.items():
            try:
                if int(number) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ContractError("fixed_lines 的句号必须是正整数") from exc
            if not str(text).strip():
                raise ContractError("fixed_lines 的句子不能为空")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GeneratePoemRequest":
        data = dict(value)
        data["sampling"] = SamplingOptions.from_mapping(data.get("sampling"))
        data["task_options"] = dict(data.get("task_options") or {})
        data["fixed_lines"] = {str(k): str(v) for k, v in (data.get("fixed_lines") or {}).items()}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RewritePoemRequest:
    original_text: str
    target_line_numbers: tuple[int, ...]
    meter_type: str
    form_name: str
    variant_name: str | None = None
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    theme: str = "局部改写"
    num_lines: int | None = None
    strict_polyphonic: bool = False
    strict_context: bool = True
    candidate_count: int = 1
    task_options: dict[str, Any] = field(default_factory=dict)
    rhyme_mode: str = "auto"
    rhyme_parts: dict[str, str] = field(default_factory=dict)
    fixed_lines: dict[str, str] = field(default_factory=dict)
    sampling: SamplingOptions = field(
        default_factory=lambda: SamplingOptions(max_new_tokens=512)
    )

    def __post_init__(self) -> None:
        if not self.original_text.strip():
            raise ContractError("original_text 不能为空")
        if not self.meter_type.strip() or not self.form_name.strip():
            raise ContractError("meter_type 和 form_name 不能为空")
        normalized = tuple(sorted(set(self.target_line_numbers)))
        if normalized != self.target_line_numbers:
            raise ContractError("target_line_numbers 必须升序且不能重复")
        if not 1 <= len(normalized) <= 64:
            raise ContractError("每次必须指定一至六十四句")
        if any(number <= 0 for number in normalized):
            raise ContractError("target_line_numbers 使用从 1 开始的正整数")
        if not 1 <= self.candidate_count <= 5:
            raise ContractError("candidate_count 必须在 1 到 5 之间")
        if self.rhyme_mode not in {"auto", "fixed", "random"}:
            raise ContractError("rhyme_mode 必须是 auto、fixed 或 random")
        if self.rhyme_mode == "fixed" and not self.rhyme_parts:
            raise ContractError("fixed 模式至少要指定一个 rhyme_parts 韵组")
        if not self.strict_context:
            raise ContractError("MVP 的指定句重写只支持 strict_context=true")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RewritePoemRequest":
        data = dict(value)
        data["target_line_numbers"] = tuple(data.get("target_line_numbers") or ())
        data["sampling"] = SamplingOptions.from_mapping(
            data.get("sampling") or {"max_new_tokens": 512}
        )
        data["task_options"] = dict(data.get("task_options") or {})
        data["fixed_lines"] = {str(k): str(v) for k, v in (data.get("fixed_lines") or {}).items()}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# One backend contract covers both "补全部分句子" and "改写指定句子".
# The latter only adds original_text/target_line_numbers and negative context;
# both are partial generation from the decoder's point of view.
PartialGeneratePoemRequest = RewritePoemRequest


@dataclass(frozen=True)
class JobSubmission:
    job_id: str
    status: str
    waiting_for_worker: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
