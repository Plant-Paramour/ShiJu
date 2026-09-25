from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shiju.contracts import GeneratePoemRequest, RewritePoemRequest
from shiju.data import MeterTemplateRepository, RhymeLexicon
from shiju.rewriting.parser import parse_poem

from .framework import ToolContext
from .jobs import PoetryJobs


RHYME_BOOKS = {
    "Xinyun": "中华新韵",
    "Pinshui": "平水韵",
    "Cilin": "词林正韵",
    "Tongyun": "中华通韵",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[Mapping[str, Any], ToolContext], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class PendingProposal:
    id: str
    kind: str
    payload: dict[str, Any]
    prepared_turn: int
    submitted_job_id: str | None = None


class AgentToolbox:
    def __init__(self, project_root: str | Path, jobs: PoetryJobs):
        self._root = Path(project_root)
        self._jobs = jobs
        self._lexicons: dict[str, RhymeLexicon] = {}
        self._pending: PendingProposal | None = None
        loader = getattr(jobs, "load_pending_proposal", None)
        saved = loader() if loader else None
        if saved:
            self._pending = PendingProposal(**saved)
        self._tools = {tool.name: tool for tool in self._build_tools()}

    @property
    def pending(self) -> PendingProposal | None:
        return self._pending

    def reset(self) -> None:
        self._pending = None

    def _save_pending(self) -> None:
        saver = getattr(self._jobs, "save_pending_proposal", None)
        if saver and self._pending:
            saver(
                {
                    "id": self._pending.id,
                    "kind": self._pending.kind,
                    "payload": self._pending.payload,
                    "prepared_turn": self._pending.prepared_turn,
                    "submitted_job_id": self._pending.submitted_job_id,
                }
            )

    def submit_pending_if_confirmed(self, context: ToolContext) -> dict | None:
        """在模型漏调 submit 工具时，由宿主按同一确认门禁兜底提交。"""
        proposal = self._pending
        if proposal is None or proposal.submitted_job_id:
            return None
        later_confirmation = (
            proposal.prepared_turn < context.turn_index
            and _is_explicit_confirmation(context.user_message)
        )
        if not later_confirmation:
            return None
        if proposal.kind == "generate":
            return self._submit_generation({"proposal_id": proposal.id}, context)
        if proposal.kind == "rewrite":
            return self._submit_rewrite({"proposal_id": proposal.id}, context)
        return None

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: Mapping[str, Any], context: ToolContext) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ValueError(f"未知工具: {name}") from exc
        return tool.handler(arguments, context)

    def _build_tools(self) -> tuple[ToolSpec, ...]:
        rhyme_enum = list(RHYME_BOOKS)
        return (
            ToolSpec(
                "list_rhyme_books",
                "列出诗矩本地可查询的韵书。",
                _object_schema({}),
                self._list_rhyme_books,
            ),
            ToolSpec(
                "lookup_rhyme",
                "查询一个或多个汉字在指定韵书中的平仄和韵部。涉及具体字音时应调用。",
                _object_schema(
                    {
                        "text": {"type": "string", "description": "要查询的汉字，最多 32 字"},
                        "rhyme_book": {"type": "string", "enum": rhyme_enum},
                    },
                    ["text", "rhyme_book"],
                ),
                self._lookup_rhyme,
            ),
            ToolSpec(
                "check_pingze",
                "按指定韵书判定整段内容的平仄。凡涉及一句或多句的平仄、平仄是否正确、对仗或格律核验，必须调用；不要凭模型记忆判断。遇到返回‘中’的多音字，必须结合完整句意、词性和上下文选择实际读音，不能把‘中’直接当作错误；调用时应填写 semantic_context。标准句式中的‘中’是该位置平仄皆可，也不能误判为错误。宋词查询时同时传 stanza_number（阕编号）和 sentence_number（句编号），工具会返回定位信息；词牌格式另用 get_ci_meter 查询。",
                _object_schema(
                    {
                        "rhyme_book": {"type": "string", "enum": rhyme_enum},
                        "content": {"type": "string", "description": "待判定的汉字内容，最多 64 字，可含标点和换行"},
                        "semantic_context": {"type": "string", "description": "句意、词性和上下文，用于判断多音字实际读音；出现多音字时必填，最多 300 字"},
                        "stanza_number": {"type": "integer", "minimum": 1, "description": "宋词阕编号，从 1 开始"},
                        "sentence_number": {"type": "integer", "minimum": 1, "description": "宋词句编号，从 1 开始"},
                    },
                    ["rhyme_book", "content"],
                ),
                self._check_pingze,
            ),
            ToolSpec(
                "get_rhyme_part",
                "按韵部名称查询指定韵书收录的字，可限定平声或仄声。",
                _object_schema(
                    {
                        "rhyme_book": {"type": "string", "enum": rhyme_enum},
                        "rhyme_part": {"type": "string"},
                        "tone": {"type": "string", "enum": ["全部", "平", "仄"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    ["rhyme_book", "rhyme_part"],
                ),
                self._get_rhyme_part,
            ),
            ToolSpec(
                "list_ci_meters",
                "列出本地支持的宋词词牌及默认变体。",
                _object_schema({}),
                self._list_ci_meters,
            ),
            ToolSpec(
                "get_ci_meter",
                "查询一个词牌的逐句平仄、句读、阕结构和押韵位置。",
                _object_schema(
                    {
                        "name": {"type": "string", "description": "词牌名，如浣溪沙"},
                        "variant_name": {"type": "string", "description": "可选变体名"},
                    },
                    ["name"],
                ),
                self._get_ci_meter,
            ),
            ToolSpec(
                "list_supported_forms",
                "查询诗矩支持的唐诗、宋词、汉俳和排律形式及参数约束。",
                _object_schema({}),
                self._list_supported_forms,
            ),
            ToolSpec(
                "prepare_generation",
                "准备并保存整首格律诗词生成方案。返回的 editable_prompt 和完整配置会由界面展示并直接提交；本轮不要调用 submit_generation。",
                _generation_schema(),
                self._prepare_generation,
            ),
            ToolSpec(
                "submit_generation",
                "提交当前整首生成方案。只能用于用户在后续纯文本消息中明确确认的场景；Web 按钮不经过此工具。",
                _object_schema({"proposal_id": {"type": "string"}}, ["proposal_id"]),
                self._submit_generation,
            ),
            ToolSpec(
                "prepare_rewrite",
                "准备并保存指定句重写方案。返回的 editable_prompt 和完整配置会由界面展示并直接提交；本轮不要调用 submit_rewrite。",
                _rewrite_schema(),
                self._prepare_rewrite,
            ),
            ToolSpec(
                "submit_rewrite",
                "提交当前指定句重写方案。只能用于用户在后续纯文本消息中明确确认的场景；Web 按钮不经过此工具。",
                _object_schema({"proposal_id": {"type": "string"}}, ["proposal_id"]),
                self._submit_rewrite,
            ),
            ToolSpec(
                "get_poetry_job",
                "查询已经提交的格律生成或重写任务状态与结果。任务完成时必须读取 generated_poems 中的真实标题和正文；不得根据主题自行补写诗句。",
                _object_schema({"job_id": {"type": "string"}}, ["job_id"]),
                self._get_poetry_job,
            ),
        )

    def _list_rhyme_books(self, arguments, context) -> dict:
        return {
            "rhyme_books": [
                {"id": key, "name": value} for key, value in RHYME_BOOKS.items()
            ]
        }

    def _lookup_rhyme(self, arguments, context) -> dict:
        text = str(arguments.get("text", "")).strip()
        if not text:
            raise ValueError("text 不能为空")
        chars = list(dict.fromkeys(char for char in text if "\u3400" <= char <= "\u9fff"))
        if not chars:
            raise ValueError("text 中没有可查询的汉字")
        if len(chars) > 32:
            raise ValueError("单次最多查询 32 个不同汉字")
        book = self._book_name(arguments.get("rhyme_book"))
        lexicon = self._lexicon(book)
        entries = []
        for char in chars:
            tones = lexicon.get_pingze(char)
            entries.append(
                {
                    "char": char,
                    "tones": tones,
                    "rhyme_parts": lexicon.get_rhyme_part(char),
                    "parts_by_tone": {
                        tone: lexicon.get_rhyme_part_by_tone(char, tone) for tone in tones
                    },
                    "found": bool(tones),
                }
            )
        return {"rhyme_book": book, "entries": entries}

    def _check_pingze(self, arguments, context) -> dict:
        content = str(arguments.get("content", "")).strip()
        if not content:
            raise ValueError("content 不能为空")
        chars = [char for char in content if "\u3400" <= char <= "\u9fff"]
        if not chars:
            raise ValueError("content 中没有可查询的汉字")
        if len(chars) > 64:
            raise ValueError("单次最多查询 64 个汉字")
        book = self._book_name(arguments.get("rhyme_book"))
        lexicon = self._lexicon(book)
        entries = []
        for char in chars:
            tones = lexicon.get_pingze(char)
            entries.append({"char": char, "tones": tones, "found": bool(tones)})
        return {
            "rhyme_book": book,
            "content": content,
            "pingze": "".join(
                entry["tones"][0] if len(entry["tones"]) == 1 else "中" if entry["tones"] else "?"
                for entry in entries
            ),
            "entries": entries,
            "uncertain_chars": [entry["char"] for entry in entries if len(entry["tones"]) != 1],
            "stanza_number": arguments.get("stanza_number"),
            "sentence_number": arguments.get("sentence_number"),
            "semantic_context": str(arguments.get("semantic_context") or "").strip() or None,
            "note": "返回的‘中’表示该字在此韵书中兼有平、仄，必须结合句意、词性和上下文从 entries[tones] 中选择实际读音；它不是错误。标准句式里的‘中’表示该位置平仄皆可。?表示韵书未收录。这里只判定字音，不代替词牌格律核验。",
        }

    def _get_rhyme_part(self, arguments, context) -> dict:
        book = self._book_name(arguments.get("rhyme_book"))
        part = str(arguments.get("rhyme_part", "")).strip()
        if not part:
            raise ValueError("rhyme_part 不能为空")
        tone = str(arguments.get("tone", "全部"))
        if tone not in {"全部", "平", "仄"}:
            raise ValueError("tone 只能是全部、平或仄")
        limit = int(arguments.get("limit", 80))
        if not 1 <= limit <= 200:
            raise ValueError("limit 必须在 1 到 200 之间")
        matches = []
        for char, entry_part, entry_tone in self._lexicon(book).iter_rhyme_entries():
            if entry_part == part and (tone == "全部" or entry_tone == tone):
                matches.append({"char": char, "tone": entry_tone})
        if not matches:
            raise ValueError(f"{book} 中未找到韵部 {part}")
        return {
            "rhyme_book": book,
            "rhyme_part": part,
            "tone": tone,
            "total": len(matches),
            "entries": matches[:limit],
            "truncated": len(matches) > limit,
        }

    def _list_ci_meters(self, arguments, context) -> dict:
        meters = []
        for path in sorted((self._root / "Songci_Meter").glob("*.json")):
            root = json.loads(path.read_text(encoding="utf-8"))
            # index.json is a directory-level list, not a meter definition.
            if not isinstance(root, dict):
                continue
            meters.append(
                {
                    "name": root.get("name") or path.stem,
                    "default_variant": root.get("default_variant"),
                    "variants": [item.get("name") for item in root.get("variants", [])],
                }
            )
        return {"meters": meters}

    def _get_ci_meter(self, arguments, context) -> dict:
        name = str(arguments.get("name", "")).strip()
        if not name:
            raise ValueError("name 不能为空")
        variant_name = str(arguments.get("variant_name") or "").strip() or None
        template = MeterTemplateRepository(self._root / "Songci_Meter").get(
            name, variant_name
        )
        return {
            "name": template.name,
            "variant_name": template.variant_name,
            "rhyme_type": template.rhyme_type,
            "stanzas": [
                {
                    "index": stanza.index + 1,
                    "lines": [
                        {
                            "pattern": line.raw_pattern,
                            "characters": len(line.tone_options),
                            "rhyme_group": line.rhyme_group,
                        }
                        for line in stanza.lines
                    ],
                }
                for stanza in template.stanzas
            ],
        }

    def _list_supported_forms(self, arguments, context) -> dict:
        return {
            "唐诗": {
                "forms": ["五言绝句", "七言绝句", "五言律诗", "七言律诗"],
                "note": "对应形式可注明仄韵；默认平韵，默认不启用拗救。",
            },
            "宋词": {
                "forms": [item["name"] for item in self._list_ci_meters({}, context)["meters"]],
                "note": "按本地词牌模板逐字约束。",
            },
            "汉俳": {
                "forms": ["汉俳"],
                "line_patterns": ["5-7-5", "3-5-3"],
            },
            "排律": {
                "forms": ["五言排律", "七言排律"],
                "note": "句数必须是不少于十句的偶数，默认启用拗救。",
            },
        }

    def _prepare_generation(self, arguments, context: ToolContext) -> dict:
        payload = _generation_payload(arguments)
        if "candidate_count" not in arguments:
            payload["candidate_count"] = _requested_candidate_count(context.user_message)
        request = GeneratePoemRequest.from_mapping(payload)
        self._validate_form(
            request.meter_type,
            request.form_name,
            request.num_lines,
            request.task_options,
        )
        self._validate_rhyme_selection(
            request.rhyme_dict_name,
            request.rhyme_mode,
            request.rhyme_parts,
            request.meter_type,
            request.form_name,
        )
        return self._store_proposal("generate", request.to_dict(), context)

    def _prepare_rewrite(self, arguments, context: ToolContext) -> dict:
        payload = _rewrite_payload(arguments)
        if "candidate_count" not in arguments:
            payload["candidate_count"] = _requested_candidate_count(context.user_message)
        request = RewritePoemRequest.from_mapping(payload)
        self._validate_form(
            request.meter_type,
            request.form_name,
            request.num_lines,
            request.task_options,
        )
        self._validate_rhyme_selection(
            request.rhyme_dict_name,
            request.rhyme_mode,
            request.rhyme_parts,
            request.meter_type,
            request.form_name,
        )
        poem = parse_poem(request.original_text)
        if request.target_line_numbers[-1] > len(poem.lines):
            raise ValueError(
                f"目标句号超出原文范围；原文解析为 {len(poem.lines)} 句"
            )
        return self._store_proposal("rewrite", request.to_dict(), context)

    def _store_proposal(self, kind: str, payload: dict, context: ToolContext) -> dict:
        proposal = PendingProposal(
            id=str(uuid.uuid4()),
            kind=kind,
            payload=payload,
            prepared_turn=context.turn_index,
        )
        self._pending = proposal
        self._save_pending()
        preview_fields = (
            "meter_type",
            "form_name",
            "theme",
            "rhyme_dict_name",
            "rhyme_mode",
            "rhyme_parts",
            "requirement",
            "num_lines",
            "target_line_numbers",
            "strict_polyphonic",
            "candidate_count",
            "task_options",
        )
        return {
            "proposal_id": proposal.id,
            "kind": proposal.kind,
            "proposal": {key: payload[key] for key in preview_fields if key in payload},
            "editable_prompt": payload.get("requirement", ""),
            "candidate_count": payload.get("candidate_count", 1),
            "can_submit_now": False,
            "instruction": "完整展示 editable_prompt 和配置；Web 界面会提供直接提交按钮，本轮不要调用 submit 工具。",
        }

    def _submit_generation(self, arguments, context: ToolContext) -> dict:
        proposal = self._confirmed_proposal(arguments, context, "generate")
        result = self._jobs.submit_generate(proposal.payload, proposal.id)
        proposal.submitted_job_id = str(result.get("job_id") or "") or None
        self._save_pending()
        return result

    def _submit_rewrite(self, arguments, context: ToolContext) -> dict:
        proposal = self._confirmed_proposal(arguments, context, "rewrite")
        result = self._jobs.submit_rewrite(proposal.payload, proposal.id)
        proposal.submitted_job_id = str(result.get("job_id") or "") or None
        self._save_pending()
        return result

    def _confirmed_proposal(
        self,
        arguments: Mapping[str, Any],
        context: ToolContext,
        expected_kind: str,
    ) -> PendingProposal:
        proposal_id = str(arguments.get("proposal_id", ""))
        proposal = self._pending
        if proposal is None or proposal.id != proposal_id:
            active = proposal.id if proposal else "无"
            raise ValueError(f"proposal_id 不是当前待确认方案；当前方案为 {active}")
        if proposal.kind != expected_kind:
            raise ValueError(f"当前方案类型是 {proposal.kind}，不能作为 {expected_kind} 提交")
        if proposal.submitted_job_id:
            raise ValueError(f"该方案已经提交，job_id={proposal.submitted_job_id}")
        if proposal.prepared_turn >= context.turn_index:
            raise ValueError("方案准备后应由界面提交，不能在同一轮调用 submit 工具")
        if not _is_explicit_confirmation(context.user_message):
            raise ValueError("用户当前消息没有要求执行该方案")
        return proposal

    def _get_poetry_job(self, arguments, context) -> dict:
        job_id = str(arguments.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        snapshot = self._jobs.get_job(job_id)
        if not isinstance(snapshot, dict):
            return snapshot
        # 将异步任务的真实成稿整理成模型容易读取的稳定字段，避免模型只看到状态和 job_id。
        candidates = list(snapshot.get("candidates") or [])
        result = snapshot.get("result") if isinstance(snapshot.get("result"), dict) else {}
        if not candidates:
            candidates = list(result.get("candidates") or [])
        generated = []
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, Mapping):
                continue
            content = str(candidate.get("content") or candidate.get("text") or "").strip()
            if content:
                generated.append({
                    "ordinal": candidate.get("ordinal", index),
                    "title": str(candidate.get("title") or "").strip(),
                    "content": content,
                })
        if not generated:
            fallback_content = result.get("full_text") or result.get("content") or result.get("text")
            if fallback_content:
                generated.append({"ordinal": 1, "title": "", "content": str(fallback_content).strip()})
        snapshot["generated_poems"] = generated
        if snapshot.get("status") == "succeeded":
            snapshot["agent_instruction"] = (
                "任务已完成。以上 generated_poems 是本次真实生成正文；回答时只能引用这些正文并进行散文分析，禁止自行补写诗句。"
            )
        return snapshot

    def _book_name(self, value: Any) -> str:
        name = str(value or "")
        if name not in RHYME_BOOKS:
            raise ValueError(f"不支持的韵书: {name}")
        return name

    def _lexicon(self, book: str) -> RhymeLexicon:
        if book not in self._lexicons:
            self._lexicons[book] = RhymeLexicon(self._root / "Rhyme" / f"{book}.json")
        return self._lexicons[book]

    def _validate_rhyme_selection(
        self,
        book: str,
        mode: str,
        parts: Mapping[str, str],
        meter_type: str,
        form_name: str,
    ) -> None:
        if mode not in {"auto", "fixed", "random"}:
            raise ValueError("rhyme_mode 必须是 auto、fixed 或 random")
        entries = list(self._lexicon(book).iter_rhyme_entries())
        available = {part for _, part, _ in entries}
        expected_tone = None
        valid_groups: set[str] | None = None
        if meter_type == "唐诗":
            expected_tone = "仄" if "仄韵" in form_name else "平"
            valid_groups = {"1"}
        elif meter_type == "排律":
            expected_tone = "平"
            valid_groups = {"1"}
        elif meter_type == "宋词":
            template = MeterTemplateRepository(self._root / "Songci_Meter").get(form_name)
            expected_tone = "仄" if "仄韵" in template.rhyme_type else "平"
            valid_groups = {
                str(line.rhyme_group)
                for line in template.lines
                if line.rhyme_group is not None
            }
        elif meter_type == "汉俳":
            valid_groups = {"1"}
        for group, part in parts.items():
            group = str(group)
            if str(part).lower() != "random" and part not in available:
                raise ValueError(f"{book} 中未找到韵组 {group} 指定的韵部 {part}")
            if valid_groups is not None and group not in valid_groups:
                raise ValueError(f"{form_name} 不存在韵组 {group}")
            if expected_tone and str(part).lower() != "random":
                if not any(item_part == part and tone == expected_tone for _, item_part, tone in entries):
                    raise ValueError(
                        f"{form_name} 是{expected_tone}韵，韵部 {part} 没有可用的{expected_tone}声韵脚"
                    )

    def _validate_form(
        self,
        meter_type: str,
        form_name: str,
        num_lines: int | None,
        task_options: Mapping[str, Any],
    ) -> None:
        if meter_type == "唐诗":
            _reject_unknown_options(task_options, {"allow_aojiu"}, meter_type)
            normalized = form_name.replace("仄韵", "").strip()
            if normalized not in {"五言绝句", "七言绝句", "五言律诗", "七言律诗"}:
                raise ValueError(f"不支持的唐诗篇式: {form_name}")
            return
        if meter_type == "宋词":
            _reject_unknown_options(task_options, set(), meter_type)
            MeterTemplateRepository(self._root / "Songci_Meter").get(form_name)
            return
        if meter_type == "汉俳":
            _reject_unknown_options(
                task_options,
                {
                    "line_pattern",
                    "season_word",
                    "season_words",
                    "season",
                    "forbid_isolated_level",
                    "allow_aojiu",
                    "forbid_three_same_ending",
                    "rhyme_scheme",
                },
                meter_type,
            )
            if form_name != "汉俳":
                raise ValueError("汉俳的 form_name 必须是“汉俳”")
            line_pattern = (
                str(task_options.get("line_pattern", "5-7-5"))
                .strip()
                .replace("－", "-")
                .replace("—", "-")
                .replace("×", "-")
                .replace(" ", "")
            )
            if line_pattern not in {"5-7-5", "575", "五七五", "3-5-3", "353", "三五三"}:
                raise ValueError(f"汉俳格式仅支持 5-7-5 或 3-5-3，收到: {line_pattern}")
            return
        if meter_type == "排律":
            _reject_unknown_options(task_options, {"allow_aojiu"}, meter_type)
            if form_name not in {"五言排律", "七言排律"}:
                raise ValueError(f"不支持的排律篇式: {form_name}")
            if num_lines is None or num_lines < 10 or num_lines % 2 != 0:
                raise ValueError("排律句数必须是不少于十句的偶数")
            return
        raise ValueError(f"不支持的生成类型: {meter_type}")


def _object_schema(
    properties: Mapping[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required or [],
        "additionalProperties": False,
    }


def _generation_schema() -> dict[str, Any]:
    return _object_schema(
        {
            "meter_type": {"type": "string", "enum": ["唐诗", "宋词", "汉俳", "排律"]},
            "form_name": {"type": "string"},
            "theme": {"type": "string", "description": "简洁主题"},
            "rhyme_dict_name": {"type": "string", "enum": list(RHYME_BOOKS)},
            "rhyme_mode": {"type": "string", "enum": ["auto", "fixed", "random"], "description": "韵部策略：auto 自动锁韵，fixed 使用 rhyme_parts，random 随机选韵"},
            "rhyme_parts": {"type": "object", "additionalProperties": {"type": "string"}, "description": "按韵组编号指定韵部，如 {\"1\":\"一东\"}；值为 random 可对该组随机选韵"},
            "requirement": {
                "type": "string",
                "description": "细化后的创作提示，包含意象、情绪、章法和特殊要求",
            },
            "num_lines": {"type": "integer", "minimum": 10},
            "strict_polyphonic": {"type": "boolean"},
            "candidate_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "候选版本数量，支持 1 至 5；用户说一首时必须填 1",
            },
            "task_options": {"type": "object"},
        },
        ["meter_type", "form_name", "theme", "requirement"],
    )


def _rewrite_schema() -> dict[str, Any]:
    properties = dict(_generation_schema()["properties"])
    properties.update(
        {
            "original_text": {"type": "string"},
            "target_line_numbers": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 1,
                "maxItems": 64,
            },
        }
    )
    return _object_schema(
        properties,
        [
            "original_text",
            "target_line_numbers",
            "meter_type",
            "form_name",
            "requirement",
        ],
    )


def _generation_payload(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "meter_type": arguments.get("meter_type"),
        "form_name": arguments.get("form_name"),
        "theme": arguments.get("theme"),
        "rhyme_dict_name": arguments.get("rhyme_dict_name", "Xinyun"),
        "rhyme_mode": arguments.get("rhyme_mode", "auto"),
        "rhyme_parts": dict(arguments.get("rhyme_parts") or {}),
        "requirement": arguments.get("requirement", ""),
        "num_lines": arguments.get("num_lines"),
        "strict_polyphonic": arguments.get("strict_polyphonic", True),
        "candidate_count": arguments.get("candidate_count", 1),
        "task_options": dict(arguments.get("task_options") or {}),
    }


def _rewrite_payload(arguments: Mapping[str, Any]) -> dict[str, Any]:
    payload = _generation_payload(arguments)
    payload.pop("theme", None)
    payload.update(
        {
            "original_text": arguments.get("original_text"),
            "target_line_numbers": arguments.get("target_line_numbers") or [],
            "theme": arguments.get("theme", "局部改写"),
        }
    )
    return payload


def _is_explicit_confirmation(text: str) -> bool:
    normalized = re.sub(r"[\s，。！？、,.!?]", "", text).lower()
    if not normalized:
        return False
    if any(word in normalized for word in ("不要", "不行", "先别", "等等", "取消", "别生成", "别提交")):
        return False
    modification_words = ("改成", "改为", "修改", "调整", "换成", "加上", "去掉")
    if any(word in normalized for word in modification_words):
        return False
    exact = {
        "确认",
        "好的",
        "好",
        "可以",
        "可以了",
        "没问题",
        "就这样",
        "按这个来",
        "开始吧",
        "提交吧",
        "生成吧",
    }
    if normalized in exact:
        return True
    phrases = (
        "确认生成",
        "确认提交",
        "开始生成",
        "按此生成",
        "按这个生成",
        "就按这个",
        "按这个来",
        "可以生成",
        "生成吧",
        "提交吧",
        "开始吧",
        "没问题",
    )
    return any(phrase in normalized for phrase in phrases)


def _requests_poetry_action(text: str) -> bool:
    normalized = re.sub(r"[\s，。！？、,.!?]", "", text).lower()
    preview_only = (
        "先看方案",
        "先整理方案",
        "先给方案",
        "先讨论",
        "暂不生成",
        "暂时不生成",
        "不要生成",
        "别生成",
        "只看提示词",
        "看看提示词",
    )
    if any(phrase in normalized for phrase in preview_only):
        return False
    if _is_explicit_confirmation(text):
        return True
    if re.search(r"(?:写|生成|创作)[一二三四五1-5]首", normalized):
        return True
    action_phrases = (
        "写一首",
        "写首",
        "生成一首",
        "生成诗",
        "生成词",
        "创作一首",
        "创作诗",
        "创作词",
        "重写",
        "改写",
        "润色",
        "修改第",
        "改第",
    )
    return any(phrase in normalized for phrase in action_phrases)


def _requested_candidate_count(text: str) -> int:
    normalized = re.sub(r"\s", "", text)
    match = re.search(r"([一二三四五1-5])(?:首|个候选|个版本)", normalized)
    if not match:
        return 1
    values = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    token = match.group(1)
    return values.get(token, int(token) if token.isdigit() else 1)


def _reject_unknown_options(
    options: Mapping[str, Any], allowed: set[str], meter_type: str
) -> None:
    unknown = set(options).difference(allowed)
    if unknown:
        raise ValueError(f"{meter_type} 不支持 task_options: {sorted(unknown)}")
