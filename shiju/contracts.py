from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class JobKind(str, Enum):
    GENERATE = "generate"
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
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    task_type: str = "instruction"
    use_thinking: bool = False
    cipai_data_path: str = "PoeTone-main/data/cipai_data.json"
    num_lines: int | None = None
    strict_polyphonic: bool = True
    candidate_count: int = 3
    task_options: dict[str, Any] = field(default_factory=dict)
    sampling: SamplingOptions = field(default_factory=SamplingOptions)

    def __post_init__(self) -> None:
        for name in ("meter_type", "form_name", "theme", "rhyme_dict_name"):
            if not str(getattr(self, name)).strip():
                raise ContractError(f"{name} 不能为空")
        if not 1 <= self.candidate_count <= 5:
            raise ContractError("candidate_count 必须在 1 到 5 之间")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GeneratePoemRequest":
        data = dict(value)
        data["sampling"] = SamplingOptions.from_mapping(data.get("sampling"))
        data["task_options"] = dict(data.get("task_options") or {})
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RewritePoemRequest:
    original_text: str
    target_line_numbers: tuple[int, ...]
    meter_type: str
    form_name: str
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    theme: str = "局部改写"
    num_lines: int | None = None
    strict_polyphonic: bool = True
    strict_context: bool = True
    candidate_count: int = 3
    task_options: dict[str, Any] = field(default_factory=dict)
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
        if not 1 <= len(normalized) <= 4:
            raise ContractError("首期每次必须指定一至四句")
        if any(number <= 0 for number in normalized):
            raise ContractError("target_line_numbers 使用从 1 开始的正整数")
        if not 1 <= self.candidate_count <= 5:
            raise ContractError("candidate_count 必须在 1 到 5 之间")
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
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobSubmission:
    job_id: str
    status: str
    waiting_for_worker: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
