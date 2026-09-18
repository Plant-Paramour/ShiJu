#!/usr/bin/env python3
"""
Classical Chinese Poetry Evaluator — pypinyin 规则评分（宋词 + 唐诗）。
评分体系：结构 40% + 平仄 30% + 押韵 30%，基于中华新韵。
"""

import json
import os
import re
import sys
import io
import shutil
from collections import Counter, defaultdict
from pypinyin import pinyin, Style
from tqdm import tqdm

# ============================================================
#  Shared utilities — pypinyin-based tone & rhyme (中华新韵)
# ============================================================

_XINYUN_FINAL_MAP = {
    'a': '一麻', 'ia': '一麻', 'ua': '一麻',
    'o': '二波', 'e': '二波', 'uo': '二波',
    'ie': '三皆', 'ue': '三皆',
    'ai': '四开', 'uai': '四开',
    'ei': '五微', 'ui': '五微', 'uei': '五微',
    'ao': '六豪', 'iao': '六豪',
    'ou': '七尤', 'iu': '七尤', 'iou': '七尤',
    'an': '八寒', 'ian': '八寒', 'uan': '八寒', 'van': '八寒',
    'en': '九文', 'in': '九文', 'un': '九文', 'uen': '九文', 'vn': '九文',
    'ang': '十唐', 'iang': '十唐', 'uang': '十唐',
    'eng': '十一庚', 'ing': '十一庚', 'ong': '十一庚',
    'iong': '十一庚', 'ueng': '十一庚',
    'er': '十二齐',
    'v': '十二齐',
    've': '三皆',
}

_ZHI_INITIALS = {'zh', 'ch', 'sh', 'r', 'z', 'c', 's'}
_JU_INITIALS = {'j', 'q', 'x', 'y'}


def get_char_tone(char):
    try:
        tone_char = pinyin(char, style=Style.TONE3, heteronym=False)[0][0][-1]
        if tone_char in '12':
            return '平'
        elif tone_char in '34':
            return '仄'
        return '中'
    except (IndexError, TypeError):
        return '中'


def get_char_rhyme(char):
    try:
        all_finals = pinyin(char, style=Style.FINALS, heteronym=True)[0]
        all_initials = pinyin(char, style=Style.INITIALS, heteronym=True)[0]
        if not all_finals:
            return frozenset({'none'})
    except (IndexError, TypeError):
        return frozenset({'none'})

    categories = set()
    for i, final in enumerate(all_finals):
        initial = all_initials[i] if i < len(all_initials) else (all_initials[0] if all_initials else '')

        if not final:
            continue

        if final == 'i':
            if initial in _ZHI_INITIALS:
                categories.add('十三支')
            else:
                categories.add('十二齐')
        elif final == 'u':
            if initial in _JU_INITIALS:
                categories.add('十二齐')
            else:
                categories.add('十四姑')
        else:
            category = _XINYUN_FINAL_MAP.get(final)
            if category:
                categories.add(category)

    return frozenset(categories) if categories else frozenset({'none'})


def _parse_poem_lines(text):
    lines = re.split(r'[，,。.！!？?、；;\n\r]+', text.strip())
    return [line.strip() for line in lines if line.strip()]


def extract_poem_text(raw_output):
    m = re.search(r'\[content\]\s*(.+)', raw_output, re.DOTALL)
    if m:
        text = m.group(1).strip()
        return text if text else None
    return None


# ============================================================
#  SongciEvaluator (宋词)
# ============================================================

