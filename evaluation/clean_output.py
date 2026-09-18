#!/usr/bin/env python3
"""
清洗 raw/ 中的原始生成数据，按 (模型, 体裁) 合并输出到 cleaned/。
"""

import os
import re
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
CLEAN_DIR = os.path.join(BASE_DIR, "cleaned")

# 唐诗 forms
TANGSHI_FORMS = {"五绝", "七绝", "五律", "七律"}
# 宋词 forms (词牌名)
SONGCI_FORMS = {"南乡子", "桂枝香", "水调歌头", "浣溪沙", "渔家傲", "谢池春"}
ALL_FORMS = TANGSHI_FORMS | SONGCI_FORMS
FORM_PATTERN = "|".join(re.escape(form) for form in sorted(ALL_FORMS, key=len, reverse=True))
FILENAME_RE = re.compile(
    rf"^(?P<model>.+?)-(?P<prompt>\([^)]*\)|[^-]+)-(?P<form>{FORM_PATTERN})-(?P<theme>.+)$"
)


def classify_category(form):
    if form in TANGSHI_FORMS:
        return "唐诗"
    elif form in SONGCI_FORMS:
        return "宋词"
    else:
        return None


def parse_filename(filename):
    name, ext = os.path.splitext(filename)
    if ext.lower() != ".txt":
        return None, None, None, None

    match = FILENAME_RE.match(name)
    if match:
        return match.group("model"), match.group("prompt"), match.group("form"), match.group("theme")

    parts = name.split("-")
    for idx in range(len(parts) - 2, -1, -1):
        form = parts[idx]
        if form not in ALL_FORMS:
            continue
        if idx < 2:
            break
        model_name = "-".join(parts[: idx - 1])
        prompt_tag = parts[idx - 1]
        theme = "-".join(parts[idx + 1 :])
        if not model_name or not prompt_tag or not theme:
            break
        return model_name, prompt_tag, form, theme

    return None, None, None, None


def extract_works(content):
    works = []
    blocks = re.split(r'=== 作品 \d+ ===', content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        title_match = re.search(r'\[title](.+?)(?:\n|$)', block)
        if not title_match:
            title_match = re.search(r'\*\*\[title](.+?)\*\*', block)
        if not title_match:
            title_match = re.search(r'\[title](.+)', block)

        content_match = re.search(
            r'\[content](.+?)(?=== 作品|\Z)', block, re.DOTALL
        )
        if not content_match:
            content_match = re.search(
                r'\*\*\[content](.+?)\*\*(?=== 作品|\Z)', block, re.DOTALL
            )
        if not content_match:
            content_match = re.search(
                r'\[content](.+?)\Z', block, re.DOTALL
            )

        if title_match and content_match:
            title = title_match.group(1).strip().strip("*").strip()
            content_text = content_match.group(1).strip().strip("*").strip()
            works.append((title, content_text))

    return works


def process_files():
    os.makedirs(CLEAN_DIR, exist_ok=True)

    for mode in ["constrained_decoding", "free_decoding"]:
        mode_dir = os.path.join(RAW_DIR, mode)
        if not os.path.exists(mode_dir):
            continue

        clean_mode_dir = os.path.join(CLEAN_DIR, mode)
        os.makedirs(clean_mode_dir, exist_ok=True)

        grouped = defaultdict(list)

        for filename in sorted(os.listdir(mode_dir)):
            if not filename.endswith(".txt"):
                continue

            model_name, prompt_tag, form, theme = parse_filename(filename)
            if not model_name:
                print(f"Warning: cannot parse filename '{filename}'")
                continue
            category = classify_category(form)
            if category is None:
                print(f"Warning: cannot classify form '{form}' in {filename}")
                continue

            filepath = os.path.join(mode_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                file_content = f.read()

            works = extract_works(file_content)
            for title, content_text in works:
                grouped[(model_name, category)].append(
                    (theme, title, content_text)
                )

        for (model_name, category), works_list in sorted(grouped.items()):
            output_filename = f"{model_name}-{category}.txt"
            output_path = os.path.join(clean_mode_dir, output_filename)

            with open(output_path, "w", encoding="utf-8") as f:
                for i, (theme, title, content_text) in enumerate(works_list):
                    f.write(f"主题：{theme}\n")
                    f.write(f"作品名：{title}\n")
                    f.write(f"内容：\n{content_text}\n")
                    if i < len(works_list) - 1:
                        f.write("========================================\n")

            print(f"Written: {output_path} ({len(works_list)} works)")

    print("Done!")


if __name__ == "__main__":
    process_files()
