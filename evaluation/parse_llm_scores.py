#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 三维度评分汇总脚本。
解析 cleaned/ 下所有大模型评分文件（支持多轮），
计算各模型/各任务/是否约束生成的平均分，输出综合评分 JSON。
"""

import re
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


# ---------- 配置 ----------
BASE_DIR = Path(__file__).resolve().parent  # evaluation/
CLEANED_DIR = BASE_DIR / "cleaned"
SOTA_SOURCE_DIR = BASE_DIR / "SOTA"
OUTPUT_DIR = BASE_DIR / "results" / "llm_judge"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FULL_OUTPUT = OUTPUT_DIR / "full.json"
COMPACT_OUTPUT = OUTPUT_DIR / "compact.json"

# 评分文件匹配模式 — 匹配 "{Model}-{唐诗/宋词} - {评分模型}评分(N).txt"
SCORING_FILE_RE = re.compile(r"(.+?)-(唐诗|宋词)\s*-\s*(.+?)评分\((\d+)\)\.txt$")

# 唐诗权重 0.4，宋词权重 0.6
W_TANG = 0.4
W_SONGCI = 0.6

# 评分满分（用于归一化为百分制）
SCORE_MAX = 15.0

KNOWN_MODES = ["constrained_decoding", "free_decoding", "SOTA"]
SOTA_MODEL_ALIASES = {
    "诗三百": "shisanbai",
}


def _strip_poem_title_prefix(title):
    title = (title or "").strip()
    if "·" in title:
        title = title.split("·", 1)[1].strip()
    title = re.sub(r"[（(]其[一二三四五六七八九十]+[)）]$", "", title).strip()
    return title


def _extract_form_order(works):
    order = []
    seen = set()
    for work in works:
        title = work.get("title", "")
        if "·" not in title:
            continue
        form = title.split("·", 1)[0].strip()
        if form and form not in seen:
            seen.add(form)
            order.append(form)
    return order


def normalize(score):
    return round(score / SCORE_MAX * 100, 2)


def _round_items(rounds_dict):
    items = []
    for key, works in rounds_dict.items():
        m = re.fullmatch(r"round_(\d+)", key)
        if not m:
            continue
        items.append((int(m.group(1)), works))
    return sorted(items)


def _average_score(works, key):
    scores = [work.get(key) for work in works if work.get(key) is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _first_non_empty(works, key, default=""):
    for work in works:
        value = work.get(key)
        if value not in (None, ""):
            return value
    return default


def _format_round_counts(rounds_dict):
    items = _round_items(rounds_dict)
    if not items:
        return "0"
    return ", ".join(f"round_{round_num}={len(works)}" for round_num, works in items)


def build_score_counts(data):
    counts = {}
    for model in sorted(data.keys()):
        counts[model] = {}
        for mode in sorted(data[model].keys()):
            counts[model][mode] = {}
            mode_data = data[model][mode]
            for key, task_label in [("tang_scores", "tang"), ("songci_scores", "songci")]:
                if key in mode_data:
                    counts[model][mode][task_label] = {
                        f"round_{round_num}": len(works)
                        for round_num, works in _round_items(mode_data[key])
                    }
    return counts


def parse_scoring_file(filepath):
    """
    解析一个大模型评分文件，返回作品列表。
    每项: {title, lang, logic, imagery, total, hard_flaw}
    """
    works = []
    text = Path(filepath).read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=## 作品\d+)", text)
    for block in blocks:
        if not block.strip():
            continue
        title_m = re.search(r"^##\s*作品\d+\s*[：:]\s*(.+?)\s*$", block, re.M)
        if not title_m:
            continue
        title_line = title_m.group(1).strip() if title_m else ""
        title_bracket_m = re.search(r"《(.+?)》", title_line)
        title = title_bracket_m.group(1).strip() if title_bracket_m else title_line.strip("《》 ")

        lang_m = re.search(r"\*\*一、语言[（(](\d+\.?\d*)/5[)）]\*\*", block)
        lang = float(lang_m.group(1)) if lang_m else None

        logic_m = re.search(r"\*\*二、逻辑[（(](\d+\.?\d*)/5[)）]\*\*", block)
        logic = float(logic_m.group(1)) if logic_m else None

        imagery_m = re.search(r"\*\*三、意境[（(](\d+\.?\d*)/5[)）]\*\*", block)
        imagery = float(imagery_m.group(1)) if imagery_m else None

        total_m = re.search(r"\*\*总分[：:](\d+\.?\d*)/15\*\*", block)
        total = float(total_m.group(1)) if total_m else None

        flaw_m = re.search(r"\*\*硬伤[：:]\*\*\s*(.+?)(?:\n|$)", block)
        hard_flaw = flaw_m.group(1).strip() if flaw_m else ""

        works.append({
            "title": title,
            "lang": lang,
            "logic": logic,
            "imagery": imagery,
            "total": total,
            "hard_flaw": hard_flaw,
        })
    return works


def parse_content_file(filepath):
    text = Path(filepath).read_text(encoding="utf-8")
    works = []

    # 兼容 SOTA 原始格式：[title]... / [content]...
    marked_blocks = re.findall(
        r"\[title\]\s*(.*?)\s*\[content\]\s*(.*?)(?=(?:\n\s*\[title\])|\Z)",
        text,
        flags=re.DOTALL,
    )
    if marked_blocks:
        for title, content in marked_blocks:
            title = title.strip()
            content = content.strip()
            works.append({
                "theme": _strip_poem_title_prefix(title),
                "title": title,
                "content": content,
            })
        return works

    # 兼容现有生成输出：主题/作品名/内容 的分块格式
    blocks = text.strip().split("========================================")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        theme_m = re.search(r"主题[：:]\s*(.+)", block)
        title_m = re.search(r"作品名[：:]\s*(.+)", block)
        content_m = re.search(r"内容[：:]\s*\n(.+)", block, re.DOTALL)

        theme = theme_m.group(1).strip() if theme_m else ""
        title = title_m.group(1).strip() if title_m else ""
        content = content_m.group(1).strip() if content_m else ""

        works.append({
            "theme": theme,
            "title": title,
            "content": content,
        })
    return works


def _collect_mode_dirs():
    mode_dirs = []
    for mode_dir in sorted(CLEANED_DIR.iterdir()):
        if mode_dir.is_dir():
            mode_dirs.append(mode_dir)
    return mode_dirs


def _load_content_works(mode_name, model, task, form_order=None):
    if mode_name in {"constrained_decoding", "free_decoding"}:
        content_file = CLEANED_DIR / mode_name / f"{model}-{task}.txt"
        return parse_content_file(content_file) if content_file.exists() else []

    if mode_name == "SOTA":
        model_dir = SOTA_MODEL_ALIASES.get(model, model)
        genre_dir = "诗" if task == "唐诗" else "词"
        source_dir = SOTA_SOURCE_DIR / model_dir / genre_dir
        if not source_dir.exists():
            return []

        works = []
        candidate_files = []
        if form_order:
            candidate_files = [source_dir / f"{form}.txt" for form in form_order]
        else:
            candidate_files = sorted(source_dir.glob("*.txt"))

        for content_file in candidate_files:
            if not content_file.exists():
                continue
            if ".ipynb_checkpoints" in content_file.parts:
                continue
            form_name = content_file.stem
            for work in parse_content_file(content_file):
                entry = dict(work)
                entry["form_name"] = form_name
                works.append(entry)
        return works

    return []


def collect_data():
    """
    遍历 cleaned/ 目录，收集所有数据。
    返回:
      data[model][mode][task] = {
          "tang_scores": {round_N: [...works...]},
          "songci_scores": {...},
      }
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    for mode_dir in _collect_mode_dirs():
        mode = mode_dir.name

        for filepath in sorted(mode_dir.glob("*.txt")):
            fname = filepath.name

            # 匹配评分文件: Model-唐诗 - XXX评分(N).txt
            m = SCORING_FILE_RE.match(fname)
            if not m:
                # 跳过纯内容文件（如 Qwen3-4B-唐诗.txt）
                continue

            model = m.group(1)
            task = m.group(2)  # "唐诗" or "宋词"
            scoring_model = m.group(3)  # 评分模型名，如 "Deepseek"
            round_num = int(m.group(4))

            ds_works = parse_scoring_file(filepath)
            form_order = _extract_form_order(ds_works)
            content_works = _load_content_works(mode, model, task, form_order=form_order)

            merged = []
            for i, ds in enumerate(ds_works):
                entry = dict(ds)
                if i < len(content_works):
                    entry["theme"] = content_works[i]["theme"]
                    entry["content_title"] = content_works[i]["title"]
                    entry["content"] = content_works[i]["content"]
                    if "form_name" in content_works[i]:
                        entry["form_name"] = content_works[i]["form_name"]
                else:
                    entry["theme"] = ""
                    entry["content_title"] = ""
                    entry["content"] = ""
                merged.append(entry)

            key = "tang_scores" if task == "唐诗" else "songci_scores"
            if key not in data[model][mode]:
                data[model][mode][key] = {}
            data[model][mode][key][f"round_{round_num}"] = merged

    return data


