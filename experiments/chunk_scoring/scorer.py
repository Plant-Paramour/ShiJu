from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    chunk: str
    model_logprob: float
    token_count: int | None = None


class Lexicon:
    def __init__(self, path: str | Path):
        self._frequency: dict[str, int] = {}
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                word = (row.get("word") or "").strip()
                if len(word) not in (2, 3):
                    continue
                try:
                    frequency = int(row.get("frequency") or 0)
                except ValueError:
                    frequency = 0
                self._frequency[word] = max(frequency, self._frequency.get(word, 0))

    def bonus(self, chunk: str, *, saturation: float = 10.0) -> float:
        """Return positive evidence only; an unknown chunk receives exactly zero."""
        matches: list[float] = []
        for length in (2, 3):
            for start in range(len(chunk) - length + 1):
                word = chunk[start : start + length]
                frequency = self._frequency.get(word)
                if frequency is None:
                    continue
                compressed = math.log1p(frequency)
                matches.append(compressed / (compressed + saturation))
        if not matches:
            return 0.0
        return max(matches)


def score(
    candidate: Candidate,
    *,
    lexicon: Lexicon | None = None,
    reward_enabled: bool = False,
    reward_weight: float = 0.1,
) -> dict[str, float | str]:
    if not candidate.chunk:
        raise ValueError("chunk 不能为空")
    if candidate.model_logprob > 0:
        raise ValueError("model_logprob 应为不大于 0 的对数概率")
    char_count = len(candidate.chunk)
    model_score = candidate.model_logprob / char_count
    lexicon_bonus = lexicon.bonus(candidate.chunk) if lexicon else 0.0
    total = model_score + reward_weight * lexicon_bonus if reward_enabled else model_score
    return {
        "chunk": candidate.chunk,
        "model_score": model_score,
        "lexicon_bonus": lexicon_bonus,
        "total_score": total,
    }
