import torch

from shiju.constraints import RelationalConstraintProfile
from shiju.policies import PolicyTier, TangVerifierPolicy
from shiju.processor import (
    ConstrainedLogitsProcessor,
    ProcessorConfig,
    RelationalSeparatorPolicy,
)
from shiju.state import GenerationController, GenerationStateMachine

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


class SingleTokenVocab(FakeVocab):
    def __init__(self, tokenizer, lexicon, token_id):
        super().__init__(tokenizer, lexicon)
        self.token_id = token_id

    def resolve_patterns(self, patterns, ignore_rhyme=False):
        return {self.token_id}


class RejectAll:
    def evaluate(self, token_id, context):
        return None


def _processor():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = FakeVocab(tokenizer, lexicon)
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    processor = ConstrainedLogitsProcessor(
        vocab=vocab,
        controller=controller,
        tokenizer=tokenizer,
        input_prompt_len=0,
        separator_policy=RelationalSeparatorPolicy(tokenizer),
        policy_tiers=(PolicyTier("base", ()),),
        config=ProcessorConfig(),
    )
    return processor, tokenizer, controller


def test_processor_is_inactive_before_content_marker():
    processor, tokenizer, _ = _processor()
    scores = torch.arange(20, dtype=torch.float32).unsqueeze(0)
    result = processor(torch.tensor([[2]]), scores.clone())
    expected = scores.clone()
    expected[:, 8] = -float("inf")
    assert torch.equal(result, expected)


def test_processor_tracks_content_and_masks_to_allowed_tokens():
    processor, tokenizer, controller = _processor()
    scores = torch.arange(20, dtype=torch.float32).unsqueeze(0)

    result = processor(torch.tensor([[1]]), scores.clone())
    finite = set(torch.where(torch.isfinite(result[0]))[0].tolist())
    assert {2, 3, 9, 10, 11, 12, 13}.issuperset(finite)
    assert 4 not in finite
    processor(torch.tensor([[1, 2]]), scores.clone())
    assert controller.snapshot().all_text == "山"


def test_processor_forces_separator_after_full_line():
    processor, tokenizer, controller = _processor()
    scores = torch.arange(20, dtype=torch.float32).unsqueeze(0)
    processor(torch.tensor([[1, 2, 3, 2, 3, 2]]), scores.clone())
    result = processor(torch.tensor([[1, 2, 3, 2, 3, 2]]), scores.clone())
    finite = set(torch.where(torch.isfinite(result[0]))[0].tolist())
    assert finite == {4, 16}


def test_processor_falls_back_from_full_tang_rules_to_critical_rules():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = SingleTokenVocab(tokenizer, lexicon, 12)  # “的”：完整规则拒绝，核心规则放行
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    processor = ConstrainedLogitsProcessor(
        vocab=vocab,
        controller=controller,
        tokenizer=tokenizer,
        input_prompt_len=0,
        separator_policy=RelationalSeparatorPolicy(tokenizer),
        policy_tiers=(
            PolicyTier("full", (TangVerifierPolicy(lexicon, "full"),)),
            PolicyTier("critical", (TangVerifierPolicy(lexicon, "critical"),)),
        ),
        config=ProcessorConfig(raw_after_policy_failure=True),
    )
    scores = torch.arange(20, dtype=torch.float32).unsqueeze(0)

    result = processor(torch.tensor([[1]]), scores.clone())
    finite = set(torch.where(torch.isfinite(result[0]))[0].tolist())

    assert finite == {12}


def test_processor_final_fallback_releases_original_scores():
    tokenizer = FakeTokenizer()
    lexicon = FakeLexicon()
    vocab = SingleTokenVocab(tokenizer, lexicon, 2)
    profile = RelationalConstraintProfile(5, 4, "平韵", lexicon)
    controller = GenerationController(
        GenerationStateMachine(profile.layout),
        profile.create_session(),
    )
    processor = ConstrainedLogitsProcessor(
        vocab=vocab,
        controller=controller,
        tokenizer=tokenizer,
        input_prompt_len=0,
        separator_policy=RelationalSeparatorPolicy(tokenizer),
        policy_tiers=(PolicyTier("reject", (RejectAll(),)),),
        config=ProcessorConfig(raw_after_policy_failure=True),
    )
    scores = torch.arange(20, dtype=torch.float32).unsqueeze(0)

    result = processor(torch.tensor([[1]]), scores.clone())

    assert torch.equal(result[:, :8], scores[:, :8])
    assert torch.isneginf(result[0, 8])  # 全局分号禁用仍然保留
    assert torch.equal(result[:, 9:], scores[:, 9:])
