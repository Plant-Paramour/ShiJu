from __future__ import annotations

import re
from dataclasses import dataclass
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
