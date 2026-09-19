from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from shiju.contracts import RewritePoemRequest
from shiju.generation.engine import GenerationEngine, ModelProtocolFailure
from shiju.rewriting.parser import parse_poem
from shiju.rewriting.planner import RewritePlan
from shiju.rewriting.protocol import RewriteProtocolError, parse_rewrite_protocol
from shiju.tasks import TaskContext, TaskRequest, default_task_registry

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


class EngineTokenizer(FakeTokenizer):
    def __call__(self, text, **kwargs):
        return SimpleNamespace(input_ids=torch.tensor([[1]]))


class FakeRunner:
    def __init__(self, outputs):
        self.tokenizer = EngineTokenizer({20: "[rewrite]"})
        self.outputs = list(outputs)
        self.rendered_messages = []
        self.generate_calls = 0

    def render_chat(self, messages, *, enable_thinking=None):
        self.rendered_messages.append(messages)
        assert enable_thinking is False
        return "prompt"

    def generate(self, prompt, sampling, **kwargs):
        self.generate_calls += 1
        return self.outputs.pop(0)


def _rewrite_runtime(tmp_path, tokenizer):
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    runtime = default_task_registry().create(
        TaskRequest(
            meter_type="唐诗",
            form_name="五言绝句",
            theme="测试",
            rhyme_dict_name="Xinyun",
        ),
        TaskContext(tokenizer, vocab, lexicon, tmp_path / "meters", 50.0),
    )
    return runtime, vocab


def test_parser_replaces_only_target_character_span():
    source = "  山雨山山雨，雨山雨雨山。\n山雨山山雨，雨山雨雨春。  "
    poem = parse_poem(source)

    rewritten = poem.replace_lines({3: "月雨山山夜"})

    assert rewritten == "  山雨山山雨，雨山雨雨山。\n月雨山山夜，雨山雨雨春。  "


def test_rewrite_protocol_parses_visible_plan_and_target_text():
    output = parse_rewrite_protocol(
        "[plan]以月色承接离情，再以归雁收束余韵。\n[rewrite]\n山雨山山雨，雨山雨雨春。"
    )

    assert output.revision_note == "以月色承接离情，再以归雁收束余韵。"
    assert output.rewrite_text == "山雨山山雨，雨山雨雨春。"


@pytest.mark.parametrize(
    "text",
    [
        "[rewrite]山雨山山雨。",
        "[plan]两句。多句。\n[rewrite]山雨山山雨。",
        "<think>草稿</think>[plan]调整意象。\n[rewrite]山雨山山雨。",
        "[plan]调整意象。\n[rewrite]山雨山山雨。[rewrite]",
    ],
)
def test_rewrite_protocol_rejects_invalid_shapes(text):
    with pytest.raises(RewriteProtocolError):
        parse_rewrite_protocol(text)


def test_non_contiguous_rewrite_skips_fixed_lines_inside_same_controller(tmp_path):
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    runtime = default_task_registry().create(
        TaskRequest(
            meter_type="唐诗",
            form_name="五言绝句",
            theme="测试",
            rhyme_dict_name="Xinyun",
        ),
        TaskContext(tokenizer, vocab, lexicon, tmp_path / "meters", 50.0),
    )
    original = "山雨山山雨，雨山雨雨山。山雨山山雨，山雨山山春。"
    request = RewritePoemRequest(
        original_text=original,
        target_line_numbers=(1, 3),
        meter_type="唐诗",
        form_name="五言绝句",
        candidate_count=1,
    )
    plan = RewritePlan.build(request, runtime)
    controller = plan.create_controller()

    assert controller.snapshot().line_index == 0
    controller.advance("月雨山山夜，")
    assert controller.snapshot().line_index == 2
    assert "雨山雨雨山" in controller.snapshot().all_text
    controller.advance("月雨山山夜，")
    assert controller.snapshot().is_finished

    replacements = plan.replacements_from_text("月雨山山夜，月雨山山夜。")
    result = plan.apply(replacements)
    assert result == "月雨山山夜，雨山雨雨山。月雨山山夜，山雨山山春。"


def test_generation_engine_retries_protocol_once_then_succeeds(tmp_path, monkeypatch):
    runner = FakeRunner(
        [
            "缺少协议标记",
            "[plan]改用月夜意象承接原诗余韵。\n[rewrite]\n月雨山山夜，月雨山山夜。",
        ]
    )
    runtime, vocab = _rewrite_runtime(tmp_path, runner.tokenizer)
    engine = GenerationEngine(runner)
    monkeypatch.setattr(engine, "_runtime_for", lambda request: (runtime, vocab))

    result = engine.rewrite_poem(
        RewritePoemRequest(
            original_text="山雨山山雨，雨山雨雨山。山雨山山雨，山雨山山春。",
            target_line_numbers=(1, 3),
            meter_type="唐诗",
            form_name="五言绝句",
            candidate_count=1,
        )
    )

    assert runner.generate_calls == 2
    assert len(runner.rendered_messages) == 2
    assert [message["role"] for message in runner.rendered_messages[1]] == ["system", "user"]
    assert result["revision_note"] == "改用月夜意象承接原诗余韵。"
    assert result["replacements"] == {"1": "月雨山山夜", "3": "月雨山山夜"}


def test_generation_engine_stops_after_one_protocol_retry(tmp_path, monkeypatch):
    runner = FakeRunner(["第一次失败", "第二次失败", "不应被使用"])
    runtime, vocab = _rewrite_runtime(tmp_path, runner.tokenizer)
    engine = GenerationEngine(runner)
    monkeypatch.setattr(engine, "_runtime_for", lambda request: (runtime, vocab))

    with pytest.raises(ModelProtocolFailure):
        engine.rewrite_poem(
            RewritePoemRequest(
                original_text="山雨山山雨，雨山雨雨山。山雨山山雨，山雨山山春。",
                target_line_numbers=(1, 3),
                meter_type="唐诗",
                form_name="五言绝句",
                candidate_count=1,
            )
        )

    assert runner.generate_calls == 2
    assert runner.outputs == ["不应被使用"]
