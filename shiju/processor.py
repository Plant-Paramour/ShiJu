from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import torch
from transformers import LogitsProcessor

from .domain import CONTENT_MARKER, GenerationState, StepKind
from .policies import CandidateContext, PolicyTier
from .state import GenerationController
from .vocab import TokenizerLike, VocabLookup


class SeparatorPolicy(Protocol):
    @property
    def newline_tokens(self) -> set[int]: ...

    def allowed_tokens(self, state: GenerationState, constraint_context) -> set[int]: ...


@dataclass(frozen=True)
class ProcessorConfig:
    relax_rhyme_on_empty: bool = False
    raw_on_no_candidates: bool = False
    raw_after_policy_failure: bool = False
    release_constraints_after_finish: bool = False
    separator_empty_returns_raw: bool = False
    strict_polyphonic: bool = True


def _exact_token_ids(tokenizer: TokenizerLike, values: Sequence[str]) -> set[int]:
    wanted = set(values)
    result = set()
    for _, token_id in tokenizer.get_vocab().items():
        clean = tokenizer.decode([token_id]).replace(" ", "")
        if clean in wanted:
            result.add(token_id)
    for value in values:
        ids = tokenizer.encode(value, add_special_tokens=False)
        if ids:
            result.add(ids[0])
    return result


class TemplateSeparatorPolicy:
    def __init__(self, tokenizer: TokenizerLike, rhyming_lines: frozenset[int]):
        self._rhyming_lines = rhyming_lines
        self._punct_odd = _exact_token_ids(tokenizer, ("，", "？", "！", "，\n"))
        self._punct_even = _exact_token_ids(tokenizer, ("？", "！"))
        self._newline_odd = _exact_token_ids(tokenizer, ("\n", "，\n"))
        self._newline_even = _exact_token_ids(tokenizer, ("\n",))
        self._caesura = _exact_token_ids(tokenizer, ("、",))
        self._terminal_punct = _exact_token_ids(tokenizer, ("。", "？", "！", "。\n"))
        self._terminal_newline = _exact_token_ids(tokenizer, ("\n", "。\n"))

    @property
    def newline_tokens(self) -> set[int]:
        return set(self._terminal_newline)

    def allowed_tokens(self, state: GenerationState, constraint_context) -> set[int]:
        if state.step is StepKind.CAESURA:
            return set(self._caesura)
        if state.line is None:
            return set()
        is_rhyming = state.line_index in self._rhyming_lines
        is_odd = state.line.line_in_stanza % 2 == 0
        if state.step is StepKind.NEWLINE:
            if is_rhyming:
                return set(self._terminal_newline)
            return set(self._newline_odd if is_odd else self._newline_even)
        if state.step is StepKind.PUNCTUATION:
            if is_rhyming:
                return set(self._terminal_punct)
            return set(self._punct_odd if is_odd else self._punct_even)
        return set()


class RelationalSeparatorPolicy:
    def __init__(self, tokenizer: TokenizerLike):
        self._comma = self._encode_all(tokenizer, ("，", ","))
        self._period = self._encode_all(tokenizer, ("。", "."))
        self._question = self._encode_all(tokenizer, ("？", "?"))
        self._exclamation = self._encode_all(tokenizer, ("！", "!"))
        self._newline = self._encode_all(tokenizer, ("\n",))

    @staticmethod
    def _encode_all(tokenizer: TokenizerLike, values: Sequence[str]) -> set[int]:
        result = set()
        for value in values:
            result.update(tokenizer.encode(value, add_special_tokens=False))
        return result

    @property
    def newline_tokens(self) -> set[int]:
        return set(self._newline)

    def allowed_tokens(self, state: GenerationState, constraint_context) -> set[int]:
        if state.step is not StepKind.PUNCTUATION:
            return set()
        if (state.line_index + 1) % 2 == 0:
            return set(self._period | self._question | self._exclamation)
        return set(self._comma)


class NewlineSeparatorPolicy:
    """用于内部强制顿号、行间只换行的诗体。"""

    def __init__(self, tokenizer: TokenizerLike):
        self._newline = _exact_token_ids(tokenizer, ("\n",))
        self._caesura = _exact_token_ids(tokenizer, ("、",))

    @property
    def newline_tokens(self) -> set[int]:
        return set(self._newline)

    def allowed_tokens(self, state: GenerationState, constraint_context) -> set[int]:
        if state.step is StepKind.CAESURA:
            return set(self._caesura)
        if state.step is StepKind.NEWLINE:
            return set(self._newline)
        return set()


