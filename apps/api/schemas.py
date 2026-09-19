from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SamplingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_new_tokens: int = Field(default=4096, gt=0)
    temperature: float = Field(default=0.6, gt=0)
    top_p: float = Field(default=0.95, gt=0, le=1)
    top_k: int = Field(default=20, ge=0)
    min_p: float = Field(default=0.0, ge=0, le=1)


class GenerateJobModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    candidate_count: int = Field(default=3, ge=1, le=5)
    task_options: dict[str, Any] = Field(default_factory=dict)
    sampling: SamplingModel = Field(default_factory=SamplingModel)


class RewriteJobModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str
    target_line_numbers: list[int] = Field(min_length=1, max_length=4)
    meter_type: str
    form_name: str
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    theme: str = "局部改写"
    num_lines: int | None = None
    strict_polyphonic: bool = True
    strict_context: bool = True
    candidate_count: int = Field(default=3, ge=1, le=5)
    task_options: dict[str, Any] = Field(default_factory=dict)
    sampling: SamplingModel = Field(
        default_factory=lambda: SamplingModel(max_new_tokens=512)
    )


class WorkerClaimModel(BaseModel):
    worker_id: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    wait_seconds: int = Field(default=15, ge=0, le=20)


class WorkerIdentityModel(BaseModel):
    worker_id: str


class WorkerCompleteModel(WorkerIdentityModel):
    result: dict[str, Any]


class WorkerFailModel(WorkerIdentityModel):
    code: str
    message: str
    retryable: bool = False