def average_rounds(rounds_dict):
    round_items = _round_items(rounds_dict)
    if not round_items:
        return []

    results = []
    n = max(len(works) for _, works in round_items)
    for i in range(n):
        indexed_rounds = [
            (round_num, works[i])
            for round_num, works in round_items
            if i < len(works)
        ]
        round_nums = [round_num for round_num, _ in indexed_rounds]
        works = [work for _, work in indexed_rounds]

        avg_total = _average_score(works, "total")
        avg_lang = _average_score(works, "lang")
        avg_logic = _average_score(works, "logic")
        avg_imagery = _average_score(works, "imagery")
        round_totals = {
            f"round_{round_num}": work.get("total")
            for round_num, work in indexed_rounds
        }

        results.append({
            "title": _first_non_empty(works, "title"),
            "theme": _first_non_empty(works, "theme"),
            "content": _first_non_empty(works, "content"),
            "content_title": _first_non_empty(works, "content_title"),
            "form_name": _first_non_empty(works, "form_name"),
            "avg_total": avg_total,
            "avg_total_pct": normalize(avg_total) if avg_total is not None else None,
            "avg_lang": avg_lang,
            "avg_lang_pct": normalize(avg_lang * 3) if avg_lang is not None else None,
            "avg_logic": avg_logic,
            "avg_logic_pct": normalize(avg_logic * 3) if avg_logic is not None else None,
            "avg_imagery": avg_imagery,
            "avg_imagery_pct": normalize(avg_imagery * 3) if avg_imagery is not None else None,
            "round1_total": round_totals.get("round_1"),
            "round2_total": round_totals.get("round_2"),
            "round_totals": round_totals,
            "used_rounds": [f"round_{round_num}" for round_num in round_nums],
            "used_rounds_count": len(round_nums),
            "hard_flaws": [work.get("hard_flaw", "") for work in works],
        })
    return results


