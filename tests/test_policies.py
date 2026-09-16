from shiju.constraints import RelationalConstraintContext
from shiju.domain import GenerationState, LineLayout, StepKind
from shiju.policies import (
    BoundaryCoherencePolicy,
    CandidateContext,
    RepetitionPenaltyPolicy,
    TangVerifierPolicy,
)

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


def _context(current_line="山", all_text="山", char_index=1):
    tokenizer = FakeTokenizer({20: "山雨"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    state = GenerationState(
        line_index=0,
        char_index=char_index,
        current_line_text=current_line,
        all_text=all_text,
        step=StepKind.TEXT,
        line=LineLayout(length=5, break_positions=frozenset({1, 2})),
    )
    relational = RelationalConstraintContext(
        current_line=0,
        current_char_idx=char_index,
        target_length=5,
        is_rhyming=False,
        locked_rhyme_parts=None,
        excluded_rhyme_parts=None,
        rhyme_type="平韵",
        base_tone=2,
        global_base_tone=2,
        line0_rhymes=False,
    )
    return CandidateContext(state, relational, tokenizer, vocab)


def test_repetition_penalty_matches_exponential_policy():
    context = _context()
    penalty = RepetitionPenaltyPolicy().evaluate(2, context)
    assert penalty is not None and penalty >= 8.0


def test_common_boundary_policy_penalizes_known_bigram():
    tokenizer = FakeTokenizer({20: "山雨"})
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    context = _context()
    policy = BoundaryCoherencePolicy(frozenset({"山雨"}), penalty=50.0)
    assert policy.evaluate(3, context) == 50.0


def test_tang_full_verifier_rejects_forbidden_character_but_critical_allows_it():
    context = _context(current_line="", all_text="", char_index=0)
    lexicon = FakeLexicon()

    assert TangVerifierPolicy(lexicon, "full").evaluate(12, context) is None
    assert TangVerifierPolicy(lexicon, "critical").evaluate(12, context) == 0.0
