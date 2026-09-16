from __future__ import annotations

import json
from pathlib import Path

from .data import MeterTemplate
from .domain import CONTENT_MARKER, TITLE_MARKER


RHYME_NAMES = {
    "Cilin": "词林正韵",
    "Pinshui": "平水韵",
    "Xinyun": "中华新韵",
    "Tongyun": "中华通韵",
}


def _apply_thinking(messages: list[dict[str, str]], use_thinking: bool) -> list[dict[str, str]]:
    if not use_thinking:
        for message in messages:
            if message["role"] == "user":
                message["content"] = "/no_think " + message["content"]
    return messages


def _output_contract(title_prefix: str) -> str:
    return (
        "你是一位擅长古典诗词创作的作者。\n\n"
        "创作时必须遵守以下优先级：\n"
        "1. 用户给出的核心叙事必须全部落实在正文中，不得只在标题或说明中提及。\n"
        "2. 现代语义须转换为自然的古典表达，但不得省略人物、时间、事件、关切或情感。\n"
        "3. 正文须符合指定诗体、主题和古典诗词审美。\n"
        "4. 同时根据格律约束安排字词，不得为了格律省略核心叙事。\n\n"
        "请先分别从题旨立意、章法布局、意象选择、用典化用和用韵策略五方面进行散文分析，"
        "每方面二至三句；分析中不得提前写出诗句或词句草稿。\n\n"
        "必须按以下格式输出：\n"
        "1. 先输出创作构思分析。\n"
        "2. 分析结束后，严格按照下面的完整模板输出标题和正文：\n"
        f"{TITLE_MARKER}{title_prefix}·作品名\n"
        f"{CONTENT_MARKER}正文\n\n"
        "完整格式示例：\n"
        f"{TITLE_MARKER}{title_prefix}·春思\n"
        f"{CONTENT_MARKER}柳色含烟……\n\n"
        f"标题中的“{title_prefix}”不可省略，也不得只输出作品名。"
        f"{TITLE_MARKER} 和 {CONTENT_MARKER} 两个标记均不可省略、修改或替换；"
        f"正文第一个字之前必须原样输出 {CONTENT_MARKER}。\n"
        "不得输出格律说明、注释或其他额外文字。正文不得包含段落标记、"
        "序号、解释性文字或“平”“仄”“中”“/”等格律符号。"
    )


def _narrative_section(requirement: str) -> str:
    if not requirement:
        return "【核心叙事】\n请围绕主题完成完整、具体的情感表达。"
    return (
        "【核心叙事】\n"
        "以下要求必须全部体现在正文中，不得只表现笼统的主题或相思；"
        "可以改写为古典语汇，但不得省略或泛化：\n"
        f"{requirement}"
    )


def _style_section(theme: str) -> str:
    return (
        "【情感与风格】\n"
        f"主题：{theme}\n"
        "表达须含蓄典雅、情景交融，避免直白口语和泛泛堆砌相思意象。"
    )


def _final_section(title_prefix: str) -> str:
    return (
        "【最终要求】\n"
        "正文篇幅有限时，优先保证核心叙事完整，其次考虑意象、用典和辞藻。\n"
        "请严格按创作分析、标题、正文的顺序输出。分析结束后必须紧接：\n"
        f"{TITLE_MARKER}{title_prefix}·作品名\n"
        f"{CONTENT_MARKER}正文\n"
        f"不得省略“{title_prefix}”，也不得省略或改写 {TITLE_MARKER}、{CONTENT_MARKER}。"
    )


def _template_meter_section(template: MeterTemplate, rhyme_name: str) -> str:
    rules = [
        "【格律约束】",
        f"采用变体：{template.variant_name}",
        f"用韵依据：{rhyme_name}",
        f"韵式：{template.rhyme_type}",
        "以下格律只供理解，格律符号不得出现在正文中。"
        "其中“/”表示句内节奏边界且不输出，“、”表示必须输出顿号。",
    ]
    for stanza in template.stanzas:
        rules.append(f"第{stanza.index + 1}阕：")
        for line_index, line in enumerate(stanza.lines, start=1):
            rhyme_note = f"，押第{line.rhyme_group}组韵" if line.rhyme_group else ""
            rules.append(
                f"- 第{line_index}句（{line.layout.length}字）：{line.raw_pattern}{rhyme_note}"
            )
    return "\n".join(rules)


def _template_task_prompt(
    name: str,
    rhyme_name: str,
    theme: str,
    requirement: str,
    variant_name: str | None = None,
    meter_text: str = "",
) -> str:
    variant_line = f"\n变体：{variant_name}" if variant_name else ""
    meter_section = f"{meter_text}\n\n" if meter_text else ""
    return (
        "【创作形式】\n"
        f"词牌：{name}{variant_line}\n"
        f"用韵：{rhyme_name}\n"
        "词牌的字数、句读、平仄和押韵须严格遵守。\n\n"
        f"{_narrative_section(requirement)}\n\n"
        f"{_style_section(theme)}\n\n"
        f"{meter_section}"
        f"{_final_section(name)}"
    )