class SongciEvaluator:
    def __init__(self, meter_path):
        self.meters = {}
        if os.path.isdir(meter_path):
            for filename in os.listdir(meter_path):
                if filename.endswith('.json'):
                    filepath = os.path.join(meter_path, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    name = data.get('name') or filename.replace('.json', '')
                    variants = data.get('variants', [])
                    if variants:
                        self.meters[name] = variants[0]
        else:
            with open(meter_path, 'r', encoding='utf-8') as f:
                self.meters = json.load(f)

    def _build_total_view(self, meter_entry):
        chars_per_line = []
        rhyme_groups = []
        tonal_patterns = []
        expanded_offset = 0

        for stanza_key in ['stanza1', 'stanza2']:
            stanza = meter_entry.get(stanza_key)
            if not stanza:
                continue

            stanza_lines = stanza.get('lines', [])
            line_to_subclauses = []

            for tonal_line in stanza_lines:
                sub_clauses = tonal_line.split('、')
                sub_indices = []
                for sub in sub_clauses:
                    cleaned = re.sub(r'[/\s]', '', sub)
                    if cleaned:
                        chars_per_line.append(len(cleaned))
                        tonal_patterns.append(cleaned)
                        sub_indices.append(expanded_offset)
                        expanded_offset += 1
                line_to_subclauses.append(sub_indices)

            for key in sorted(stanza):
                if key.startswith('rhyme_') and key.endswith('_positions'):
                    group_positions = []
                    for pos in stanza[key]:
                        line_idx = pos - 1
                        if line_idx < len(line_to_subclauses):
                            sub_indices = line_to_subclauses[line_idx]
                            if sub_indices:
                                group_positions.append(sub_indices[-1] + 1)
                    if group_positions:
                        rhyme_groups.append(group_positions)

        return {
            'chars_per_line': chars_per_line,
            'rhyme_groups': rhyme_groups,
            'tonal_patterns': tonal_patterns,
        }

    def _get_template_line_count(self, meter_entry):
        count = 0
        for stanza_key in ['stanza1', 'stanza2']:
            stanza = meter_entry.get(stanza_key)
            if stanza:
                for tonal_line in stanza.get('lines', []):
                    count += len([c for c in tonal_line.split('、') if re.sub(r'[/\s]', '', c)])
        return count

    def _calculate_score(self, generated_lines, meter_entry):
        scores = {"structure": 0.0, "tonal": 0.0, "rhyme": 0.0}
        details = {"structure": {}, "tonal": {}, "rhyme": {}}
        total = self._build_total_view(meter_entry)

        template_chars = total['chars_per_line']
        tonal_patterns = total['tonal_patterns']
        rhyme_groups = total['rhyme_groups']

        if not template_chars:
            return scores, details

        n_template = len(template_chars)
        n_generated = len(generated_lines)
        n_common = min(n_template, n_generated)

        # --- 1. Structure Score (40%) ---
        if n_template > 0:
            mismatches = []
            for i in range(n_common):
                actual_len = len(generated_lines[i])
                expected_len = template_chars[i]
                if actual_len != expected_len:
                    mismatches.append({
                        "clause_index": i,
                        "clause": generated_lines[i],
                        "actual_len": actual_len,
                        "expected_len": expected_len,
                    })
            correct = n_common - len(mismatches)
            scores['structure'] = correct / n_template
            details['structure'] = {
                "mismatches": mismatches,
                "missing_template_clauses": n_template - n_common if n_template > n_generated else 0,
                "extra_generated_clauses": n_generated - n_common if n_generated > n_template else 0,
            }

        # --- 2. Tonal Score (30%) ---
        tonal_mismatches = []
        skipped_clauses = []
        total_chars, matching_chars = 0, 0
        if tonal_patterns:
            for i in range(n_common):
                if i >= len(tonal_patterns):
                    break
                pattern = tonal_patterns[i]
                clause = generated_lines[i]
                if len(clause) != len(pattern):
                    skipped_clauses.append({
                        "clause_index": i,
                        "clause": clause,
                        "reason": f"length mismatch (clause:{len(clause)} vs pattern:{len(pattern)})",
                    })
                    continue
                clause_mismatches = []
                for j, char in enumerate(clause):
                    required = pattern[j]
                    actual = get_char_tone(char)
                    total_chars += 1
                    if required == '中' or actual == required:
                        matching_chars += 1
                    else:
                        clause_mismatches.append({
                            "char": char,
                            "position_in_clause": j,
                            "required_tone": required,
                            "actual_tone": actual,
                        })
                if clause_mismatches:
                    tonal_mismatches.append({
                        "clause_index": i,
                        "clause": clause,
                        "pattern": pattern,
                        "mismatches": clause_mismatches,
                        "mismatch_count": len(clause_mismatches),
                        "clause_total_chars": len(clause),
                    })
            if total_chars > 0:
                scores['tonal'] = matching_chars / total_chars
            details['tonal'] = {
                "mismatches": tonal_mismatches,
                "skipped_clauses": skipped_clauses,
                "total_match_count": matching_chars,
                "total_char_count": total_chars,
            }

        # --- 3. Rhyme Score (30%) ---
        if rhyme_groups:
            group_results = []
            for group in rhyme_groups:
                chars = []
                char_category_sets = []
                group_xinyun_map = {}
                for pos in group:
                    idx = pos - 1
                    if idx < n_generated and generated_lines[idx]:
                        char = generated_lines[idx][-1]
                        chars.append(char)
                        cat_set = get_char_rhyme(char)
                        char_category_sets.append(cat_set)
                        for cat in cat_set:
                            if cat != 'none':
                                group_xinyun_map.setdefault(cat, []).append({
                                    "position": pos,
                                    "char": char,
                                })

                if not chars:
                    continue

                category_counts = Counter()
                for cat_set in char_category_sets:
                    for cat in cat_set:
                        if cat != 'none':
                            category_counts[cat] += 1

                if category_counts:
                    dominant = category_counts.most_common(1)[0]
                    group_score = dominant[1] / len(chars)
                else:
                    dominant = (None, 0)
                    group_score = 0.0

                group_results.append({
                    "positions": group,
                    "chars": chars,
                    "xinyun_map": group_xinyun_map,
                    "dominant_xinyun": dominant[0],
                    "match_count": dominant[1],
                    "total_count": len(chars),
                    "group_score": round(group_score, 4),
                })

            if group_results:
                scores['rhyme'] = sum(g["group_score"] for g in group_results) / len(group_results)
                details['rhyme'] = {
                    "groups": group_results,
                    "num_groups": len(group_results),
                    "average_group_score": round(scores['rhyme'], 4),
                }
            else:
                details['rhyme'] = {
                    "groups": [],
                    "num_groups": 0,
                    "average_group_score": 0.0,
                }

        return scores, details

    def evaluate(self, cipai, output):
        generated_lines = _parse_poem_lines(output)
        meter_entry = self.meters.get(cipai)

        if not meter_entry:
            return {
                "error": f"Cipai '{cipai}' not found in meter data.",
                "total_score_percentage": 0.0,
            }

        component_scores, score_details = self._calculate_score(generated_lines, meter_entry)
        weights = {"S": 0.4, "T": 0.3, "R": 0.3}
        total_score = (
            weights["S"] * component_scores["structure"]
            + weights["T"] * component_scores["tonal"]
            + weights["R"] * component_scores["rhyme"]
        )

        return {
            "cipai": cipai,
            "variant": meter_entry.get("variant", ""),
            "rhyme_type": meter_entry.get("rhyme_type", ""),
            "length_category": meter_entry.get("length_category", ""),
            "total_score_percentage": round(total_score * 100, 2),
            "structure_score_percentage": round(component_scores["structure"] * 100, 2),
            "tonal_score_percentage": round(component_scores["tonal"] * 100, 2),
            "rhyme_score_percentage": round(component_scores["rhyme"] * 100, 2),
            "parsed_clauses": generated_lines,
            "parsed_clause_count": len(generated_lines),
            "template_line_count": self._get_template_line_count(meter_entry),
            "scoring_details": {
                "structure": score_details.get("structure", {}),
                "tonal": score_details.get("tonal", {}),
                "rhyme": score_details.get("rhyme", {}),
            },
        }


# ============================================================
#  TangPoemEvaluator (唐诗)
# ============================================================

class TangPoemEvaluator:
    def __init__(self):
        pass

    def _determine_poem_type(self, lines):
        if not lines:
            return 0, 0, "未知"

        lens = [len(l) for l in lines if len(l) in (5, 7)]
        if not lens:
            return 0, 0, "未知"

        char_count = max(set(lens), key=lens.count)
        n_lines = len(lines)

        type_map = {
            (5, 4): "五言绝句",
            (5, 8): "五言律诗",
            (7, 4): "七言绝句",
            (7, 8): "七言律诗",
        }
        type_name = type_map.get((char_count, n_lines),
                                 f"{char_count}言{n_lines}句")
        return char_count, n_lines, type_name

    def _detect_rhyme_type(self, lines):
        ping_count = 0
        ze_count = 0
        for i, line in enumerate(lines):
            if (i + 1) % 2 == 0 and line:
                t = get_char_tone(line[-1])
                if t == '平':
                    ping_count += 1
                elif t == '仄':
                    ze_count += 1
        return "平韵" if ping_count >= ze_count else "仄韵"

    def _evaluate_tonal_rules(self, lines, char_count):
        violations = set()
        details = {
            "二四六分明": [],
            "三连同": [],
            "孤平": [],
            "末字收束": [],
        }

        is_ping_yun = "平" in self._detect_rhyme_type(lines)

        global_base_tone = 2
        if len(lines) > 0 and len(lines[0]) >= 2:
            t = get_char_tone(lines[0][1])
            if t in ('平', '仄'):
                global_base_tone = 0 if t == '平' else 1

        for line_idx, line in enumerate(lines):
            if len(line) != char_count:
                continue

            if global_base_tone != 2:
                if line_idx in (1, 2, 5, 6):
                    line_base_tone = 1 - global_base_tone
                else:
                    line_base_tone = global_base_tone
            else:
                line_base_tone = 2

            # 二四六分明
            if line_base_tone != 2:
                if len(line) >= 2:
                    actual = get_char_tone(line[1])
                    if actual in ('平', '仄'):
                        expected = '平' if line_base_tone == 0 else '仄'
                        if actual != expected:
                            violations.add((line_idx, 1))
                            details["二四六分明"].append({
                                "line": line_idx + 1, "pos": 2,
                                "char": line[1],
                                "expected": expected, "actual": actual,
                            })

                if len(line) >= 4:
                    actual = get_char_tone(line[3])
                    if actual in ('平', '仄'):
                        expected = '仄' if line_base_tone == 0 else '平'
                        if actual != expected:
                            violations.add((line_idx, 3))
                            details["二四六分明"].append({
                                "line": line_idx + 1, "pos": 4,
                                "char": line[3],
                                "expected": expected, "actual": actual,
                            })

                if char_count >= 7 and len(line) >= 6:
                    actual = get_char_tone(line[5])
                    if actual in ('平', '仄'):
                        expected = '平' if line_base_tone == 0 else '仄'
                        if actual != expected:
                            violations.add((line_idx, 5))
                            details["二四六分明"].append({
                                "line": line_idx + 1, "pos": 6,
                                "char": line[5],
                                "expected": expected, "actual": actual,
                            })

            # 三连同
            if len(line) >= 3:
                last3 = line[-3:]
                t0 = get_char_tone(last3[0])
                t1 = get_char_tone(last3[1])
                t2 = get_char_tone(last3[2])
                if t0 in ('平', '仄') and t0 == t1 == t2:
                    violations.add((line_idx, len(line) - 1))
                    details["三连同"].append({
                        "line": line_idx + 1,
                        "chars": last3, "tone": t0,
                    })

            # 孤平
            if len(line) >= 3:
                last_tone = get_char_tone(line[-1])
                if last_tone == '平' and line_base_tone != 2:
                    if line_base_tone == 0:
                        if len(line) >= 3:
                            pz0 = get_char_tone(line[0])
                            pz2 = get_char_tone(line[2])
                            if pz0 == '仄' and pz2 == '仄':
                                violations.add((line_idx, 1))
                                details["孤平"].append({
                                    "line": line_idx + 1,
                                    "type": "平起式", "isolated_pos": 2,
                                    "chars": line[:3],
                                })
                    else:
                        if len(line) >= 5:
                            pz2 = get_char_tone(line[2])
                            pz4 = get_char_tone(line[4])
                            if pz2 == '仄' and pz4 == '仄':
                                violations.add((line_idx, 3))
                                details["孤平"].append({
                                    "line": line_idx + 1,
                                    "type": "仄起式", "isolated_pos": 4,
                                    "chars": line[2:5],
                                })

            # 末字收束
            if len(line) >= 1:
                is_even = (line_idx + 1) % 2 == 0
                is_first = (line_idx == 0)

                if is_even:
                    expected = '平' if is_ping_yun else '仄'
                    actual = get_char_tone(line[-1])
                    if actual in ('平', '仄') and actual != expected:
                        violations.add((line_idx, len(line) - 1))
                        details["末字收束"].append({
                            "line": line_idx + 1, "char": line[-1],
                            "reason": f"偶句应为{expected}收",
                            "actual": actual,
                        })
                elif not is_first:
                    expected = '仄' if is_ping_yun else '平'
                    actual = get_char_tone(line[-1])
                    if actual in ('平', '仄') and actual != expected:
                        violations.add((line_idx, len(line) - 1))
                        details["末字收束"].append({
                            "line": line_idx + 1, "char": line[-1],
                            "reason": f"奇句应为{expected}收",
                            "actual": actual,
                        })

        total_chars = sum(len(l) for l in lines if len(l) == char_count)
        score = (total_chars - len(violations)) / max(total_chars, 1)
        return score, violations, details

    def evaluate(self, poem_text):
        lines = _parse_poem_lines(poem_text)
        char_count, num_lines, type_name = self._determine_poem_type(lines)

        if char_count == 0:
            return {
                "error": "Cannot determine poem type from text.",
                "poem_type": type_name,
                "total_score_percentage": 0.0,
            }

        n_generated = len(lines)

        # Structure Score (40%)
        structure_mismatches = []
        for i, line in enumerate(lines):
            if len(line) != char_count:
                structure_mismatches.append({
                    "line_index": i, "line": line,
                    "actual_len": len(line), "expected_len": char_count,
                })
        structure_score = (n_generated - len(structure_mismatches)) / max(n_generated, 1)
        if n_generated != num_lines:
            structure_score = min(structure_score, 0.5)

        # Tonal Score (30%)
        tonal_score, violation_set, tonal_details = self._evaluate_tonal_rules(
            lines, char_count)
        total_tonal_chars = sum(len(l) for l in lines if len(l) == char_count)
        matching_tonal_chars = total_tonal_chars - len(violation_set)

        # Rhyme Score (30%)
        is_ping_yun = "平" in self._detect_rhyme_type(lines)

        rhyme_positions = []
        for i in range(n_generated):
            if (i + 1) % 2 == 0:
                rhyme_positions.append(i + 1)
        if lines and lines[0]:
            flt = get_char_tone(lines[0][-1])
            if flt == ('平' if is_ping_yun else '仄'):
                rhyme_positions.insert(0, 1)

        rhyme_chars = []
        rhyme_category_sets = []
        rhyme_xinyun_map = {}
        for pos in rhyme_positions:
            idx = pos - 1
            if idx < n_generated and lines[idx]:
                char = lines[idx][-1]
                rhyme_chars.append(char)
                cat_set = get_char_rhyme(char)
                rhyme_category_sets.append(cat_set)
                for cat in cat_set:
                    if cat != 'none':
                        rhyme_xinyun_map.setdefault(cat, []).append({
                            "position": pos, "char": char,
                        })

        if rhyme_chars:
            category_counts = Counter()
            for cat_set in rhyme_category_sets:
                for cat in cat_set:
                    if cat != 'none':
                        category_counts[cat] += 1

            if category_counts:
                dominant = category_counts.most_common(1)[0]
                rhyme_score = dominant[1] / len(rhyme_chars)
            else:
                dominant = (None, 0)
                rhyme_score = 0.0

            rhyme_details = {
                "rhyme_type": "平韵" if is_ping_yun else "仄韵",
                "rhyme_positions": rhyme_positions,
                "chars": rhyme_chars,
                "dominant_xinyun": dominant[0],
                "match_count": dominant[1],
                "total_count": len(rhyme_chars),
                "group_score": round(rhyme_score, 4),
            }
        else:
            rhyme_score = 0.0
            rhyme_details = {"rhyme_positions": [], "group_score": 0.0}

        weights = {"S": 0.4, "T": 0.3, "R": 0.3}
        total_score = (
            weights["S"] * structure_score
            + weights["T"] * tonal_score
            + weights["R"] * rhyme_score
        )

        qishi = "未定"
        if lines and len(lines[0]) >= 2:
            t = get_char_tone(lines[0][1])
            if t == '平':
                qishi = "平起"
            elif t == '仄':
                qishi = "仄起"

        return {
            "poem_type": type_name,
            "char_count": char_count,
            "detected_lines": num_lines,
            "actual_lines": n_generated,
            "detected_qishi": qishi,
            "detected_rhyme_type": "平韵" if is_ping_yun else "仄韵",
            "total_score_percentage": round(total_score * 100, 2),
            "structure_score_percentage": round(structure_score * 100, 2),
            "tonal_score_percentage": round(tonal_score * 100, 2),
            "rhyme_score_percentage": round(rhyme_score * 100, 2),
            "parsed_lines": lines,
            "parsed_line_count": n_generated,
            "tonal_violation_count": len(violation_set),
            "tonal_total_chars": total_tonal_chars,
            "tonal_matching_chars": matching_tonal_chars,
            "scoring_details": {
                "structure": {
                    "mismatches": structure_mismatches,
                    "expected_chars_per_line": char_count,
                    "expected_lines": num_lines,
                },
                "tonal": {
                    "total_chars": total_tonal_chars,
                    "violation_count": len(violation_set),
                    "matching_chars": matching_tonal_chars,
                    "violations_by_rule": {
                        rule: items
                        for rule, items in tonal_details.items()
                        if items
                    },
                },
                "rhyme": rhyme_details,
            },
        }


# ============================================================
#  Filename parsing & classification
# ============================================================

TANG_FORMS = {'七律', '七绝', '五律', '五绝'}
SOTA_MODEL_ALIASES = {
    'shisanbai': '诗三百',
}
CLEANED_FILE_RE = re.compile(r'^(.+?)-(唐诗|宋词)\.txt$')


def parse_filename(filename):
    base = filename.replace('.txt', '').strip()
    m = re.match(r'^(.+?)-\((.+?)\)-(.+)-(.+)$', base)
    if m:
        return {
            'model': m.group(1),
            'task_type': m.group(2),
            'form_name': m.group(3),
            'theme': m.group(4),
        }
    return None


def _strip_poem_title_prefix(title):
    title = (title or '').strip()
    if '·' in title:
        title = title.split('·', 1)[1].strip()
    title = re.sub(r'[（(]其[一二三四五六七八九十]+[)）]$', '', title).strip()
    return title


def classify_form(form_name):
    return 'tang' if form_name in TANG_FORMS else 'songci'


def parse_cleaned_filename(filename):
    match = CLEANED_FILE_RE.match(filename)
    if not match:
        return None
    return {
        'model': match.group(1),
        'category': match.group(2),
        'form_type': 'tang' if match.group(2) == '唐诗' else 'songci',
    }


def _parse_cleaned_works(raw_text):
    works = []
    for block in raw_text.strip().split("========================================"):
        block = block.strip()
        if not block:
            continue

        theme_m = re.search(r"主题[：:]\s*(.+)", block)
        title_m = re.search(r"作品名[：:]\s*(.+)", block)
        content_m = re.search(r"内容[：:]\s*\n(.+)", block, re.DOTALL)
        if not content_m:
            continue

        works.append({
            "theme": theme_m.group(1).strip() if theme_m else "",
            "title": title_m.group(1).strip() if title_m else "",
            "content": content_m.group(1).strip(),
        })
    return works


def _title_prefix(title):
    title = (title or "").strip()
    return title.split("·", 1)[0].strip() if "·" in title else title


def _infer_tang_form(title, poem_text):
    prefix = _title_prefix(title)
    if prefix in TANG_FORMS:
        return prefix

    lines = _parse_poem_lines(poem_text)
    line_count = len(lines)
    lengths = [len(re.sub(r"\s+", "", line)) for line in lines if line.strip()]
    common_length = Counter(lengths).most_common(1)[0][0] if lengths else 0

    if line_count <= 4:
        return "五绝" if common_length <= 5 else "七绝"
    return "五律" if common_length <= 5 else "七律"


def _infer_cleaned_form(work, form_type, songci_evaluator):
    title = work.get("title", "")
    content = work.get("content", "")
    prefix = _title_prefix(title)

    if form_type == "tang":
        return _infer_tang_form(title, content)
    if songci_evaluator and prefix in songci_evaluator.meters:
        return prefix
    return prefix


def _collect_input_files(input_dir):
    files = []
    if not os.path.isdir(input_dir):
        return files
    for root, _dirs, filenames in os.walk(input_dir):
        for fn in filenames:
            if fn.endswith('.txt') and '评分(' not in fn:
                files.append(os.path.join(root, fn))
    return files


def _reset_mode_output_dir(mode_output_dir):
    if os.path.isdir(mode_output_dir):
        shutil.rmtree(mode_output_dir)
    os.makedirs(mode_output_dir, exist_ok=True)


# ============================================================
#  Unified batch evaluation
# ============================================================

def _process_one_file(filepath, songci_evaluator, tang_evaluator):
    filename = os.path.basename(filepath)
    info = parse_filename(filename)

    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    works = re.split(r'===+\s*作品\s*\d*\s*===+', raw_text)
    if len(works) <= 1:
        works = [raw_text]

    poem_results = []
    total_sum = structure_sum = tonal_sum = rhyme_sum = 0.0
    poem_count = 0

    if info is None:
        return None

    form_name = info['form_name']
    form_type = classify_form(form_name)

    for i, work in enumerate(works):
        work = work.strip()
        if not work:
            continue
        poem_text = extract_poem_text(work)
        if not poem_text:
            continue

        if form_type == 'songci' and songci_evaluator:
            ev = songci_evaluator.evaluate(form_name, poem_text)
        elif form_type == 'tang' and tang_evaluator:
            ev = tang_evaluator.evaluate(poem_text)
        else:
            continue

        poem_results.append({
            "work_index": i,
            "poem_text": poem_text,
            "evaluation": ev,
        })

        if "error" not in ev:
            total_sum += ev.get("total_score_percentage", 0)
            structure_sum += ev.get("structure_score_percentage", 0)
            tonal_sum += ev.get("tonal_score_percentage", 0)
            rhyme_sum += ev.get("rhyme_score_percentage", 0)
            poem_count += 1

    avg_scores = {}
    if poem_count > 0:
        avg_scores = {
            "average_total_score": round(total_sum / poem_count, 2),
            "average_structure_score": round(structure_sum / poem_count, 2),
            "average_tonal_score": round(tonal_sum / poem_count, 2),
            "average_rhyme_score": round(rhyme_sum / poem_count, 2),
        }

    return {
        "source_file": filename,
        "model": info['model'],
        "task_type": info['task_type'],
        "form_name": form_name,
        "form_type": form_type,
        "theme": info['theme'],
        "works_evaluated": poem_count,
        "average_scores": avg_scores,
        "individual_results": poem_results,
    }


def _process_cleaned_file(filepath, mode_name, songci_evaluator, tang_evaluator):
    filename = os.path.basename(filepath)
    info = parse_cleaned_filename(filename)
    if info is None:
        return []

    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    grouped = defaultdict(list)
    for work in _parse_cleaned_works(raw_text):
        form_name = _infer_cleaned_form(work, info['form_type'], songci_evaluator)
        grouped[(form_name, work.get("theme", ""))].append(work)

    results = []
    for (form_name, theme), works in sorted(grouped.items()):
        form_type = info['form_type']
        poem_results = []
        total_sum = structure_sum = tonal_sum = rhyme_sum = 0.0
        poem_count = 0

        for i, work in enumerate(works):
            poem_text = work.get("content", "").strip()
            if not poem_text:
                continue

            if form_type == 'songci' and songci_evaluator:
                ev = songci_evaluator.evaluate(form_name, poem_text)
            elif form_type == 'tang' and tang_evaluator:
                ev = tang_evaluator.evaluate(poem_text)
            else:
                continue

            poem_results.append({
                "work_index": i,
                "poem_text": poem_text,
                "title": work.get("title", ""),
                "theme": theme,
                "evaluation": ev,
            })

            if "error" not in ev:
                total_sum += ev.get("total_score_percentage", 0)
                structure_sum += ev.get("structure_score_percentage", 0)
                tonal_sum += ev.get("tonal_score_percentage", 0)
                rhyme_sum += ev.get("rhyme_score_percentage", 0)
                poem_count += 1

        avg_scores = {}
        if poem_count > 0:
            avg_scores = {
                "average_total_score": round(total_sum / poem_count, 2),
                "average_structure_score": round(structure_sum / poem_count, 2),
                "average_tonal_score": round(tonal_sum / poem_count, 2),
                "average_rhyme_score": round(rhyme_sum / poem_count, 2),
            }

        model_base = filename[:-4] if filename.endswith(".txt") else filename
        safe_source = f"{model_base}-({mode_name})-{form_name}-{theme}.txt"
        results.append({
            "source_file": safe_source,
            "model": info['model'],
            "task_type": mode_name,
            "form_name": form_name,
            "form_type": form_type,
            "theme": theme,
            "works_evaluated": poem_count,
            "average_scores": avg_scores,
            "individual_results": poem_results,
        })

    return results


def _parse_marked_works(raw_text):
    marked_blocks = re.findall(
        r'\[title\]\s*(.*?)\s*\[content\]\s*(.*?)(?=(?:\n\s*\[title\])|\Z)',
        raw_text,
        flags=re.DOTALL,
    )
    return [
        {
            'title': title.strip(),
            'content': content.strip(),
        }
        for title, content in marked_blocks
    ]


def _parse_sota_info(filepath, sota_root):
    rel_parts = os.path.relpath(filepath, sota_root).split(os.sep)
    if len(rel_parts) < 3:
        return None

    model_dir, genre_dir = rel_parts[0], rel_parts[1]
    if genre_dir not in {'诗', '词'}:
        return None

    form_name = os.path.splitext(os.path.basename(filepath))[0]
    model = SOTA_MODEL_ALIASES.get(model_dir, model_dir)
    return {
        'model': model,
        'task_type': 'SOTA',
        'form_name': form_name,
        'form_type': 'tang' if genre_dir == '诗' else 'songci',
    }


def _process_sota_file(filepath, sota_root, songci_evaluator, tang_evaluator):
    info = _parse_sota_info(filepath, sota_root)
    if info is None:
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    marked_works = _parse_marked_works(raw_text)
    poem_results = []
    total_sum = structure_sum = tonal_sum = rhyme_sum = 0.0
    poem_count = 0

    for i, work in enumerate(marked_works):
        poem_text = work['content']
        if not poem_text:
            continue

        form_name = info['form_name']
        form_type = info['form_type']
        if form_type == 'songci' and songci_evaluator:
            ev = songci_evaluator.evaluate(form_name, poem_text)
        elif form_type == 'tang' and tang_evaluator:
            ev = tang_evaluator.evaluate(poem_text)
        else:
            continue

        poem_results.append({
            "work_index": i,
            "poem_text": poem_text,
            "title": work['title'],
            "theme": _strip_poem_title_prefix(work['title']),
            "evaluation": ev,
        })

        if "error" not in ev:
            total_sum += ev.get("total_score_percentage", 0)
            structure_sum += ev.get("structure_score_percentage", 0)
            tonal_sum += ev.get("tonal_score_percentage", 0)
            rhyme_sum += ev.get("rhyme_score_percentage", 0)
            poem_count += 1

    avg_scores = {}
    if poem_count > 0:
        avg_scores = {
            "average_total_score": round(total_sum / poem_count, 2),
            "average_structure_score": round(structure_sum / poem_count, 2),
            "average_tonal_score": round(tonal_sum / poem_count, 2),
            "average_rhyme_score": round(rhyme_sum / poem_count, 2),
        }

    return {
        "source_file": os.path.relpath(filepath, sota_root),
        "model": info['model'],
        "task_type": info['task_type'],
        "form_name": info['form_name'],
        "form_type": info['form_type'],
        "theme": "",
        "works_evaluated": poem_count,
        "average_scores": avg_scores,
        "individual_results": poem_results,
    }


def _save_per_file_output(result, mode_output_dir):
    model = result['model']
    model_dir = os.path.join(mode_output_dir, model)
    os.makedirs(model_dir, exist_ok=True)

    filename = result['source_file']
    out_name = filename.replace(os.sep, '__').replace('/', '__').replace('.txt', '_evaluation.json')
    out_name = re.sub(r'[<>:"\\|?*]+', '_', out_name)
    out_path = os.path.join(model_dir, out_name)

    output_data = {
        "source_file": filename,
        "model": model,
        "task_type": result['task_type'],
        "form_name": result['form_name'],
        "form_type": result['form_type'],
        "theme": result['theme'],
        "works_evaluated": result['works_evaluated'],
        "average_scores": result['average_scores'],
        "individual_results": result['individual_results'],
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    return out_path


def _build_model_summaries(all_results, mode_output_dir):
    by_model = defaultdict(lambda: {'tang': [], 'songci': []})
    for r in all_results:
        model = r['model']
        avg = r['average_scores']
        if not avg:
            continue
        entry = {
            "source_file": r['source_file'],
            "form_name": r['form_name'],
            "theme": r['theme'],
            "works_evaluated": r['works_evaluated'],
            "average_total_score": avg.get('average_total_score', 0),
            "average_structure_score": avg.get('average_structure_score', 0),
            "average_tonal_score": avg.get('average_tonal_score', 0),
            "average_rhyme_score": avg.get('average_rhyme_score', 0),
        }
        by_model[model][r['form_type']].append(entry)

    summaries = {}
    for model, type_dict in sorted(by_model.items()):
        tang_files = type_dict['tang']
        songci_files = type_dict['songci']

        def _aggregate(file_list):
            if not file_list:
                return {
                    "files_evaluated": 0,
                    "works_evaluated": 0,
                    "average_total_score": 0.0,
                    "average_structure_score": 0.0,
                    "average_tonal_score": 0.0,
                    "average_rhyme_score": 0.0,
                }
            n_files = len(file_list)
            n_works = sum(f['works_evaluated'] for f in file_list)
            return {
                "files_evaluated": n_files,
                "works_evaluated": n_works,
                "average_total_score": round(
                    sum(f['average_total_score'] for f in file_list) / n_files, 2),
                "average_structure_score": round(
                    sum(f['average_structure_score'] for f in file_list) / n_files, 2),
                "average_tonal_score": round(
                    sum(f['average_tonal_score'] for f in file_list) / n_files, 2),
                "average_rhyme_score": round(
                    sum(f['average_rhyme_score'] for f in file_list) / n_files, 2),
                "detail_files": [
                    {"file": f['source_file'], "form": f['form_name'],
                     "theme": f['theme'], "score": f['average_total_score']}
                    for f in file_list
                ],
            }

        tang_agg = _aggregate(tang_files)
        songci_agg = _aggregate(songci_files)

        tang_score = tang_agg['average_total_score']
        songci_score = songci_agg['average_total_score']
        weighted = round(0.4 * tang_score + 0.6 * songci_score, 2)

        summary = {
            "model": model,
            "tang_poem": tang_agg,
            "songci": songci_agg,
            "tang_total_score": tang_score,
            "songci_total_score": songci_score,
            "weighted_total_score": weighted,
            "weight_formula": "0.4 * tang_total + 0.6 * songci_total",
        }

        summary_path = os.path.join(mode_output_dir, f"{model}_summary.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        summaries[model] = summary_path

    return summaries


# ============================================================
#  Main
# ============================================================

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    import argparse

    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Evaluate Songci + Tang poems — constrained vs free decoding comparison")
    parser.add_argument("--meter", default=os.path.join(SCRIPT_DIR, "..", "Songci_Meter"),
                        help="Path to Songci meter JSON directory")
    parser.add_argument("--input", default=os.path.join(SCRIPT_DIR, "cleaned"),
                        help="Root input directory (expects cleaned constrained_decoding/ and free_decoding/ subdirs)")
    parser.add_argument("--sota-input", default=os.path.join(SCRIPT_DIR, "SOTA"),
                        help="SOTA input directory (expects {paper}/{诗|词}/{form}.txt)")
    parser.add_argument("--output", default=os.path.join(SCRIPT_DIR, "results", "auto_score"),
                        help="Root output directory")
    args = parser.parse_args()

    METER_DIR = args.meter
    INPUT_ROOT = args.input
    SOTA_INPUT_ROOT = args.sota_input
    OUTPUT_ROOT = args.output

    MODES = ['constrained_decoding', 'free_decoding', 'SOTA']

    songci_evaluator = None
    if os.path.isdir(METER_DIR):
        songci_evaluator = SongciEvaluator(METER_DIR)
        print(f"Loaded {len(songci_evaluator.meters)} cipai from '{METER_DIR}'")
    else:
        print(f"[WARN] Meter directory not found: {METER_DIR}")

    tang_evaluator = TangPoemEvaluator()

    for mode_name in ['constrained_decoding', 'free_decoding']:
        mode_input_dir = os.path.join(INPUT_ROOT, mode_name)
        mode_output_dir = os.path.join(OUTPUT_ROOT, mode_name)
        _reset_mode_output_dir(mode_output_dir)

        if not os.path.isdir(mode_input_dir):
            print(f"\n[SKIP] '{mode_name}': input directory not found")
            continue

        input_files = _collect_input_files(mode_input_dir)
        print(f"\n{'='*60}")
        print(f"  [{mode_name}] — {len(input_files)} file(s)")
        print(f"{'='*60}")

        all_results = []
        skipped = 0

        for fp in tqdm(input_files, desc=f"Evaluating {mode_name}"):
            results = _process_cleaned_file(fp, mode_name, songci_evaluator, tang_evaluator)
            if not results:
                skipped += 1
                continue
            for res in results:
                all_results.append(res)
                _save_per_file_output(res, mode_output_dir)

        if skipped:
            print(f"  Skipped {skipped} file(s) (unable to parse filename)")

        summaries = _build_model_summaries(all_results, mode_output_dir)
        print(f"  Processed {len(all_results)} file(s)")
        print(f"  Model summaries:")
        for model, path in summaries.items():
            print(f"    {model} -> {os.path.basename(path)}")

    mode_name = 'SOTA'
    mode_output_dir = os.path.join(OUTPUT_ROOT, mode_name)
    _reset_mode_output_dir(mode_output_dir)

    if os.path.isdir(SOTA_INPUT_ROOT):
        input_files = _collect_input_files(SOTA_INPUT_ROOT)
        print(f"\n{'='*60}")
        print(f"  [{mode_name}] — {len(input_files)} file(s)")
        print(f"{'='*60}")

        all_results = []
        skipped = 0

        for fp in tqdm(input_files, desc=f"Evaluating {mode_name}"):
            res = _process_sota_file(fp, SOTA_INPUT_ROOT, songci_evaluator, tang_evaluator)
            if res is None:
                skipped += 1
                continue
            all_results.append(res)
            _save_per_file_output(res, mode_output_dir)

        if skipped:
            print(f"  Skipped {skipped} file(s) (unable to parse SOTA path)")

        summaries = _build_model_summaries(all_results, mode_output_dir)
        print(f"  Processed {len(all_results)} file(s)")
        print(f"  Model summaries:")
        for model, path in summaries.items():
            print(f"    {model} -> {os.path.basename(path)}")
    else:
        print(f"\n[SKIP] '{mode_name}': input directory not found")

    comparison = {}
    for mode_name in MODES:
        mode_output_dir = os.path.join(OUTPUT_ROOT, mode_name)
        mode_models = {}
        if os.path.isdir(mode_output_dir):
            for fn in os.listdir(mode_output_dir):
                if fn.endswith('_summary.json'):
                    with open(os.path.join(mode_output_dir, fn), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    model_name = data['model']
                    mode_models[model_name] = {
                        "tang_total_score": data['tang_total_score'],
                        "songci_total_score": data['songci_total_score'],
                        "weighted_total_score": data['weighted_total_score'],
                    }
        comparison[mode_name] = mode_models

    comparison_path = os.path.join(OUTPUT_ROOT, 'comparison.json')
    with open(comparison_path, 'w', encoding='utf-8') as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  Evaluation complete.")
    for mode_name in MODES:
        info = comparison.get(mode_name, {})
        print(f"  [{mode_name}]: {len(info)} model(s)")
    print(f"  Comparison summary -> {comparison_path}")
    print(f"{'='*60}")