def compute_summary(data):
    summary = {}
    mode_order = [m for m in KNOWN_MODES if any(m in data[model] for model in data)]

    for model in sorted(data.keys()):
        summary[model] = {}
        for mode in mode_order:
            if mode not in data[model]:
                continue
            mode_data = data[model][mode]

            # 唐诗
            tang_avg = None
            tang_lang_avg = None
            tang_logic_avg = None
            tang_imagery_avg = None
            tang_works = []

            if "tang_scores" in mode_data:
                tang_works = average_rounds(mode_data["tang_scores"])
                totals = [w["avg_total"] for w in tang_works if w["avg_total"] is not None]
                langs = [w["avg_lang"] for w in tang_works if w["avg_lang"] is not None]
                logics = [w["avg_logic"] for w in tang_works if w["avg_logic"] is not None]
                imageries = [w["avg_imagery"] for w in tang_works if w["avg_imagery"] is not None]

                if totals:
                    tang_avg = round(sum(totals) / len(totals), 2)
                if langs:
                    tang_lang_avg = round(sum(langs) / len(langs), 2)
                if logics:
                    tang_logic_avg = round(sum(logics) / len(logics), 2)
                if imageries:
                    tang_imagery_avg = round(sum(imageries) / len(imageries), 2)

            # 宋词
            songci_avg = None
            songci_lang_avg = None
            songci_logic_avg = None
            songci_imagery_avg = None
            songci_works = []

            if "songci_scores" in mode_data:
                songci_works = average_rounds(mode_data["songci_scores"])
                totals = [w["avg_total"] for w in songci_works if w["avg_total"] is not None]
                langs = [w["avg_lang"] for w in songci_works if w["avg_lang"] is not None]
                logics = [w["avg_logic"] for w in songci_works if w["avg_logic"] is not None]
                imageries = [w["avg_imagery"] for w in songci_works if w["avg_imagery"] is not None]

                if totals:
                    songci_avg = round(sum(totals) / len(totals), 2)
                if langs:
                    songci_lang_avg = round(sum(langs) / len(langs), 2)
                if logics:
                    songci_logic_avg = round(sum(logics) / len(logics), 2)
                if imageries:
                    songci_imagery_avg = round(sum(imageries) / len(imageries), 2)

            weighted_avg = None
            if tang_avg is not None and songci_avg is not None:
                weighted_avg = round(W_TANG * tang_avg + W_SONGCI * songci_avg, 2)

            w_lang = None
            if tang_lang_avg is not None and songci_lang_avg is not None:
                w_lang = round(W_TANG * tang_lang_avg + W_SONGCI * songci_lang_avg, 2)

            w_logic = None
            if tang_logic_avg is not None and songci_logic_avg is not None:
                w_logic = round(W_TANG * tang_logic_avg + W_SONGCI * songci_logic_avg, 2)

            w_imagery = None
            if tang_imagery_avg is not None and songci_imagery_avg is not None:
                w_imagery = round(W_TANG * tang_imagery_avg + W_SONGCI * songci_imagery_avg, 2)

            summary[model][mode] = {
                "tang": {
                    "avg_total_15": tang_avg,
                    "avg_total_pct": normalize(tang_avg) if tang_avg is not None else None,
                    "avg_lang_5": tang_lang_avg,
                    "avg_logic_5": tang_logic_avg,
                    "avg_imagery_5": tang_imagery_avg,
                    "works_count": len(tang_works),
                },
                "songci": {
                    "avg_total_15": songci_avg,
                    "avg_total_pct": normalize(songci_avg) if songci_avg is not None else None,
                    "avg_lang_5": songci_lang_avg,
                    "avg_logic_5": songci_logic_avg,
                    "avg_imagery_5": songci_imagery_avg,
                    "works_count": len(songci_works),
                },
                "weighted": {
                    "avg_total_15": weighted_avg,
                    "avg_total_pct": normalize(weighted_avg) if weighted_avg is not None else None,
                    "avg_lang_5": w_lang,
                    "avg_logic_5": w_logic,
                    "avg_imagery_5": w_imagery,
                    "formula": f"{W_TANG}*唐诗 + {W_SONGCI}*宋词",
                },
            }

    return summary


