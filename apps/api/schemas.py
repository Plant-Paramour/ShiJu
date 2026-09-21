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


class AgentChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = Field(default=None, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)


class AgentProposalSubmitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=128)
    requirement: str = Field(max_length=12000)
    candidate_count: int = Field(default=1, ge=1, le=5)
    meter_type: str
    form_name: str
    rhyme_dict_name: str = "Xinyun"
    strict_polyphonic: bool = True
    num_lines: int | None = Field(default=None, ge=4, le=128)
    task_options: dict[str, Any] = Field(default_factory=dict)


class CandidateEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation: dict[str, Any]


class LoginModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ConversationCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="新建对话", max_length=120)


class ConversationPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=120)
    folder_id: str | None = Field(default=None, max_length=128)
    clear_folder: bool = False


class FolderCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class FolderPatchModel(FolderCreateModel):
    pass


class PoemPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=20000)
    work_type: str | None = Field(default=None, max_length=32)
    meter_type: str | None = Field(default=None, max_length=64)
    form_name: str | None = Field(default=None, max_length=128)


class CollectionCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class CollectionPatchModel(CollectionCreateModel):
    pass


class CollectionItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poem_id: str = Field(min_length=1, max_length=128)


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
    candidate_count: int = Field(default=1, ge=1, le=5)
    task_options: dict[str, Any] = Field(default_factory=dict)
    sampling: SamplingModel = Field(default_factory=SamplingModel)


class RewriteJobModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str
    target_line_numbers: list[int] = Field(min_length=1, max_length=64)
    meter_type: str
    form_name: str
    rhyme_dict_name: str = "Xinyun"
    requirement: str = ""
    theme: str = "局部改写"
    num_lines: int | None = None
    strict_polyphonic: bool = True
    strict_context: bool = True
    candidate_count: int = Field(default=1, ge=1, le=5)
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


class WorkerCandidateModel(WorkerIdentityModel):
    ordinal: int = Field(ge=1)
    status: str | None = None
    attempt: int | None = Field(default=None, ge=0)
    partial_text: str | None = None
    raw_text: str | None = None
    title: str | None = None
    content: str | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
