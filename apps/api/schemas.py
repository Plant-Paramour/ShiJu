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


class RegisterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class PasswordResetRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)


class PasswordResetConfirmModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProfilePatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    notify_on_reaction: bool | None = None


class ForumThreadCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=30000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    poem_ids: list[str] = Field(default_factory=list, max_length=8)


class ForumThreadPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=30000)
    is_pinned: bool | None = None
    is_locked: bool | None = None
    is_featured: bool | None = None
    section_id: str | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


class ForumReplyCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=20000)
    parent_reply_id: str | None = None
    quoted_reply_id: str | None = None
    poem_ids: list[str] = Field(default_factory=list, max_length=8)


class ForumReplyPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=20000)


class ForumReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)
    thread_id: str | None = None
    reply_id: str | None = None


class ForumReactionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reaction_type: str = Field(pattern="^(like|question)$")


class ForumDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(thread|reply)$")
    thread_id: str | None = None
    section_id: str | None = None
    title: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=30000)
    tags: list[str] = Field(default_factory=list, max_length=12)


class ModeratorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class AdminUserCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    role: str = Field(default="user", pattern="^(user|admin)$")


class AdminUserPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    role: str | None = Field(default=None, pattern="^(user|admin)$")


class ForumSectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=80, pattern="^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0, ge=0, le=10000)


class ForumSectionPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    slug: str | None = Field(default=None, min_length=1, max_length=80, pattern="^[a-z0-9][a-z0-9-]*$")
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_locked: bool | None = None


class PermissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permission: str = Field(pattern="^(none|read|write|moderate)$")


class ReportResolutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(resolved|dismissed)$")
    note: str = Field(default="", max_length=1000)


class ConversationCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="新建对话", max_length=15)


class ConversationPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=15)
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
    is_public: bool | None = None


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