def _relational_task_prompt(
    form_name: str,
    rhyme_name: str,
    theme: str,
    line_length: int,
    num_lines: int,
    requirement: str,
) -> str:
    length_name = "五言" if line_length == 5 else "七言"
    form_type = "绝句" if num_lines == 4 else "律诗"
    rules = (
        "【格律约束】\n"
        "以下格律须严格遵守：\n"
        f"- 每句 {line_length} 字，共 {num_lines} 句\n"
        "- 严格遵守二四六分明：第2字决定基调，第4字与第2字相反，第6字与第2字相同\n"
        "- 奇数句以仄声收尾，偶数句以平声收尾\n"
        "- 所有偶数句必须押同一韵部，一韵到底\n"
        "- 避免孤平、三连平、三连仄\n"
        "- 不以“的”“些”“么”“了”等现代白话虚词入诗"
    )
    return (
        "【创作形式】\n"
        f"诗体：{form_name}（{length_name}{form_type}）\n"
        f"用韵：{rhyme_name}\n"
        f"篇幅：每句{line_length}字，共{num_lines}句\n"
        "字数、句数、句读、平仄和押韵须严格遵守。\n\n"
        f"{_narrative_section(requirement)}\n\n"
        f"{_style_section(theme)}\n\n"
        f"{rules}\n\n"
        f"{_final_section(form_name)}"
    )


def build_template_prompt(
    task_type: str,
    template: MeterTemplate,
    theme: str,
    requirement: str = "",
    use_thinking: bool = True,
    rhyme_dict_name: str = "Cilin",
    cipai_data_path: str = "PoeTone-main/data/cipai_data.json",
) -> list[dict[str, str]]:
    name = template.name
    rhyme_name = RHYME_NAMES.get(rhyme_dict_name, rhyme_dict_name)

    if task_type == "zero-shot":
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位精通宋代词学的词人，擅长以典雅凝练的古典语汇营造深远意境。\n\n"
                    + _output_contract(name)
                ),
            },
            {
                "role": "user",
                "content": _template_task_prompt(name, rhyme_name, theme, requirement),
            },
        ]
        return _apply_thinking(messages, use_thinking)

    if task_type in {"one-shot", "completion"}:
        path = Path(cipai_data_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{cipai_data_path} 不存在，{task_type} 依赖仓库外部示例数据"
            )
        with path.open("r", encoding="utf-8") as stream:
            external_data = json.load(stream)
        if task_type == "one-shot":
            example = external_data["one_shot_examples"].get(name, "")
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一位精通宋代词学的词人，擅长揣摩前人词作的风格神韵，"
                        "并能融会贯通、推陈出新。请研读范例后创作具有独立艺术价值的新词。\n\n"
                        + _output_contract(name)
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"这是《{name}》的范例：\n\n{example}\n\n"
                        "请揣摩其意象、章法和语言风格，效仿神韵而非字句。\n\n"
                        f"{_template_task_prompt(name, rhyme_name, theme, requirement)}"
                    ),
                },
            ]
        else:
            first_half = external_data["completion_data"].get(name, {}).get("first_half", "")
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一位精通宋代词学的词人，尤其擅长承上启下、续写词章。"
                        "下阕须承接上阕意脉，又能翻出新意并升华主题，且必须完全原创。\n\n"
                        + _output_contract(name)
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"这是《{name}》的上阕：\n\n{first_half}\n\n"
                        "请承接上阕意脉、深化情感或转出新境，并完全原创。\n\n"
                        f"{_template_task_prompt(name, rhyme_name, theme, requirement)}"
                    ),
                },
            ]
        return _apply_thinking(messages, use_thinking)

    if task_type != "instruction":
        raise ValueError(f"宋词不支持任务类型: {task_type}")

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位精通宋代词学的词人，深谙词牌格律、意象经营与章法布局，追求字字珠玑、"
                "句句有意。\n\n" + _output_contract(name)
            ),
        },
        {
            "role": "user",
            "content": _template_task_prompt(
                name,
                rhyme_name,
                theme,
                requirement,
                template.variant_name,
                _template_meter_section(template, rhyme_name),
            ),
        },
    ]
    return _apply_thinking(messages, use_thinking)


def build_relational_prompt(
    task_type: str,
    form_name: str,
    theme: str,
    line_length: int,
    num_lines: int,
    requirement: str = "",
    use_thinking: bool = True,
    rhyme_dict_name: str = "Pinshui",
) -> list[dict[str, str]]:
    if task_type != "instruction":
        raise ValueError(f"唐诗当前只支持 instruction，收到: {task_type}")
    rhyme_name = RHYME_NAMES.get(rhyme_dict_name, rhyme_dict_name)
    messages = [
        {
            "role": "system",
            "content": "你是一位擅长唐诗创作的诗人。\n\n"
            + _output_contract(form_name),
        },
        {
            "role": "user",
            "content": _relational_task_prompt(
                form_name,
                rhyme_name,
                theme,
                line_length,
                num_lines,
                requirement,
            ),
        },
    ]
    return _apply_thinking(messages, use_thinking)
