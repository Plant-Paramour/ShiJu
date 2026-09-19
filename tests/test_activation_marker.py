import torch

from shiju.constraints import RelationalConstraintProfile
from shiju.policies import PolicyTier
from shiju.processor import ConstrainedLogitsProcessor, ProcessorConfig, RelationalSeparatorPolicy
from shiju.state import GenerationController, GenerationStateMachine

from conftest import FakeLexicon, FakeTokenizer, FakeVocab


def _rewrite_processor():
    tokenizer = FakeTokenizer({20: "[plan]调整意象。", 21: "[re", 22: "write]"})
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
        activation_marker="[rewrite]",
    )
    return processor, controller


def test_plan_does_not_advance_state_and_split_marker_starts_constraints():
    processor, controller = _rewrite_processor()
    scores = torch.arange(23, dtype=torch.float32).unsqueeze(0)

    processor(torch.tensor([[20]]), scores.clone())
    processor(torch.tensor([[20, 21]]), scores.clone())
    assert controller.snapshot().all_text == ""
    assert not processor.constraints_started

    result = processor(torch.tensor([[20, 21, 22]]), scores.clone())
    assert processor.constraints_started
    assert controller.snapshot().all_text == ""
    assert torch.isfinite(result).any()

    processor(torch.tensor([[20, 21, 22, 2]]), scores.clone())
    assert controller.snapshot().all_text == "山"

