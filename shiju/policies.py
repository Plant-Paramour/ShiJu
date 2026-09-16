from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import product
from typing import Any, Protocol, Sequence

from .constraints import HanpaiConstraintContext, RelationalConstraintContext
from .data import RhymeLookup
from .domain import GenerationState
from .vocab import TokenizerLike, VocabLookup


@dataclass(frozen=True)
class CandidateContext:
    state: GenerationState
    constraint: Any
    tokenizer: TokenizerLike
    vocab: VocabLookup


class CandidatePolicy(Protocol):
    def evaluate(self, token_id: int, context: CandidateContext) -> float | None: ...


@dataclass(frozen=True)
class PolicyTier:
    name: str
    policies: Sequence[CandidatePolicy]

    def evaluate(self, token_id: int, context: CandidateContext) -> float | None:
        penalty = 0.0
        for policy in self.policies:
            item_penalty = policy.evaluate(token_id, context)
            if item_penalty is None:
                return None
            penalty += item_penalty
        return penalty


class BoundaryCoherencePolicy:
    """统一的句读粘连惩罚。"""

    def __init__(self, common_bigrams: frozenset[str], penalty: float = 50.0):
        self._common_bigrams = common_bigrams
        self._penalty = penalty

    def evaluate(self, token_id: int, context: CandidateContext) -> float | None:
        state = context.state
        if state.line is None or state.char_index not in state.line.break_positions:
            return 0.0
        token_text = context.vocab.text_for_token(token_id)
        if not token_text or not state.current_line_text:
            return 0.0
        bigram = state.current_line_text[-1] + token_text[0]
        return self._penalty if bigram in self._common_bigrams else 0.0


class RepetitionPenaltyPolicy:
    def __init__(
        self,
        base_penalty: float = 20.0,
        decay_rate: float = 0.05,
        min_penalty: float = 8.0,
    ):
        self._base_penalty = base_penalty
        self._decay_rate = decay_rate
        self._min_penalty = min_penalty

    def evaluate(self, token_id: int, context: CandidateContext) -> float | None:
        last_positions: dict[str, int] = {}
        for position, char in enumerate(context.state.all_text):
            last_positions[char] = position
        if not last_positions:
            return 0.0
        token_text = context.vocab.text_for_token(token_id)
        current_position = len(context.state.all_text)
        penalty = 0.0
        for char in token_text:
            if char not in last_positions:
                continue
            distance = max(1, current_position - last_positions[char])
            decayed = self._base_penalty * math.exp(-self._decay_rate * distance)
            penalty += max(self._min_penalty, decayed)
        return penalty


class HanpaiVerifierPolicy:
    """校验汉俳可选的孤平、拗救和句尾三连同规则。"""

    _TEXT_CHAR = re.compile(r"[一-龥A-Za-z]")

    def __init__(self, lexicon: RhymeLookup):
        self._lexicon = lexicon

    def evaluate(self, token_id: int, context: CandidateContext) -> float | None:
        info = context.constraint
        if not isinstance(info, HanpaiConstraintContext):
            raise TypeError("HanpaiVerifierPolicy 需要 HanpaiConstraintContext")

        raw = context.tokenizer.decode([token_id])
        token_text = context.vocab.text_for_token(token_id)
        if not token_text:
            token_text = raw.replace(" ", "").replace("\r", "")
        token_chars = "".join(
            char for char in token_text if self._TEXT_CHAR.fullmatch(char)
        )
        if re.search(r"[\s　，。、？！；：\n\r]", raw) or not token_chars:
            return None

        simulated = context.state.current_line_text + token_chars
        if len(simulated) > info.target_length:
            return None
        if len(simulated) < info.target_length:
            return 0.0
        if not info.forbid_isolated_level and not info.forbid_three_same_ending:
            return 0.0

        tone_options = [self._lexicon.get_pingze(char) for char in simulated]
        if any(not options for options in tone_options):
            return None
        for tones in product(*tone_options):
            if self._valid_tone_sequence(tones, info):
                return 0.0
        return None

    @staticmethod
    def _valid_tone_sequence(
        tones: tuple[str, ...],
        info: HanpaiConstraintContext,
    ) -> bool:
        if info.forbid_three_same_ending and len(tones) >= 3:
            if len(set(tones[-3:])) == 1:
                return False
        if not info.forbid_isolated_level:
            return True

        for index in range(1, len(tones) - 1):
            if tones[index - 1 : index + 2] != ("仄", "平", "仄"):
                continue
            if info.allow_aojiu:
                left_rescue = index >= 2 and tones[index - 2] == "平"
                right_rescue = index + 2 < len(tones) and tones[index + 2] == "平"
                if left_rescue or right_rescue:
                    continue
            return False
        return True