def compute_comparison(summary):
    comparison = {}

    for model in sorted(summary.keys()):
        comparison[model] = {}

        for task in ["tang", "songci", "weighted"]:
            c = summary[model].get("constrained_decoding", {}).get(task, {})
            f = summary[model].get("free_decoding", {}).get(task, {})

            c_total = c.get("avg_total_15")
            f_total = f.get("avg_total_15")

            delta = None
            if c_total is not None and f_total is not None:
                delta = round(c_total - f_total, 2)

            comparison[model][task] = {
                "constrained_avg_total_15": c_total,
                "constrained_avg_total_pct": c.get("avg_total_pct"),
                "free_avg_total_15": f_total,
                "free_avg_total_pct": f.get("avg_total_pct"),
                "delta_15": delta,
                "constrained_better": delta > 0 if delta is not None else None,
                "constrained_lang_5": c.get("avg_lang_5"),
                "free_lang_5": f.get("avg_lang_5"),
                "constrained_logic_5": c.get("avg_logic_5"),
                "free_logic_5": f.get("avg_logic_5"),
                "constrained_imagery_5": c.get("avg_imagery_5"),
                "free_imagery_5": f.get("avg_imagery_5"),
            }

    return comparison


def _mode_label(mode):
    return {
        "constrained_decoding": "约束解码",
        "free_decoding": "自由生成",
        "SOTA": "SOTA论文",
    }.get(mode, mode)


