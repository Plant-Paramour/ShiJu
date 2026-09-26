"""独立 chunk 生成实验。

该脚本只依赖本地 Transformers 模型，不接入 shiju 生产生成链路。
它按固定字数逐 chunk 生成候选，并从 generate 的 transition scores 计算模型分数。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from scorer import Candidate, Lexicon, score


def _text_only(tokenizer, token_ids: list[int]) -> str:
    return tokenizer.decode(token_ids, skip_special_tokens=True).replace(" ", "")


def generate_chunk_candidates(
    model,
    tokenizer,
    prompt: str,
    target_chars: int,
    *,
    count: int,
    temperature: float,
    top_p: float,
) -> list[Candidate]:
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    prompt_length = inputs.input_ids.shape[1]
    # 一个汉字通常不会超过 3 个 token；多取一些 token 后过滤，避免多字 token 造成越界。
    max_new_tokens = max(4, target_chars * 3)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            num_return_sequences=count,
            return_dict_in_generate=True,
            output_scores=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    transition = model.compute_transition_scores(
        outputs.sequences,
        outputs.scores,
        normalize_logits=True,
    )
    candidates: list[Candidate] = []
    for index, sequence in enumerate(outputs.sequences):
        generated_ids = sequence[prompt_length:].tolist()
        text = _text_only(tokenizer, generated_ids)
        if len(text) != target_chars:
            continue
        token_scores = transition[index]
        # generate 的 score 长度对应生成步数；EOS 后的 padding 不纳入有效 token。
        valid_count = min(len(generated_ids), token_scores.shape[0])
        logprob = float(token_scores[:valid_count].sum().item())
        candidates.append(Candidate(text, logprob, valid_count))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3 固定句读 chunk 评分实验")
    parser.add_argument("--model", default=r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B")
    parser.add_argument("--prompt", required=True, help="生成第一个 chunk 前使用的提示词")
    parser.add_argument("--chunks", required=True, help="固定 chunk 字数，例如 2,3 或 2,2,3")
    parser.add_argument("--candidates", type=int, default=8, help="每个 chunk 采样候选数")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--lexicon", type=Path, default=Path("shiju/二三字词表.csv"))
    parser.add_argument("--lexicon-reward", action="store_true")
    parser.add_argument("--lambda", dest="weight", type=float, default=0.1)
    parser.add_argument("--output", type=Path, help="可选：写出 JSONL 结果")
    args = parser.parse_args()

    chunk_lengths = [int(item) for item in args.chunks.split(",") if item.strip()]
    if not chunk_lengths or any(item <= 0 for item in chunk_lengths):
        raise SystemExit("--chunks 必须是正整数，例如 2,3 或 2,2,3")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    lexicon = Lexicon(args.lexicon)
    context = args.prompt
    all_results: list[dict] = []

    for chunk_index, length in enumerate(chunk_lengths):
        candidates = generate_chunk_candidates(
            model,
            tokenizer,
            context,
            length,
            count=args.candidates,
            temperature=args.temperature,
            top_p=args.top_p,
        )
        if not candidates:
            raise SystemExit(
                f"第 {chunk_index + 1} 个 chunk 没有生成恰好 {length} 字的候选；"
                "可提高 --candidates 或降低 --temperature。"
            )
        ranked = [
            score(
                candidate,
                lexicon=lexicon,
                reward_enabled=args.lexicon_reward,
                reward_weight=args.weight,
            )
            for candidate in candidates
        ]
        ranked.sort(key=lambda item: float(item["total_score"]), reverse=True)
        best = ranked[0]
        all_results.append({"chunk_index": chunk_index, "candidates": ranked})
        context += str(best["chunk"])
        print(json.dumps(all_results[-1], ensure_ascii=False))

    print(json.dumps({"text": context, "lexicon_reward": args.lexicon_reward}, ensure_ascii=False))
    if args.output:
        args.output.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in all_results)
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
