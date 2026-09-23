from __future__ import annotations

import pytest

from apps.agent.framework import ToolContext
from apps.agent.tools import AgentToolbox


class FakeJobs:
    def __init__(self):
        self.generated = []
        self.rewritten = []

    def submit_generate(self, payload, idempotency_key):
        self.generated.append((payload, idempotency_key))
        return {"job_id": "generate-1", "status": "queued", "waiting_for_worker": True}

    def submit_rewrite(self, payload, idempotency_key):
        self.rewritten.append((payload, idempotency_key))
        return {"job_id": "rewrite-1", "status": "queued", "waiting_for_worker": False}

    def get_job(self, job_id):
        return {"job_id": job_id, "status": "succeeded", "result": {"text": "春山"}}


def _toolbox():
    from pathlib import Path

    return AgentToolbox(Path(__file__).resolve().parents[1], FakeJobs())


def test_rhyme_and_meter_queries_use_local_data():
    toolbox = _toolbox()
    context = ToolContext("查询", 1)

    rhyme = toolbox.execute(
        "lookup_rhyme",
        {"text": "春山", "rhyme_book": "Xinyun"},
        context,
    )
    assert [entry["char"] for entry in rhyme["entries"]] == ["春", "山"]
    assert all(entry["found"] for entry in rhyme["entries"])

    meter = toolbox.execute("get_ci_meter", {"name": "浣溪沙"}, context)
    assert meter["name"] == "浣溪沙"
    assert meter["variant_name"] == "韩偓"
    assert len(meter["stanzas"]) == 2
    assert meter["stanzas"][0]["lines"][0]["pattern"] == "中仄/平平/仄仄平"


def test_generation_submission_waits_for_web_or_a_later_turn():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_generation",
        {
            "meter_type": "唐诗",
            "form_name": "七言绝句",
            "theme": "春山夜雨",
            "requirement": "以雨后月色写归思，前两句写景，后两句转情。",
        },
        ToolContext("写一首春山夜雨的七绝", 1),
    )
    proposal_id = proposal["proposal_id"]
    with pytest.raises(ValueError, match="同一轮"):
        toolbox.execute(
            "submit_generation",
            {"proposal_id": proposal_id},
            ToolContext("写一首春山夜雨的七绝", 1),
        )
    submitted = toolbox.execute(
        "submit_generation", {"proposal_id": proposal_id}, ToolContext("确认生成", 2)
    )
    assert submitted["job_id"] == "generate-1"
    payload, idempotency_key = toolbox._jobs.generated[0]
    assert payload["form_name"] == "七言绝句"
    assert payload["candidate_count"] == 1
    assert idempotency_key == proposal_id


def test_preview_only_proposal_waits_for_a_later_confirmation():
    toolbox = _toolbox()
    context = ToolContext("先看方案，暂不生成", 1)
    proposal = toolbox.execute(
        "prepare_generation",
        {
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "theme": "春山",
            "requirement": "写春山新雨。",
        },
        context,
    )

    assert proposal["editable_prompt"] == "写春山新雨。"
    assert proposal["candidate_count"] == 1
    assert toolbox.submit_pending_if_confirmed(context) is None
    with pytest.raises(ValueError, match="同一轮"):
        toolbox.execute(
            "submit_generation",
            {"proposal_id": proposal["proposal_id"]},
            context,
        )

    submitted = toolbox.execute(
        "submit_generation",
        {"proposal_id": proposal["proposal_id"]},
        ToolContext("确认生成", 2),
    )
    assert submitted["job_id"] == "generate-1"


def test_rewrite_preparation_validates_target_line_and_preserves_request():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_rewrite",
        {
            "original_text": "春风入小楼，明月照归舟。\n山色连天远，江声带雨流。",
            "target_line_numbers": [2],
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "requirement": "第二句改得更含蓄，保持月夜归舟意象。",
        },
        ToolContext("重写第二句", 1),
    )
    with pytest.raises(ValueError, match="同一轮"):
        toolbox.execute(
            "submit_rewrite",
            {"proposal_id": proposal["proposal_id"]},
            ToolContext("重写第二句", 1),
        )
    result = toolbox.execute(
        "submit_rewrite", {"proposal_id": proposal["proposal_id"]}, ToolContext("确认", 2)
    )
    assert result["job_id"] == "rewrite-1"
    payload, _ = toolbox._jobs.rewritten[0]
    assert payload["target_line_numbers"] == (2,)
    assert payload["original_text"].startswith("春风入小楼")
    assert payload["candidate_count"] == 1


