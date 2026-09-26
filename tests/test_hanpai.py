import pytest
import torch

from shiju.constraints import HanpaiConstraintProfile
from shiju.domain import GenerationLayout, LineLayout, RhymeMode, StepKind
from shiju.policies import (
    BoundaryCoherencePolicy,
    CandidateContext,
    HanpaiVerifierPolicy,
    PolicyTier,
)
from shiju.processor import ConstrainedLogitsProcessor, NewlineSeparatorPolicy, ProcessorConfig
from shiju.prompts import build_hanpai_prompt
from shiju.state import GenerationController, GenerationStateMachine

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


def _advance_hanpai_text(controller, text):
    for char in text:
        if controller.snapshot().step is StepKind.CAESURA:
            controller.advance("、")
        controller.advance(char)
    if controller.snapshot().step is StepKind.CAESURA:
        controller.advance("、")


@pytest.mark.parametrize(
    ("line_lengths", "expected_breaks"),
    [
        ((5, 7, 5), ({2}, {2, 4}, {2})),
        ((3, 5, 3), (set(), {2}, set())),
    ],
)
def test_hanpai_profile_supports_both_line_patterns(line_lengths, expected_breaks):
    profile = HanpaiConstraintProfile(line_lengths, FakeLexicon())

    assert [line.length for line in profile.layout.lines] == list(line_lengths)
    assert [set(line.break_positions) for line in profile.layout.lines] == list(
        expected_breaks
    )
    assert [set(line.caesura_positions) for line in profile.layout.lines] == [
        set(),
        set(),
        set(),
    ]
    assert all(line.stanza_end for line in profile.layout.lines)


def test_hanpai_candidate_patterns_cannot_cross_five_and_seven_char_breaks():
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )

    assert {item.length for item in controller.allowed_patterns()} == {1, 2}
    controller.advance("山雨")
    assert controller.snapshot().step is StepKind.TEXT
    assert {item.length for item in controller.allowed_patterns()} == {1, 2, 3}
    controller.advance("山雨山\n")
    assert {item.length for item in controller.allowed_patterns()} == {1, 2}
    controller.advance("山雨")
    assert controller.snapshot().step is StepKind.TEXT
    assert {item.length for item in controller.allowed_patterns()} == {1, 2}
    controller.advance("山雨")
    assert controller.snapshot().step is StepKind.TEXT
    assert {item.length for item in controller.allowed_patterns()} == {1, 2, 3}


@pytest.mark.parametrize(
    ("position", "expected_lengths"),
    [
        (0, {1, 2}),
        (1, {1}),
        (2, {1, 2, 3}),
        (3, {1, 2}),
        (4, {1}),
    ],
)
def test_hanpai_five_char_line_limits_tokens_to_next_break(
    position,
    expected_lengths,
):
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    _advance_hanpai_text(controller, "山" * position)

    assert controller.remaining_before_boundary() == max(expected_lengths)
    assert {item.length for item in controller.allowed_patterns()} == expected_lengths


@pytest.mark.parametrize(
    ("position", "expected_lengths"),
    [
        (0, {1, 2}),
        (1, {1}),
        (2, {1, 2}),
        (3, {1}),
        (4, {1, 2, 3}),
        (5, {1, 2}),
        (6, {1}),
    ],
)
def test_hanpai_seven_char_line_limits_tokens_to_next_break(
    position,
    expected_lengths,
):
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    _advance_hanpai_text(controller, "山雨山雨山\n" + "山" * position)

    assert controller.remaining_before_boundary() == max(expected_lengths)
    assert {item.length for item in controller.allowed_patterns()} == expected_lengths


def test_hanpai_processor_rejects_token_longer_than_current_segment():
    class BoundaryLeakingVocab(FakeVocab):
        def resolve_patterns(
            self,
            patterns,
            ignore_rhyme=False,
            strict_polyphonic=True,
        ):
            return {2, 20}

    tokenizer = FakeTokenizer({20: "山雨"})
    lexicon = FakeLexicon()
    vocab = BoundaryLeakingVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    processor = ConstrainedLogitsProcessor(
        vocab=vocab,
        controller=controller,
        tokenizer=tokenizer,
        input_prompt_len=0,
        separator_policy=NewlineSeparatorPolicy(tokenizer),
        policy_tiers=(PolicyTier("base", ()),),
        config=ProcessorConfig(),
    )
    scores = torch.arange(21, dtype=torch.float32).unsqueeze(0)

    result = processor(torch.tensor([[1, 2]]), scores)
    finite = set(torch.where(torch.isfinite(result[0]))[0].tolist())

    assert controller.snapshot().char_index == 1
    assert controller.remaining_before_boundary() == 1
    assert finite == {2}


