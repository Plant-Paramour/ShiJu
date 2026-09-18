#!/usr/bin/env python3
"""对比约束 vs 自由生成：每个任务平均后求差值，输出 CSV。"""

import csv
import os
from collections import defaultdict

INPUT_CSV = "csv/per_work_detail.csv"
OUTPUT_CSV = "csv/constraint_vs_free_diff.csv"


def safe_float(value):
    """安全转换为浮点数，处理 None、空字符串、非数字等"""
    if value is None or value == "" or value.strip() == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, INPUT_CSV)
    output_path = os.path.join(script_dir, OUTPUT_CSV)

    # 检查输入文件是否存在
    if not os.path.exists(input_path):
        print(f"错误：输入文件不存在 {input_path}")
        return

    # 读取所有行
    rows = []
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # 获取所有字段名，用于后续检查
        fieldnames = reader.fieldnames
        for r in reader:
            rows.append(r)

    if not rows:
        print("警告：输入文件为空")
        return

    # 分组：(模型, 体裁, 主题, 是否约束) → [语言分数列表, 逻辑分数列表, ...]
    groups = defaultdict(lambda: {
        "语言": [], "逻辑": [], "意境": [], "写作总分": [],
    })

    # 统计跳过的行数
    skipped_rows = 0

    for r in rows:
        # 安全获取关键字段，去除空白
        model = r.get("模型", "").strip()
        form = r.get("体裁", "").strip()
        theme = r.get("主题", "").strip()
        constraint = r.get("是否约束", "").strip()

        # 如果关键字段为空，跳过该行
        if not all([model, form, theme, constraint]):
            skipped_rows += 1
            continue

        key = (model, form, theme, constraint)

        # 安全转换各分数
        scores = {}
        for dim in ["语言分数", "逻辑分数", "意境分数", "写作总分"]:
            # 尝试获取字段值，处理字段不存在的情况
            value = r.get(dim, "")
            scores[dim] = safe_float(value)

        # 检查是否所有分数都有效
        if any(v is None for v in scores.values()):
            skipped_rows += 1
            continue

        # 添加有效数据
        groups[key]["语言"].append(scores["语言分数"])
        groups[key]["逻辑"].append(scores["逻辑分数"])
        groups[key]["意境"].append(scores["意境分数"])
        groups[key]["写作总分"].append(scores["写作总分"])

    if skipped_rows > 0:
        print(f"注意：跳过 {skipped_rows} 行（数据不完整或格式错误）")

    if not groups:
        print("错误：没有有效数据可处理")
        return

    # 计算每组的平均分
    avg_scores = {}
    for key, scores in groups.items():
        avg_scores[key] = {}
        for dim, vals in scores.items():
            if vals:  # 确保列表不为空
                avg_scores[key][dim] = sum(vals) / len(vals)
            else:
                avg_scores[key][dim] = 0.0

    # 按 (模型, 体裁, 主题) 配对约束和自由，计算差值
    tasks = defaultdict(dict)
    for (model, form, theme, constraint), scores in avg_scores.items():
        tasks[(model, form, theme)][constraint] = scores

    # 生成 CSV
    output_rows = []
    for (model, form, theme) in sorted(tasks.keys()):
        pair = tasks[(model, form, theme)]

        # 检查是否同时有约束和自由的数据
        if "是" not in pair or "否" not in pair:
            continue

        c = pair["是"]
        f = pair["否"]

        def fmt_diff(dim):
            # 确保维度存在
            c_val = c.get(dim, 0.0)
            f_val = f.get(dim, 0.0)
            diff = c_val - f_val
            sign = "+" if diff >= 0 else ""
            return f"{sign}{diff:.2f}"

        output_rows.append({
            "模型": model,
            "体裁-主题": f"{form}-{theme}",
            "语言(提升)": fmt_diff("语言"),
            "逻辑(提升)": fmt_diff("逻辑"),
            "意境(提升)": fmt_diff("意境"),
            "写作总分(提升)": fmt_diff("写作总分"),
        })

    if not output_rows:
        print("警告：没有生成任何数据行（可能缺少约束或自由的配对数据）")
        return

    # 写 CSV
    fieldnames = ["模型", "体裁-主题", "语言(提升)", "逻辑(提升)", "意境(提升)", "写作总分(提升)"]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"生成完成：{len(output_rows)} 行 → {output_path}")

    # 打印前 5 行预览
    print("\n预览（前 5 行）：")
    for row in output_rows[:5]:
        print(
            f"  {row['模型']} | {row['体裁-主题']} | {row['语言(提升)']} | {row['逻辑(提升)']} | {row['意境(提升)']} | {row['写作总分(提升)']}")


if __name__ == "__main__":
    main()