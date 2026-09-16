from shiju.domain import GenerationLayout, LineLayout, StepKind
from shiju.state import GenerationController, GenerationStateMachine


class EmptySession:
    def allowed_patterns(self, state, max_length):
        return ()

    def observe_text(self, state, text):
        return None

    def candidate_context(self, state):
        return None


def test_generic_state_supports_variable_line_lengths():
    layout = GenerationLayout(
        (
            LineLayout(length=3, break_positions=frozenset({1})),
            LineLayout(length=5, break_positions=frozenset({2}), stanza_end=True),
        )
    )
    controller = GenerationController(GenerationStateMachine(layout), EmptySession())

    controller.advance("山雨山")
    assert controller.snapshot().step is StepKind.PUNCTUATION
    controller.advance("，")
    assert controller.snapshot().line_index == 1
    controller.advance("山雨山雨山")
    assert controller.snapshot().step is StepKind.NEWLINE
    controller.advance("\n")
    assert controller.snapshot().is_finished


def test_caesura_is_a_separator_not_a_lexical_character():
    layout = GenerationLayout(
        (LineLayout(length=4, caesura_positions=frozenset({2}), stanza_end=True),)
    )
    controller = GenerationController(GenerationStateMachine(layout), EmptySession())

    controller.advance("山雨")
    assert controller.snapshot().step is StepKind.CAESURA
    assert controller.snapshot().char_index == 2
    controller.advance("、春风")
    assert controller.snapshot().current_line_text == "山雨春风"
    assert controller.snapshot().step is StepKind.NEWLINE
