#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Judge 评分排行榜生成脚本。
读取 results/llm_judge/full.json，按模型 × 模式 × 体裁输出：
  - 约束解码: TOP 10（唐诗/宋词各 10）
  - 自由生成: TOP 5（唐诗/宋词各 5）
排名依据: avg_total（两轮 LLM 评分的平均分，满分 15）
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "results" / "llm_judge" / "full.json"
OUTPUT_DIR = BASE_DIR / "results" / "top_ranking"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_N_CONSTRAINED = 10
TOP_N_FREE = 5
TOP_N_OTHER = 10


def load_data():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_ranking_table(works, top_n):
    """按 avg_total 降序排列并取 TOP N"""
    sorted_works = sorted(works, key=lambda w: w.get("avg_total", 0), reverse=True)
    return sorted_works[:top_n]


def format_ranked_entry(rank, entry):
    """格式化单条排行：排名 + 评分 + 诗文内容"""
    lines = []
    title = entry.get("content_title", entry.get("title", ""))
    theme = entry.get("theme", "")
    total = entry.get("avg_total", "")
    pct = entry.get("avg_total_pct", "")
    lang = entry.get("avg_lang", "")
    logic = entry.get("avg_logic", "")
    imagery = entry.get("avg_imagery", "")
    content = entry.get("content", "")
    flaws = entry.get("hard_flaws", [])

    total_str = f"{total:.2f}" if isinstance(total, (int, float)) else str(total)
    pct_str = f"{pct:.2f}" if isinstance(pct, (int, float)) else str(pct)
    lang_str = f"{lang:.2f}" if isinstance(lang, (int, float)) else str(lang)
    logic_str = f"{logic:.2f}" if isinstance(logic, (int, float)) else str(logic)
    imagery_str = f"{imagery:.2f}" if isinstance(imagery, (int, float)) else str(imagery)

    lines.append(f"### No.{rank} — {title}（{theme}）")
    lines.append("")
    lines.append(f"> **总分: {total_str}/15** ({pct_str}%) | 语言: {lang_str}/5 | 逻辑: {logic_str}/5 | 意境: {imagery_str}/5")
    lines.append("")
    lines.append("```")
    lines.append(content.strip())
    lines.append("```")

    real_flaws = [f for f in flaws if f]
    if real_flaws:
        for flaw in real_flaws:
            lines.append(f"> ⚠ {flaw}")
    lines.append("")
    return lines


def generate_ranking_md(data):
    """生成完整排行 Markdown 报告"""
    works_data = data.get("works", {})
    models = sorted(works_data.keys())
    meta = data.get("meta", {})
    scoring_system = meta.get("scoring_system", "")

    lines = []
    lines.append("# LLM Judge 评分排行榜")
    lines.append("")
    lines.append(f"> 评分体系: {scoring_system}")
    lines.append(f"> 约束解码 TOP {TOP_N_CONSTRAINED} / 自由生成 TOP {TOP_N_FREE}")
    lines.append("")

    mode_meta = meta.get("modes", {})
    mode_labels = {
        "constrained_decoding": f"约束解码 TOP {TOP_N_CONSTRAINED}",
        "free_decoding": f"自由生成 TOP {TOP_N_FREE}",
    }
    for mode_key, label in mode_meta.items():
        if mode_key not in mode_labels:
            mode_labels[mode_key] = f"{label} TOP {TOP_N_OTHER}"
    genre_keys = [("tang", "唐诗"), ("songci", "宋词")]

    for model in models:
        lines.append(f"---")
        lines.append(f"# {model}")
        lines.append("")

        for mode_key, mode_label in mode_labels.items():
            mode_data = works_data.get(model, {}).get(mode_key, {})
            top_n = TOP_N_CONSTRAINED if mode_key == "constrained_decoding" else (
                TOP_N_FREE if mode_key == "free_decoding" else TOP_N_OTHER
            )

            if not mode_data:
                continue

            lines.append(f"## {mode_label}")
            lines.append("")

            for genre_key, genre_label in genre_keys:
                entries = mode_data.get(genre_key, [])
                if not entries:
                    continue

                lines.append(f"### {genre_label}")
                lines.append("")

                ranked = build_ranking_table(entries, top_n)
                for rank, entry in enumerate(ranked, 1):
                    lines.extend(format_ranked_entry(rank, entry))

            lines.append("---")
            lines.append("")

        lines.append("")
    return "\n".join(lines)


def generate_ranking_json(data):
    """生成结构化排行 JSON"""
    works_data = data.get("works", {})
    models = sorted(works_data.keys())

    output = {}
    for model in models:
        output[model] = {}
        for mode_key in sorted(works_data.get(model, {}).keys()):
            mode_data = works_data.get(model, {}).get(mode_key, {})
            if not mode_data:
                continue

            top_n = TOP_N_CONSTRAINED if mode_key == "constrained_decoding" else (
                TOP_N_FREE if mode_key == "free_decoding" else TOP_N_OTHER
            )
            output[model][mode_key] = {}

            for genre_key, genre_label in [("tang", "唐诗"), ("songci", "宋词")]:
                entries = mode_data.get(genre_key, [])
                if not entries:
                    continue
                ranked = build_ranking_table(entries, top_n)
                output[model][mode_key][genre_key] = [
                    {"rank": i + 1, **entry}
                    for i, entry in enumerate(ranked)
                ]

    return output


def main():
    print("=" * 60)
    print("  LLM Judge 排行生成")
    print(f"  数据源: {INPUT_FILE}")
    print(f"  输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    data = load_data()
    model_list = data.get("meta", {}).get("models", [])
    print(f"\n模型: {model_list}")

    # Markdown 报告
    print("\n[1/2] 生成 Markdown 排行报告...")
    md_content = generate_ranking_md(data)
    md_path = OUTPUT_DIR / "ranking.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"  -> {md_path}")

    # JSON 结构化数据
    print("\n[2/2] 生成 JSON 排行数据...")
    json_data = generate_ranking_json(data)
    json_path = OUTPUT_DIR / "ranking.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"  -> {json_path}")

    # 控制台快速摘要
    print("\n" + "=" * 60)
    print("  快速摘要")
    print("=" * 60)

    for model in model_list:
        print(f"\n[{model}]")
        for mode_key, mode_label in data.get("meta", {}).get("modes", {}).items():
            print(f"  {mode_label}:")
            for genre_key, genre_label in [("tang", "唐诗"), ("songci", "宋词")]:
                entries = json_data.get(model, {}).get(mode_key, {}).get(genre_key, [])
                if entries:
                    top1 = entries[0]
                    print(f"    {genre_label} TOP1: {top1.get('content_title','')} ({top1.get('avg_total')}/15)")

    print("\n完成!")


if __name__ == "__main__":
    main()
