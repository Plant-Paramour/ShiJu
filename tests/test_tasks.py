from pathlib import Path

from shiju.tasks import TaskContext, TaskRequest, default_task_registry

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


def test_tang_task_does_not_read_meter_source(tmp_path):
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    missing_source = tmp_path / "missing-songci-meter"
    context = TaskContext(tokenizer, vocab, lexicon, missing_source)
    request = TaskRequest(
        meter_type="唐诗",
        form_name="七律",
        theme="秋夜",
        rhyme_dict_name="Pinshui",
        use_thinking=False,
    )

    runtime = default_task_registry().create(request, context)

    assert len(runtime.profile.layout.lines) == 8
    assert not missing_source.exists()


def test_template_task_reuses_resolved_default_variant_in_prompt():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    meter_source = Path(__file__).resolve().parents[1] / "Songci_Meter"
    context = TaskContext(tokenizer, vocab, lexicon, meter_source)
    request = TaskRequest(
        meter_type="宋词",
        form_name="浣溪沙",
        theme="春日",
        rhyme_dict_name="Xinyun",
        use_thinking=False,
    )

    runtime = default_task_registry().create(request, context)
    prompt = "\n".join(message["content"] for message in runtime.messages)
    output_template = "[title]浣溪沙·作品名\n[content]正文"

    assert runtime.profile.template.variant_name == "韩偓"
    assert "采用变体：韩偓" in prompt
    assert output_template in runtime.messages[0]["content"]
    assert output_template in runtime.messages[-1]["content"]
    assert "[title]浣溪沙·春思\n[content]柳色含烟" in prompt
    assert "两个标记均不可省略、修改或替换" in prompt
