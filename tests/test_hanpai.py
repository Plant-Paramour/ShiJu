import pytest

from shiju.constraints import HanpaiConstraintProfile
from shiju.domain import RhymeMode, StepKind
from shiju.policies import BoundaryCoherencePolicy, CandidateContext, HanpaiVerifierPolicy
from shiju.processor import NewlineSeparatorPolicy
from shiju.prompts import build_hanpai_prompt
from shiju.state import GenerationController, GenerationStateMachine

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


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
    assert {item.length for item in controller.allowed_patterns()} == {1, 2, 3}
    controller.advance("山雨山\n")
    assert {item.length for item in controller.allowed_patterns()} == {1, 2}
    controller.advance("山雨")
    assert {item.length for item in controller.allowed_patterns()} == {1, 2}
    controller.advance("山雨")
    assert {item.length for item in controller.allowed_patterns()} == {1, 2, 3}


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

    policy = BoundaryCoherencePolicy(vocab.common_bigrams())

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

    controller.advance("雨雨山\n")
    assert session.locked_rhyme_parts == {"平": frozenset({"一"})}
    controller.advance("山雨山雨雨\n雨雨")
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


def test_hanpai_aojiu_can_rescue_an_isolated_level_tone():
    from shiju.constraints import HanpaiConstraintContext

    tokenizer = FakeTokenizer({20: "山雨山雨"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    state = GenerationStateMachine(
        HanpaiConstraintProfile((3, 5, 3), lexicon).layout
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


def test_hanpai_season_input_modes_are_mutually_exclusive():
    from shiju.tasks import HanpaiOptions

    with pytest.raises(ValueError, match="只能配置其中一种"):
        HanpaiOptions(season_word="寒蝉", season="初秋")