class ConstrainedLogitsProcessor(LogitsProcessor):
    """诗体无关的约束解码管线。"""

    def __init__(
        self,
        vocab: VocabLookup,
        controller: GenerationController,
        tokenizer: TokenizerLike,
        input_prompt_len: int,
        separator_policy: SeparatorPolicy,
        policy_tiers: Sequence[PolicyTier],
        config: ProcessorConfig,
        activation_marker: str = CONTENT_MARKER,
    ):
        if not activation_marker:
            raise ValueError("约束启动标记不能为空")
        self._vocab = vocab
        self._controller = controller
        self._tokenizer = tokenizer
        self._input_prompt_len = input_prompt_len
        self._separator_policy = separator_policy
        self._policy_tiers = tuple(policy_tiers)
        self._config = config
        self._activation_marker = activation_marker
        self._last_decoded_text = ""
        self._has_started_content = False
        self._eos_token_id = tokenizer.eos_token_id
        self._completion_waiting = False
        self._constraints_released = False
        self._semicolon_token_ids = set(
            tokenizer.encode("；", add_special_tokens=False)
        )

    def __call__(
        self,
        input_ids: torch.LongTensor,
        scores: torch.FloatTensor,
    ) -> torch.FloatTensor:
        for token_id in self._semicolon_token_ids:
            if 0 <= token_id < scores.shape[1]:
                scores[:, token_id] = -float("inf")

        generated_ids = input_ids[0][self._input_prompt_len :].tolist()
        raw_text = self._tokenizer.decode(generated_ids, skip_special_tokens=True)
        raw_text = raw_text.replace(" ", "").replace("\r", "")
        if not self._track_constrained_content(raw_text):
            return scores

        if self._constraints_released:
            return scores
        if self._completion_waiting:
            if generated_ids and "\n" in self._tokenizer.decode([generated_ids[-1]]):
                self._constraints_released = True
                return scores
            return self._completion_mask(scores)

        state = self._controller.snapshot()
        if state.is_finished:
            if self._config.release_constraints_after_finish:
                self._completion_waiting = True
                return self._completion_mask(scores)
            return self._only_tokens(scores, {self._eos_token_id})

        if state.step is not StepKind.TEXT:
            allowed = self._separator_policy.allowed_tokens(
                state,
                self._controller.candidate_context(),
            )
            if not allowed and self._config.separator_empty_returns_raw:
                return scores
            if not allowed:
                allowed = {self._eos_token_id}
            return self._only_tokens(scores, allowed)

        patterns = self._controller.allowed_patterns()
        allowed_ids = self._vocab.resolve_patterns(
            patterns,
            strict_polyphonic=self._config.strict_polyphonic,
        )
        vocab_size = scores.shape[1]
        allowed_ids = self._limit_to_current_segment(allowed_ids, vocab_size)
        if not allowed_ids and self._config.relax_rhyme_on_empty:
            allowed_ids = self._vocab.resolve_patterns(
                patterns,
                ignore_rhyme=True,
                strict_polyphonic=self._config.strict_polyphonic,
            )
            allowed_ids = self._limit_to_current_segment(allowed_ids, vocab_size)
        if not allowed_ids:
            if self._config.raw_on_no_candidates:
                result = scores.clone()
                result[:, self._eos_token_id] = -float("inf")
                return result
            return self._only_tokens(scores, {self._eos_token_id})

        state = self._controller.snapshot()
        candidate_context = CandidateContext(
            state=state,
            constraint=self._controller.candidate_context(),
            tokenizer=self._tokenizer,
            vocab=self._vocab,
        )
        sorted_ids = sorted(allowed_ids)
        for tier in self._policy_tiers or (PolicyTier("base", ()),):
            result = torch.full_like(scores, -float("inf"))
            accepted = False
            for token_id in sorted_ids:
                penalty = tier.evaluate(token_id, candidate_context)
                if penalty is None:
                    continue
                result[0, token_id] = scores[0, token_id] - penalty
                accepted = True
            if accepted:
                return result

        if self._config.raw_after_policy_failure:
            return scores
        return self._only_tokens(scores, {self._eos_token_id})

    def _limit_to_current_segment(
        self,
        token_ids: set[int],
        vocab_size: int,
    ) -> set[int]:
        max_characters = self._controller.remaining_before_boundary()
        if max_characters <= 0:
            return set()
        return {
            token_id
            for token_id in token_ids
            if 0 <= token_id < vocab_size
            and 0 < len(self._vocab.text_for_token(token_id)) <= max_characters
        }

    @property
    def constraints_started(self) -> bool:
        return self._has_started_content

    def _track_constrained_content(self, raw_text: str) -> bool:
        if not self._has_started_content:
            if self._activation_marker not in raw_text:
                return False
            self._has_started_content = True
            content = raw_text.split(self._activation_marker, 1)[1]
            self._controller.advance(content)
            self._last_decoded_text = content
            return True
        content = (
            raw_text.split(self._activation_marker, 1)[1]
            if self._activation_marker in raw_text
            else raw_text
        )
        if len(content) > len(self._last_decoded_text):
            latest = content[len(self._last_decoded_text) :]
            self._controller.advance(latest)
            self._last_decoded_text = content
        return True

    def _completion_mask(self, scores: torch.FloatTensor) -> torch.FloatTensor:
        return self._only_tokens(
            scores,
            self._separator_policy.newline_tokens | {self._eos_token_id},
        )

    @staticmethod
    def _only_tokens(scores: torch.FloatTensor, token_ids: set[int]) -> torch.FloatTensor:
        result = torch.full_like(scores, -float("inf"))
        for token_id in token_ids:
            if 0 <= token_id < scores.shape[1]:
                result[:, token_id] = scores[:, token_id]
        return result