def main():
    print("=" * 60)
    print("  LLM 评分汇总工具")
    print("=" * 60)
    print(f"  源目录: {CLEANED_DIR}")
    print(f"  输出目录: {OUTPUT_DIR}")
    print()

    # 1. 收集原始数据
    print("[1/4] 解析大模型评分文件...")
    data = collect_data()

    model_list = sorted(data.keys())
    mode_list = [m for m in KNOWN_MODES if any(m in data[model] for model in model_list)]
    print(f"  模型: {model_list}")
    print(f"  模式: {mode_list}")

    for model in model_list:
        for mode in mode_list:
            if mode in data[model]:
                td = data[model][mode]
                t_count = _format_round_counts(td.get("tang_scores", {}))
                s_count = _format_round_counts(td.get("songci_scores", {}))
                print(f"    {model} / {mode}: 唐诗({t_count}), 宋词({s_count})")

    # 2. 计算汇总
    print("\n[2/4] 计算多轮平均分与汇总...")
    summary = compute_summary(data)

    # 3. 构建对比
    print("[3/4] 构建约束 vs 自由对比...")
    comparison = compute_comparison(summary)

    # 4. 收集逐作品数据
    print("[4/5] 收集逐作品数据...")
    per_works = {}
    for model in model_list:
        per_works[model] = {}
        for mode in mode_list:
            if mode not in data.get(model, {}):
                continue
            per_works[model][mode] = {}
            mode_data = data[model][mode]
            for key, task_label in [("tang_scores", "tang"), ("songci_scores", "songci")]:
                if key in mode_data:
                    per_works[model][mode][task_label] = average_rounds(mode_data[key])

    # 5. 输出 JSON
    print("[5/5] 输出评分 JSON...")
    output = {
        "meta": {
            "description": "基于大模型评分的诗歌质量评估汇总（多轮平均）",
            "scoring_system": "语言(5) + 逻辑(5) + 意境(5) = 总分(15)，归一化百分制 = (得分/15)*100",
            "weight_formula": f"总分 = {W_TANG}*唐诗 + {W_SONGCI}*宋词",
            "models": model_list,
            "modes": {mode: _mode_label(mode) for mode in mode_list},
            "score_counts": build_score_counts(data),
        },
        "summary": summary,
        "comparison": comparison,
        "works": per_works,
    }

    with open(FULL_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  已生成: {FULL_OUTPUT}")

    # 15 分制精简版
    summary_15 = {mode: {} for mode in mode_list}
    for mode in mode_list:
        for model in model_list:
            entry = summary.get(model, {}).get(mode, {})
            tang = entry.get("tang", {})
            songci = entry.get("songci", {})
            weighted = entry.get("weighted", {})

            summary_15[mode][model] = {
                "tang_total_score": tang.get("avg_total_15"),
                "tang_lang_score": tang.get("avg_lang_5"),
                "tang_logic_score": tang.get("avg_logic_5"),
                "tang_imagery_score": tang.get("avg_imagery_5"),
                "tang_works_count": tang.get("works_count", 0),
                "songci_total_score": songci.get("avg_total_15"),
                "songci_lang_score": songci.get("avg_lang_5"),
                "songci_logic_score": songci.get("avg_logic_5"),
                "songci_imagery_score": songci.get("avg_imagery_5"),
                "songci_works_count": songci.get("works_count", 0),
                "weighted_total_score": weighted.get("avg_total_15"),
                "weight_formula": f"{W_TANG}*tang + {W_SONGCI}*songci",
            }

    with open(COMPACT_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(summary_15, f, ensure_ascii=False, indent=2)

    print(f"  已生成: {COMPACT_OUTPUT}")

    # 快速摘要
    print("\n" + "=" * 60)
    print("  快速摘要（15 分制）")
    print("=" * 60)
    for mode in mode_list:
        label = _mode_label(mode)
        print(f"\n  [{label}]")
        for model in model_list:
            e = summary_15[mode].get(model, {})
            w = e.get("weighted_total_score", "N/A")
            t = e.get("tang_total_score", "N/A")
            s = e.get("songci_total_score", "N/A")
            tl = e.get("tang_lang_score", "N/A")
            sl = e.get("songci_lang_score", "N/A")
            print(f"    {model}: 加权={w}, 唐诗={t}(语{tl}), 宋词={s}(语{sl})")

    print("\n  完成!")


if __name__ == "__main__":
    main()