def test_generation_supports_up_to_five_candidates():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_generation",
        {
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "theme": "秋江",
            "requirement": "写秋江晚景。",
        },
        ToolContext("生成五首秋江五绝", 1),
    )

    assert proposal["candidate_count"] == 5
    assert proposal["proposal"]["candidate_count"] == 5


def test_generation_carries_explicit_rhyme_selection():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_generation",
        {
            "meter_type": "唐诗",
            "form_name": "七言绝句",
            "theme": "秋江",
            "rhyme_dict_name": "Pinshui",
            "rhyme_mode": "fixed",
            "rhyme_parts": {"1": "一东"},
            "requirement": "写秋江晚景。",
        },
        ToolContext("写一首平水韵一东七绝", 1),
    )

    assert proposal["proposal"]["rhyme_mode"] == "fixed"
    assert proposal["proposal"]["rhyme_parts"] == {"1": "一东"}


def test_generation_rejects_unknown_rhyme_part():
    toolbox = _toolbox()
    with pytest.raises(ValueError, match="未找到韵组"):
        toolbox.execute(
            "prepare_generation",
            {
                "meter_type": "唐诗",
                "form_name": "七言绝句",
                "theme": "秋江",
                "rhyme_dict_name": "Pinshui",
                "rhyme_mode": "fixed",
                "rhyme_parts": {"1": "不存在"},
                "requirement": "写秋江晚景。",
            },
            ToolContext("写一首诗", 1),
        )


def test_generation_rejects_rhyme_part_with_wrong_tone():
    from shiju.data import RhymeLexicon

    lexicon = RhymeLexicon("Rhyme/Pinshui.json")
    oblique_only = next(
        part
        for part in {item_part for _, item_part, _ in lexicon.iter_rhyme_entries()}
        if {
            tone for _, item_part, tone in lexicon.iter_rhyme_entries() if item_part == part
        }
        == {"仄"}
    )
    toolbox = _toolbox()
    with pytest.raises(ValueError, match="平韵"):
        toolbox.execute(
            "prepare_generation",
            {
                "meter_type": "唐诗",
                "form_name": "七言绝句",
                "theme": "秋江",
                "rhyme_dict_name": "Pinshui",
                "rhyme_mode": "fixed",
                "rhyme_parts": {"1": oblique_only},
                "requirement": "写秋江晚景。",
            },
            ToolContext("写一首诗", 1),
        )


def test_rewrite_accepts_six_target_lines_in_lushi():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_rewrite",
        {
            "original_text": (
                "春风春月花，夜雨夜山春。"
                "春风春月花，夜雨夜山春。"
                "春风春月花，夜雨夜山春。"
                "春风春月花，夜雨夜山春。"
            ),
            "target_line_numbers": [1, 2, 3, 4, 7, 8],
            "meter_type": "唐诗",
            "form_name": "五言律诗",
            "requirement": "保留第五、六句，重写其余六句。",
        },
        ToolContext("保留第五、六句，重写其余六句", 1),
    )

    assert proposal["proposal"]["target_line_numbers"] == (1, 2, 3, 4, 7, 8)


def test_prepare_rejects_unsupported_form():
    toolbox = _toolbox()
    with pytest.raises(ValueError, match="不支持的唐诗篇式"):
        toolbox.execute(
            "prepare_generation",
            {
                "meter_type": "唐诗",
                "form_name": "九言绝句",
                "theme": "春",
                "requirement": "写春景。",
            },
            ToolContext("写诗", 1),
        )


def test_confirmation_accepts_natural_phrase_but_not_modification():
    toolbox = _toolbox()
    proposal = toolbox.execute(
        "prepare_generation",
        {
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "theme": "秋江",
            "requirement": "写秋江晚景。",
        },
        ToolContext("写诗", 1),
    )

    with pytest.raises(ValueError, match="没有要求执行"):
        toolbox.execute(
            "submit_generation",
            {"proposal_id": proposal["proposal_id"]},
            ToolContext("没问题，但是改成七言绝句", 2),
        )
    result = toolbox.execute(
        "submit_generation",
        {"proposal_id": proposal["proposal_id"]},
        ToolContext("好的，生成吧", 3),
    )
    assert result["job_id"] == "generate-1"
