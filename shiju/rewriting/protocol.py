from __future__ import annotations

from dataclasses import dataclass

from ..domain import PLAN_MARKER, REWRITE_MARKER


class RewriteProtocolError(ValueError):
    code = "MODEL_PROTOCOL_ERROR"


@dataclass(frozen=True)
class RewriteProtocolOutput:
    revision_note: str
    rewrite_text: str

    @property
    def display_prefix(self) -> str:
        return f"修改思路：{self.revision_note}"


def parse_rewrite_protocol(text: str) -> RewriteProtocolOutput:
    if "<think" in text.lower() or "</think" in text.lower():
        raise RewriteProtocolError("重写响应不得包含 <think> 标签")
    if text.count(PLAN_MARKER) != 1 or text.count(REWRITE_MARKER) != 1:
        raise RewriteProtocolError("重写响应必须且只能包含一个 [plan] 和一个 [rewrite]")

    plan_at = text.index(PLAN_MARKER)
    rewrite_at = text.index(REWRITE_MARKER)
    if plan_at > rewrite_at:
        raise RewriteProtocolError("[plan] 必须位于 [rewrite] 之前")
    if text[:plan_at].strip():
        raise RewriteProtocolError("[plan] 之前不得输出其他内容")

    note = text[plan_at + len(PLAN_MARKER) : rewrite_at].strip()
    note_lines = [line.strip() for line in note.splitlines() if line.strip()]
    if len(note_lines) != 1:
        raise RewriteProtocolError("修改思路必须是单独一行")
    note = note_lines[0]
    if len(note) > 80:
        raise RewriteProtocolError("修改思路不得超过 80 个字符")
    if not note.endswith("。"): 
        raise RewriteProtocolError("修改思路必须以句号结束")
    if any(mark in note[:-1] for mark in "。！？!?"):
        raise RewriteProtocolError("修改思路只能包含一句")

    rewrite_text = text[rewrite_at + len(REWRITE_MARKER) :].strip()
    if not rewrite_text:
        raise RewriteProtocolError("[rewrite] 后缺少完整诗稿")
    if PLAN_MARKER in rewrite_text or REWRITE_MARKER in rewrite_text:
        raise RewriteProtocolError("完整诗稿中不得再次出现协议标记")
    return RewriteProtocolOutput(revision_note=note, rewrite_text=rewrite_text)


def build_display_text(revision_note: str, full_text: str) -> str:
    return f"修改思路：{revision_note}\n\n{full_text}"
