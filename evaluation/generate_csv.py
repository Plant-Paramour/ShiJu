#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV 生成脚本：读取 results/ 下所有评分 JSON，输出分析用 CSV。
"""

import json
import os
import csv
import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent  # evaluation/
AUTO_SCORE_DIR = BASE_DIR / "results" / "auto_score"
LLM_JUDGE_FILE = BASE_DIR / "results" / "llm_judge" / "full.json"
CSV_DIR = BASE_DIR / "csv"


def open_output_csv(path):
    try:
        return open(path, "w", encoding="utf-8-sig", newline=""), path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
        print(f"  [WARN] 无法写入 {path.name}，改写到: {fallback}")
        return open(fallback, "w", encoding="utf-8-sig", newline=""), fallback


def mode_to_constraint_label(mode):
    return {
        "constrained_decoding": "是",
        "free_decoding": "否",
        "SOTA": "SOTA",
    }.get(mode, mode)


def load_auto_score_per_works():
    """读取所有 auto_score per-file JSON，返回逐作品列表。"""
    works = []

    for mode_dir in sorted(AUTO_SCORE_DIR.iterdir()):
        if not mode_dir.is_dir():
            continue
        mode = mode_dir.name

        for model_dir in sorted(mode_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            model = model_dir.name

            for json_file in sorted(model_dir.glob("*_evaluation.json")):
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                form_name = data.get("form_name", "")
                form_type = data.get("form_type", "")
                theme = data.get("theme", "")
                is_constrained = mode_to_constraint_label(mode)

                for result in data.get("individual_results", []):
                    ev = result.get("evaluation", {})
                    if "error" in ev:
                        continue

                    works.append({
                        "model": model,
                        "form_name": form_name,
                        "form_type": form_type,
                        "theme": result.get("theme") or theme,
                        "is_constrained": is_constrained,
                        "mode": mode,
                        "work_index": result.get("work_index", 0),
                        "content": result.get("poem_text", ""),
                        "structure_score": ev.get("structure_score_percentage", 0),
                        "tonal_score": ev.get("tonal_score_percentage", 0),
                        "rhyme_score": ev.get("rhyme_score_percentage", 0),
                        "rule_total": ev.get("total_score_percentage", 0),
                    })

    return works


def load_llm_per_works():
    """读取 LLM 评分逐作品数据 (full.json)。"""
    if not LLM_JUDGE_FILE.exists():
        print(f"[WARN] LLM judge file not found: {LLM_JUDGE_FILE}")
        return {}

    with open(LLM_JUDGE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("works", {})


def build_llm_pool(llm_works):
    """构建 LLM 评分池: (model, mode, category, theme) -> [scores dict, ...].

    不使用 idx 做 key，而是在 CSV 生成时按顺序消费，避免 auto_score 的
    work_index 与 LLM 侧 0-based index 不一致的问题。
    """
    pool = defaultdict(list)

    for model, modes in llm_works.items():
        for mode, categories in modes.items():
            for category, works_list in categories.items():
                by_theme = defaultdict(list)
                for w in works_list:
                    by_theme[w.get("theme", "")].append(w)

                for theme, w_list in by_theme.items():
                    for w in w_list:
                        key = (model, mode, category, theme)
                        pool[key].append({
                            "lang_score": w.get("avg_lang"),
                            "logic_score": w.get("avg_logic"),
                            "imagery_score": w.get("avg_imagery"),
                            "writing_total": w.get("avg_total"),
                        })

    return pool


def form_type_to_category(form_type):
    """auto_score 的 form_type → LLM 的 category."""
    return "tang" if form_type == "tang" else "songci"


def category_to_shici(category):
    """tang/songci → 诗/词."""
    return "诗" if category == "tang" else "词"


def write_per_work_csv(auto_works, llm_pool):
    """表1: per_work_detail.csv — 一行一首作品。"""
    os.makedirs(CSV_DIR, exist_ok=True)
    output_path = CSV_DIR / "per_work_detail.csv"

    fieldnames = [
        "模型", "体裁", "主题", "作品内容", "是否约束",
        "结构分数", "平仄分数", "押韵分数", "形式规则总分",
        "语言分数", "逻辑分数", "意境分数", "写作总分",
    ]

    # 排序: model → form_name → theme → 同世代约束/自由配对 → work_index
    auto_works.sort(key=lambda w: (
        w["model"],
        w["form_name"],
        w["theme"],
        w["work_index"],
        0 if w["is_constrained"] == "是" else 1,
    ))

    # 从 pool 深拷贝消费计数器
    consume_counter = {k: 0 for k in llm_pool}

    rows = []
    for w in auto_works:
        category = form_type_to_category(w["form_type"])
        pool_key = (w["model"], w["mode"], category, w["theme"])
        scores_list = llm_pool.get(pool_key, [])
        idx = consume_counter.get(pool_key, 0)

        llm = {}
        if idx < len(scores_list):
            llm = scores_list[idx]
            consume_counter[pool_key] = idx + 1

        rows.append({
            "模型": w["model"],
            "体裁": w["form_name"],
            "主题": w["theme"],
            "作品内容": w["content"],
            "是否约束": w["is_constrained"],
            "结构分数": w["structure_score"],
            "平仄分数": w["tonal_score"],
            "押韵分数": w["rhyme_score"],
            "形式规则总分": w["rule_total"],
            "语言分数": llm.get("lang_score") if llm.get("lang_score") is not None else "",
            "逻辑分数": llm.get("logic_score") if llm.get("logic_score") is not None else "",
            "意境分数": llm.get("imagery_score") if llm.get("imagery_score") is not None else "",
            "写作总分": llm.get("writing_total") if llm.get("writing_total") is not None else "",
        })

    f, actual_output_path = open_output_csv(output_path)
    with f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  已生成: {actual_output_path} ({len(rows)} 行)")


def write_summary_csv(auto_works, llm_pool):
    """表2: summary.csv — 按模型×否约束×诗/词 汇总。"""
    output_path = CSV_DIR / "summary.csv"

    fieldnames = [
        "模型", "是否约束", "诗/词",
        "结构均分", "平仄均分", "押韵均分", "形式规则总分",
        "语言均分", "逻辑均分", "意境均分", "写作均分",
    ]

    # 分组: (model, is_constrained, category)
    groups = defaultdict(lambda: {
        "structure": [], "tonal": [], "rhyme": [], "rule_total": [],
        "lang": [], "logic": [], "imagery": [], "writing": [],
    })

    # 从 pool 深拷贝消费计数器
    consume_counter = {k: 0 for k in llm_pool}

    for w in auto_works:
        category = form_type_to_category(w["form_type"])
        group_key = (w["model"], w["is_constrained"], category)

        groups[group_key]["structure"].append(w["structure_score"])
        groups[group_key]["tonal"].append(w["tonal_score"])
        groups[group_key]["rhyme"].append(w["rhyme_score"])
        groups[group_key]["rule_total"].append(w["rule_total"])

        pool_key = (w["model"], w["mode"], category, w["theme"])
        scores_list = llm_pool.get(pool_key, [])
        idx = consume_counter.get(pool_key, 0)

        if idx < len(scores_list):
            llm = scores_list[idx]
            consume_counter[pool_key] = idx + 1
            if llm.get("lang_score") is not None:
                groups[group_key]["lang"].append(llm["lang_score"])
            if llm.get("logic_score") is not None:
                groups[group_key]["logic"].append(llm["logic_score"])
            if llm.get("imagery_score") is not None:
                groups[group_key]["imagery"].append(llm["imagery_score"])
            if llm.get("writing_total") is not None:
                groups[group_key]["writing"].append(llm["writing_total"])

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else ""

    rows = []
    for (model, is_constrained, category), scores in sorted(groups.items()):
        rows.append({
            "模型": model,
            "是否约束": is_constrained,
            "诗/词": category_to_shici(category),
            "结构均分": avg(scores["structure"]),
            "平仄均分": avg(scores["tonal"]),
            "押韵均分": avg(scores["rhyme"]),
            "形式规则总分": avg(scores["rule_total"]),
            "语言均分": avg(scores["lang"]),
            "逻辑均分": avg(scores["logic"]),
            "意境均分": avg(scores["imagery"]),
            "写作均分": avg(scores["writing"]),
        })

    f, actual_output_path = open_output_csv(output_path)
    with f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  已生成: {actual_output_path} ({len(rows)} 行)")


def main():
    print("=" * 60)
    print("  CSV 生成工具")
    print("=" * 60)

    # 1. 加载规则评分
    print("[1/3] 加载规则评分数据...")
    auto_works = load_auto_score_per_works()
    print(f"  规则评分作品数: {len(auto_works)}")

    # 2. 加载 LLM 评分
    print("[2/3] 加载 LLM 评分数据...")
    llm_works = load_llm_per_works()
    llm_pool = build_llm_pool(llm_works)
    print(f"  LLM 评分条目数: {sum(len(v) for v in llm_pool.values())}")

    # 3. 写 CSV
    print("[3/3] 生成 CSV 文件...")
    write_per_work_csv(auto_works, llm_pool)
    write_summary_csv(auto_works, llm_pool)

    print("\n  完成!")


if __name__ == "__main__":
    main()