class TangVerifierPolicy:
    """唐诗 poem_verifier 风格规则；mode=critical 时只保留核心格律底线。"""

    _TEXT_CHAR = re.compile(r"[一-龥A-Za-z]")

    def __init__(self, lexicon: RhymeLookup, mode: str = "full"):
        if mode not in {"full", "critical"}:
            raise ValueError(f"未知唐诗校验模式: {mode}")
        self._lexicon = lexicon
        self._mode = mode

    def evaluate(self, token_id: int, context: CandidateContext) -> float | None:
        relational = context.constraint
        if not isinstance(relational, RelationalConstraintContext):
            raise TypeError("TangVerifierPolicy 需要 RelationalConstraintContext")
        if self._mode == "critical":
            return self._critical(token_id, context, relational)
        return self._full(token_id, context, relational)

    def _decode_chars(self, token_id: int, context: CandidateContext) -> tuple[str, str]:
        raw = context.tokenizer.decode([token_id])
        text = context.vocab.text_for_token(token_id)
        if not text:
            text = raw.replace(" ", "").replace("\r", "")
        chars = "".join(char for char in text if self._TEXT_CHAR.fullmatch(char))
        return raw, chars

    def _full(
        self,
        token_id: int,
        context: CandidateContext,
        info: RelationalConstraintContext,
    ) -> float | None:
        raw, token_chars = self._decode_chars(token_id, context)
        if re.search(r"[\s　，。、？！；：\n\r]", raw) or not token_chars:
            return None
        if any(char in {"的", "些", "么", "了"} for char in token_chars):
            return None

        state = context.state
        if state.line is None:
            return None
        new_position = state.char_index + len(token_chars)
        if any(state.char_index < point < new_position for point in state.line.break_positions):
            return None

        simulated = state.current_line_text + token_chars
        target_length = info.target_length
        if len(simulated) > target_length:
            return None

        line_tone = self._resolve_line_tone(info.base_tone, simulated, state.current_line_text)
        end_tone = self._end_tone(info)
        if not self._check_even_positions(simulated, line_tone):
            return None
        if not self._check_prevent_three_same(simulated, target_length, end_tone):
            return None
        if len(simulated) == target_length:
            if not self._check_last_three(simulated):
                return None
            if not self._check_isolated_level(simulated, line_tone):
                return None
            if not self._check_end_tone(simulated[-1], end_tone):
                return None
            if not self._check_end_character(simulated[-1], state, target_length):
                return None
            if not self._check_rhyme(simulated[-1], info):
                return None

        penalty = self._repetition_penalty(token_chars, state)
        if penalty is None:
            return None
        if not self._check_ngrams(token_chars, state):
            return None
        if any(not self._lexicon.get_pingze(char) for char in token_chars):
            return None
        return penalty

    def _critical(
        self,
        token_id: int,
        context: CandidateContext,
        info: RelationalConstraintContext,
    ) -> float | None:
        raw, token_chars = self._decode_chars(token_id, context)
        if re.search(r"[\s　，。、？！；：\n\r]", raw) or not token_chars:
            return None
        state = context.state
        if state.line is None:
            return None
        new_position = state.char_index + len(token_chars)
        if any(state.char_index < point < new_position for point in state.line.break_positions):
            return None
        simulated = state.current_line_text + token_chars
        if len(simulated) > info.target_length:
            return None
        line_tone = self._resolve_line_tone(info.base_tone, simulated, state.current_line_text)
        end_tone = self._end_tone(info)
        if not self._check_even_positions(simulated, line_tone):
            return None
        if not self._check_prevent_three_same(simulated, info.target_length, end_tone):
            return None
        if len(simulated) == info.target_length:
            if not self._check_last_three(simulated):
                return None
            if not self._check_end_tone(simulated[-1], end_tone):
                return None
            if info.is_rhyming and info.locked_rhyme_parts:
                expected = "平" if "平" in info.rhyme_type else "仄"
                parts = set(self._lexicon.get_rhyme_part_by_tone(simulated[-1], expected))
                if parts and not info.locked_rhyme_parts.intersection(parts):
                    return None
        return 0.0

    def _resolve_line_tone(self, line_tone: int, simulated: str, previous: str) -> int:
        if line_tone == 2 and len(simulated) >= 2 and len(previous) < 2:
            tones = self._lexicon.get_pingze(simulated[1])
            if len(tones) == 1:
                return 0 if tones[0] == "平" else 1
        return line_tone

    @staticmethod
    def _end_tone(info: RelationalConstraintContext) -> int:
        if info.is_rhyming:
            return 0 if "平" in info.rhyme_type else 1
        if info.current_line == 0:
            return 2
        return 1 if "平" in info.rhyme_type else 0

    def _check_even_positions(self, line: str, line_tone: int) -> bool:
        checks = ((1, line_tone), (3, 1 - line_tone if line_tone != 2 else 2), (5, line_tone))
        for position, expected_value in checks:
            if position >= len(line) or expected_value == 2:
                continue
            tones = self._lexicon.get_pingze(line[position])
            if len(tones) == 1:
                expected = "平" if expected_value == 0 else "仄"
                if tones[0] != expected:
                    return False
        return True

    def _check_prevent_three_same(self, line: str, target: int, end_tone: int) -> bool:
        if len(line) != target - 1 or len(line) < 2 or end_tone == 2:
            return True
        third_from_end = line[target - 3]
        third_tones = self._lexicon.get_pingze(third_from_end)
        current_tones = self._lexicon.get_pingze(line[-1])
        if len(third_tones) != 1 or len(current_tones) != 1:
            return True
        expected = "平" if end_tone == 0 else "仄"
        return not (third_tones[0] == expected and current_tones[0] == expected)

    def _check_last_three(self, line: str) -> bool:
        if len(line) < 3:
            return True
        options = []
        for char in line[-3:]:
            tones = self._lexicon.get_pingze(char)
            options.append([0 if tone == "平" else 1 for tone in tones] or [None])
        for combination in product(*options):
            if None not in combination and sum(combination) in (0, 3):
                return False
        return True

    def _check_isolated_level(self, line: str, line_tone: int) -> bool:
        if len(line) < 3:
            return True
        last_tones = self._lexicon.get_pingze(line[-1])
        if len(last_tones) != 1 or last_tones[0] != "平":
            return True
        if line_tone == 0:
            left = self._lexicon.get_pingze(line[0])
            right = self._lexicon.get_pingze(line[2])
            return not (len(left) == len(right) == 1 and left[0] == right[0] == "仄")
        if line_tone == 1 and len(line) >= 5:
            left = self._lexicon.get_pingze(line[2])
            right = self._lexicon.get_pingze(line[4])
            return not (len(left) == len(right) == 1 and left[0] == right[0] == "仄")
        return True

    def _check_end_tone(self, char: str, end_tone: int) -> bool:
        tones = self._lexicon.get_pingze(char)
        if len(tones) != 1 or end_tone == 2:
            return True
        return tones[0] == ("平" if end_tone == 0 else "仄")

    @staticmethod
    def _check_end_character(char: str, state: GenerationState, target_length: int) -> bool:
        if char == "不":
            return False
        for previous_line in range(state.line_index):
            end_position = (previous_line + 1) * target_length - 1
            if end_position < len(state.all_text) and state.all_text[end_position] == char:
                return False
        return True

    def _check_rhyme(self, char: str, info: RelationalConstraintContext) -> bool:
        if not info.is_rhyming:
            return True
        expected = "平" if "平" in info.rhyme_type else "仄"
        parts = set(self._lexicon.get_rhyme_part_by_tone(char, expected))
        if info.locked_rhyme_parts and parts and not info.locked_rhyme_parts.intersection(parts):
            return False
        if info.excluded_rhyme_parts and parts and info.excluded_rhyme_parts.intersection(parts):
            return False
        return True

    @staticmethod
    def _repetition_penalty(token_chars: str, state: GenerationState) -> float | None:
        penalty = 0.0
        for char in token_chars:
            if char in state.current_line_text:
                penalty += 30.0
            count = state.all_text.count(char)
            if count >= 4:
                return None
            if count >= 2:
                penalty += count * 15.0
            elif count == 1:
                penalty += 5.0
        return penalty

    @staticmethod
    def _check_ngrams(token_chars: str, state: GenerationState) -> bool:
        line = state.current_line_text
        all_text = state.all_text
        for size in (3, 2):
            if len(token_chars) >= size:
                for index in range(len(token_chars) - size + 1):
                    gram = token_chars[index : index + size]
                    if gram in line or gram in all_text:
                        return False
        if len(line) >= 2 and token_chars and line[-2:] + token_chars[0] in all_text:
            return False
        if line and len(token_chars) >= 2 and line[-1] + token_chars[:2] in all_text:
            return False
        if line and token_chars and line[-1] + token_chars[0] in all_text:
            return False
        return True
