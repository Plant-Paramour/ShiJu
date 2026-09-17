from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Iterable

from .data import RhymeLookup
from .domain import GenerationState
from .tone_rules import RejectThreeSameEndingRule
from .vocab import TokenizerLike, VocabLookup


_TEXT_CHAR = re.compile(r"[\u4e00-\u9fa5A-Za-z]")
_FORBIDDEN_TOKEN_TEXT = re.compile(r"[\s　，。、？！；：\n\r]")


@dataclass(frozen=True)
class CandidateText:
    raw: str
    text: str


def decode_candidate(
    token_id: int,
    tokenizer: TokenizerLike,
    vocab: VocabLookup,
) -> CandidateText | None:
    """解码一个候选 token，并拒绝含标点或非诗文字符的 token。"""
    raw = tokenizer.decode([token_id])
    text = vocab.text_for_token(token_id)
    if not text:
        text = raw.replace(" ", "").replace("\r", "")
    text = "".join(char for char in text if _TEXT_CHAR.fullmatch(char))
    if _FORBIDDEN_TOKEN_TEXT.search(raw) or not text:
        return None
    return CandidateText(raw=raw, text=text)


def crosses_line_break(state: GenerationState, text: str) -> bool:
    if state.line is None:
        return True
    new_position = state.char_index + len(text)
    boundaries = (
        state.line.break_positions
        | state.line.caesura_positions
        | frozenset({state.line.length})
    )
    return any(state.char_index < point < new_position for point in boundaries)


def decode_position_candidate(
    token_id: int,
    tokenizer: TokenizerLike,
    vocab: VocabLookup,
    state: GenerationState,
) -> CandidateText | None:
    candidate = decode_candidate(token_id, tokenizer, vocab)
    if candidate is None or crosses_line_break(state, candidate.text):
        return None
    return candidate


def iter_tone_combinations(
    text: str,
    lexicon: RhymeLookup,
) -> Iterable[tuple[str, ...]]:
    options = [lexicon.get_pingze(char) for char in text]
    if any(not tones for tones in options):
        return ()
    return product(*options)


def has_three_same_ending(
    text: str,
    lexicon: RhymeLookup,
) -> bool:
    """只要存在一种末三字全平或全仄的解释，就返回 True。"""
    if len(text) < 3:
        return False
    rule = RejectThreeSameEndingRule()
    return any(
        not rule.validate(tones)
        for tones in iter_tone_combinations(text, lexicon)
    )


def would_force_three_same_ending(
    text: str,
    target_length: int,
    allowed_end_tones: Iterable[str],
    lexicon: RhymeLookup,
    *,
    reject_ambiguous: bool = False,
) -> bool:
    """倒数第二字生成后，判断所有可用末字声调是否都会形成三连同。"""
    if len(text) != target_length - 1 or len(text) < 2:
        return False

    end_tones = tuple(dict.fromkeys(allowed_end_tones))
    if not end_tones:
        return False
    third_tones = tuple(lexicon.get_pingze(text[-2]))
    second_tones = tuple(lexicon.get_pingze(text[-1]))
    if not third_tones or not second_tones:
        return False

    def forces_tone(end_tone: str) -> bool:
        if reject_ambiguous:
            return end_tone in third_tones and end_tone in second_tones
        return third_tones == (end_tone,) and second_tones == (end_tone,)

    return all(forces_tone(end_tone) for end_tone in end_tones)


def has_viable_tang_completion(
    text: str,
    target_length: int,
    line_tone: int,
    end_tone: int,
    lexicon: RhymeLookup,
    *,
    allow_aojiu: bool = False,
    strict_polyphonic: bool = True,
) -> bool:
    """判断关系型诗句的当前前缀能否补成合法的完整平仄序列。"""
    tone_options = tuple(
        tuple(dict.fromkeys(lexicon.get_pingze(char))) for char in text
    )
    if any(not tones for tones in tone_options):
        return False
    return _has_viable_tang_tones(
        tone_options,
        target_length,
        line_tone,
        end_tone,
        allow_aojiu,
        strict_polyphonic,
    )


@lru_cache(maxsize=8192)
def _has_viable_tang_tones(
    tone_options: tuple[tuple[str, ...], ...],
    target_length: int,
    line_tone: int,
    end_tone: int,
    allow_aojiu: bool,
    strict_polyphonic: bool,
) -> bool:
    if len(tone_options) > target_length:
        return False

    def full_line_is_valid(tones: tuple[str, ...]) -> bool:
        resolved_line_tone = line_tone
        if resolved_line_tone == 2:
            resolved_line_tone = 0 if tones[1] == "平" else 1

        expected_positions = (
            (1, resolved_line_tone),
            (3, 1 - resolved_line_tone),
            (5, resolved_line_tone),
        )
        for position, expected_value in expected_positions:
            if position >= target_length:
                continue
            expected = "平" if expected_value == 0 else "仄"
            if tones[position] == expected:
                continue
            rescued = False
            if allow_aojiu and resolved_line_tone == 0 and position == 3:
                rescued = tones[0] == tones[2] == "仄" and tones[-1] == "平"
            elif allow_aojiu and resolved_line_tone == 1 and position == 5:
                rescued = tones[2] == tones[4] == "仄" and tones[-1] == "平"
            if not rescued:
                return False

        if end_tone != 2 and tones[-1] != ("平" if end_tone == 0 else "仄"):
            return False
        if len(set(tones[-3:])) == 1:
            return False

        if tones[-1] == "平":
            if resolved_line_tone == 0:
                isolated = tones[0] == tones[2] == "仄"
                rescued = allow_aojiu and tones[3] == "平"
                if isolated and not rescued:
                    return False
            elif resolved_line_tone == 1 and target_length >= 7:
                isolated = tones[2] == tones[4] == "仄"
                rescued = allow_aojiu and tones[5] == "平"
                if isolated and not rescued:
                    return False
        return True

    prefixes = tuple(tuple(tones) for tones in product(*tone_options))

    @lru_cache(maxsize=None)
    def can_finish(suffix: tuple[str, ...]) -> bool:
        if len(tone_options) + len(suffix) == target_length:
            results = (
                full_line_is_valid(prefix + suffix)
                for prefix in prefixes
            )
            return all(results) if strict_polyphonic else any(results)
        return can_finish(suffix + ("平",)) or can_finish(suffix + ("仄",))

    return can_finish(())