def test_hanpai_verifier_rejects_token_crossing_break_as_second_guard():
    tokenizer = FakeTokenizer({20: "山雨"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山")
    context = CandidateContext(
        state=controller.snapshot(),
        constraint=controller.candidate_context(),
        tokenizer=tokenizer,
        vocab=vocab,
    )

    assert HanpaiVerifierPolicy(lexicon).evaluate(20, context) is None


def test_hanpai_uses_the_shared_boundary_coherence_penalty():
    tokenizer = FakeTokenizer({20: "春山"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("雨春")
    context = CandidateContext(
        state=controller.snapshot(),
        constraint=controller.candidate_context(),
        tokenizer=tokenizer,
        vocab=vocab,
    )

    policy = BoundaryCoherencePolicy(vocab.common_bigrams(), penalty=50.0)

    assert policy.evaluate(2, context) == 50.0


@pytest.mark.parametrize(
    ("scheme", "rhyme_lines"),
    [
        (None, frozenset()),
        ("AAA", frozenset({0, 1, 2})),
        ("ABA", frozenset({0, 2})),
        ("BAA", frozenset({1, 2})),
    ],
)
def test_hanpai_rhyme_schemes_select_expected_lines(scheme, rhyme_lines):
    profile = HanpaiConstraintProfile((3, 5, 3), FakeLexicon(), scheme)

    assert profile.rhyme_lines == rhyme_lines


def test_hanpai_aba_locks_first_and_third_line_rhyme():
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((3, 5, 3), lexicon, "ABA")
    session = profile.create_session()
    controller = GenerationController(GenerationStateMachine(profile.layout), session)

    _advance_hanpai_text(controller, "雨雨山\n")
    assert session.locked_rhyme_parts == {"平": frozenset({"一"})}
    _advance_hanpai_text(controller, "山雨山雨雨\n雨雨")
    final_patterns = controller.allowed_patterns(max_length=1)

    assert controller.snapshot().line_index == 2
    assert controller.snapshot().step is StepKind.TEXT
    assert {item.tones for item in final_patterns} == {"平"}
    assert all(item.rhyme.mode is RhymeMode.PARTS for item in final_patterns)
    assert all(item.rhyme.parts == frozenset({"一"}) for item in final_patterns)


def test_hanpai_forces_a_newline_after_each_line():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((3, 5, 3), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山雨山")

    state = controller.snapshot()
    separator = NewlineSeparatorPolicy(tokenizer)

    assert state.step is StepKind.NEWLINE
    assert separator.allowed_tokens(state, controller.candidate_context()) == {6}


def test_hanpai_does_not_generate_internal_caesuras():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山雨")

    state = controller.snapshot()
    separator = NewlineSeparatorPolicy(tokenizer)

    assert state.step is StepKind.TEXT
    assert separator.allowed_tokens(state, controller.candidate_context()) == set()
    assert controller.remaining_before_boundary() == 3


def test_hanpai_rejects_unknown_format_and_rhyme_scheme():
    from shiju.tasks import parse_hanpai_format

    with pytest.raises(ValueError, match="仅支持 5-7-5 或 3-5-3"):
        parse_hanpai_format("4-6-4")
    with pytest.raises(ValueError, match="押韵格式仅支持"):
        HanpaiConstraintProfile((5, 7, 5), FakeLexicon(), "AAB")


def _policy_context(text, info):
    tokenizer = FakeTokenizer({20: text})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    state = GenerationStateMachine(
        HanpaiConstraintProfile((3, 5, 3), lexicon).layout
    ).snapshot()
    return HanpaiVerifierPolicy(lexicon), CandidateContext(
        state=state,
        constraint=info,
        tokenizer=tokenizer,
        vocab=vocab,
    )


def test_hanpai_optional_tone_rules_can_all_be_disabled():
    from shiju.constraints import HanpaiConstraintContext

    info = HanpaiConstraintContext(3, False, False, False)
    policy, context = _policy_context("山春风", info)

    assert policy.evaluate(20, context) == 0.0


def test_hanpai_rejects_three_same_tones_at_line_end_when_enabled():
    from shiju.constraints import HanpaiConstraintContext

    info = HanpaiConstraintContext(3, False, False, True)
    policy, context = _policy_context("山春风", info)

    assert policy.evaluate(20, context) is None


@pytest.mark.parametrize(
    ("candidate", "end_tones", "expected"),
    [
        ("夜", ("仄",), None),
        ("山", ("仄",), 0.0),
        ("夜", ("平", "仄"), 0.0),
    ],
)
def test_hanpai_prevents_forced_three_same_before_final_character(
    candidate,
    end_tones,
    expected,
):
    from shiju.constraints import HanpaiConstraintContext

    tokenizer = FakeTokenizer({20: candidate})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山雨、月")
    context = CandidateContext(
        controller.snapshot(),
        HanpaiConstraintContext(5, False, False, True, end_tones),
        tokenizer,
        vocab,
    )

    assert HanpaiVerifierPolicy(lexicon).evaluate(20, context) == expected


def test_hanpai_prevention_rejects_polyphonic_three_same_interpretation():
    from shiju.constraints import HanpaiConstraintContext

    class PolyphonicLexicon(FakeLexicon):
        def __init__(self):
            super().__init__()
            self.tones["重"] = ["平", "仄"]
            self.parts["重"] = ["一"]

    tokenizer = FakeTokenizer({20: "夜"})
    lexicon = PolyphonicLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山雨、重")
    context = CandidateContext(
        controller.snapshot(),
        HanpaiConstraintContext(5, False, False, True, ("仄",)),
        tokenizer,
        vocab,
    )

    assert HanpaiVerifierPolicy(lexicon).evaluate(20, context) is None


def test_hanpai_prevention_handles_a_two_character_penultimate_token():
    from shiju.constraints import HanpaiConstraintContext

    tokenizer = FakeTokenizer({20: "月夜"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile((5, 7, 5), lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    controller.advance("山雨、")
    context = CandidateContext(
        controller.snapshot(),
        HanpaiConstraintContext(5, False, False, True, ("仄",)),
        tokenizer,
        vocab,
    )

    assert HanpaiVerifierPolicy(lexicon).evaluate(20, context) is None


def test_hanpai_aba_prevents_a_forced_three_same_tail_before_last_character():
    tokenizer = FakeTokenizer({20: "月", 21: "夜"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = HanpaiConstraintProfile(
        (5, 7, 5),
        lexicon,
        rhyme_scheme="ABA",
        forbid_three_same_ending=True,
    )
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    processor = ConstrainedLogitsProcessor(
        vocab=vocab,
        controller=controller,
        tokenizer=tokenizer,
        input_prompt_len=0,
        separator_policy=NewlineSeparatorPolicy(tokenizer),
        policy_tiers=(PolicyTier("hanpai", (HanpaiVerifierPolicy(lexicon),)),),
        config=ProcessorConfig(),
    )
    prefix = "[content]山雨、山雨夜\n山雨、山雨、山雨山\n山雨、月"
    input_ids = torch.tensor([tokenizer.encode(prefix)])
    scores = torch.arange(22, dtype=torch.float32).unsqueeze(0)

    penultimate_result = processor(input_ids, scores.clone())
    penultimate_finite = set(
        torch.where(torch.isfinite(penultimate_result[0]))[0].tolist()
    )

    assert controller.candidate_context().allowed_end_tones == ("仄",)
    assert 21 not in penultimate_finite  # “月夜”会迫使仄韵末字形成三仄尾
    assert 2 in penultimate_finite  # “月山”仍可用仄声字正常收尾
    assert tokenizer.eos_token_id not in penultimate_finite

    final_input_ids = torch.tensor([tokenizer.encode(prefix + "山")])
    final_result = processor(final_input_ids, scores.clone())
    final_finite = set(torch.where(torch.isfinite(final_result[0]))[0].tolist())

    assert 21 in final_finite
    assert tokenizer.eos_token_id not in final_finite


def test_hanpai_rejects_if_any_polyphonic_interpretation_is_three_same():
    from shiju.constraints import HanpaiConstraintContext

    class PolyphonicLexicon(FakeLexicon):
        def __init__(self):
            super().__init__()
            self.tones["重"] = ["平", "仄"]
            self.parts["重"] = ["一"]

    lexicon = PolyphonicLexicon()
    tokenizer = FakeTokenizer({20: "重重重"})
    vocab = FakeVocab(tokenizer, lexicon)
    state = GenerationStateMachine(
        HanpaiConstraintProfile((3, 5, 3), lexicon).layout
    ).snapshot()
    context = CandidateContext(
        state,
        HanpaiConstraintContext(3, False, False, True),
        tokenizer,
        vocab,
    )

    assert HanpaiVerifierPolicy(lexicon).evaluate(20, context) is None
    assert (
        HanpaiVerifierPolicy(lexicon, strict_polyphonic=False).evaluate(20, context)
        == 0.0
    )


def test_hanpai_aojiu_can_rescue_an_isolated_level_tone():
    from shiju.constraints import HanpaiConstraintContext

    tokenizer = FakeTokenizer({20: "山雨山雨"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    state = GenerationStateMachine(
        GenerationLayout((LineLayout(length=4),))
    ).snapshot()

    strict = CandidateContext(
        state,
        HanpaiConstraintContext(4, True, False, False),
        tokenizer,
        vocab,
    )
    rescued = CandidateContext(
        state,
        HanpaiConstraintContext(4, True, True, False),
        tokenizer,
        vocab,
    )
    policy = HanpaiVerifierPolicy(lexicon)

    assert policy.evaluate(20, strict) is None
    assert policy.evaluate(20, rescued) == 0.0


@pytest.mark.parametrize(
    ("season_options", "expected"),
    [
        ({"season_word": "寒蝉"}, "指定季语“寒蝉”"),
        (
            {"season_words": ("寒蝉", "雁影")},
            "必须且只能从候选季语 “寒蝉”、“雁影” 中选择一个",
        ),
        ({"season": "初秋"}, "指定季节为“初秋”"),
        ({}, "仍必须自行选择并使用一个明显、具体的季语"),
    ],
)
def test_hanpai_prompt_supports_all_season_input_modes(season_options, expected):
    messages = build_hanpai_prompt(
        task_type="instruction",
        form_name="汉俳",
        theme="城市夜景",
        line_lengths=(5, 7, 5),
        use_thinking=False,
        **season_options,
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert expected in prompt
    assert "未加时令限定的云、月、风、雨、柳等一般景物不视为明显季语" in prompt


def test_hanpai_prompt_can_disable_model_thinking():
    messages = build_hanpai_prompt(
        task_type="instruction",
        form_name="汉俳",
        theme="秋夜",
        line_lengths=(5, 7, 5),
        use_thinking=False,
    )

    assert messages[0]["content"].startswith("你是一位")
    assert messages[1]["content"].startswith("/no_think ")


def test_hanpai_prompt_requires_a_short_creation_plan_before_output():
    messages = build_hanpai_prompt(
        task_type="instruction",
        form_name="汉俳",
        theme="秋夜",
        line_lengths=(5, 7, 5),
    )
    system_prompt = messages[0]["content"]

    assert "先输出一小段简短的创作规划" in system_prompt
    assert "控制在 2 至 4 句" in system_prompt
    assert "必须作为可见答案输出并以 [plan] 开头" in system_prompt
    assert "[plan]简短创作方向与安排" in system_prompt
    assert "不要展开逐步思维链" in system_prompt
    assert "不要提前写出完整诗句、分句或格律符号" in system_prompt


def test_hanpai_season_input_modes_are_mutually_exclusive():
    from shiju.tasks import HanpaiOptions

    with pytest.raises(ValueError, match="只能配置其中一种"):
        HanpaiOptions(season_word="寒蝉", season="初秋")
