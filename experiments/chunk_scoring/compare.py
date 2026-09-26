from __future__ import annotations

import argparse
import json
from pathlib import Path

from scorer import Candidate, Lexicon, score


def main() -> None:
    parser = argparse.ArgumentParser(description="比较句读 chunk 的模型排序与词表弱奖励排序")
    parser.add_argument("candidates", type=Path, help="JSONL 候选文件")
    parser.add_argument("--lexicon", type=Path, default=Path("shiju/二三字词表.csv"))
    parser.add_argument("--lexicon-reward", action="store_true")
    parser.add_argument("--lambda", dest="weight", type=float, default=0.1)
    args = parser.parse_args()
    lexicon = Lexicon(args.lexicon)
    results = []
    for line_number, raw in enumerate(args.candidates.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
            candidate = Candidate(
                chunk=str(item["chunk"]),
                model_logprob=float(item["model_logprob"]),
                token_count=item.get("token_count"),
            )
            results.append(
                score(
                    candidate,
                    lexicon=lexicon,
                    reward_enabled=args.lexicon_reward,
                    reward_weight=args.weight,
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"第 {line_number} 行无效: {exc}") from exc
    for rank, result in enumerate(sorted(results, key=lambda item: item["total_score"], reverse=True), 1):
        print(json.dumps({"rank": rank, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
