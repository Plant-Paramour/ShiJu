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


def _output_contract(
    title_prefix: str,
    planning_instruction: str | None = None,
    planning_label: str = "创作构思分析",
    planning_marker: str | None = None,
) -> str:
    planning = planning_instruction or (
        "请先分别从题旨立意、章法布局、意象选择、用典化用和用韵策略五方面进行散文分析，"
        "每方面二至三句；分析中不得提前写出诗句或词句草稿。"
    )
    planning_step = f"1. 先输出{planning_label}。\n"
    planning_example = ""
    if planning_marker:
        planning_step = (
            f"1. 先输出{planning_label}，第一行必须以 {planning_marker} 开头。\n"
        )
        planning_example = f"{planning_marker}简短创作方向与安排\n"
    return (
        "你是一位擅长古典诗词创作的作者。\n\n"
        "创作时必须遵守以下优先级：\n"
        "1. 用户给出的核心叙事必须全部落实在正文中，不得只在标题或说明中提及。\n"
        "2. 现代语义须转换为自然的古典表达，但不得省略人物、时间、事件、关切或情感。\n"
        "3. 正文须符合指定诗体、主题和古典诗词审美。\n"
        "4. 同时根据格律约束安排字词，不得为了格律省略核心叙事。\n\n"
        f"{planning}\n\n"
        "必须按以下格式输出：\n"
        f"{planning_step}"
        f"2. {planning_label}结束后，严格按照下面的完整模板输出标题和正文：\n"
        f"{TITLE_MARKER}{title_prefix}·作品名\n"
        f"{CONTENT_MARKER}正文\n\n"
        "完整格式示例：\n"
        f"{planning_example}"
        f"{TITLE_MARKER}{title_prefix}·春思\n"
        f"{CONTENT_MARKER}柳色含烟……\n\n"
        f"标题中的“{title_prefix}”不可省略，也不得只输出作品名。"
        f"{TITLE_MARKER} 和 {CONTENT_MARKER} 两个标记均不可省略、修改或替换；"
        f"正文第一个字之前必须原样输出 {CONTENT_MARKER}。\n"
        "除前述创作构思或规划外，不得输出格律说明、注释或其他额外文字；"
        "标题和正文之后不得输出任何额外内容。正文不得包含段落标记、"
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


def _final_section(title_prefix: str, planning_label: str = "创作分析") -> str:
    return (
        "【最终要求】\n"
        "正文篇幅有限时，优先保证核心叙事完整，其次考虑意象、用典和辞藻。\n"
        f"请严格按{planning_label}、标题、正文的顺序输出。规划结束后必须紧接：\n"
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


def build_hanpai_prompt(
    task_type: str,
    form_name: str,
    theme: str,
    line_lengths: tuple[int, int, int],
    requirement: str = "",
    use_thinking: bool = True,
    rhyme_dict_name: str = "Xinyun",
    season_word: str | None = None,
    season_words: tuple[str, ...] = (),
    season: str | None = None,
    forbid_isolated_level: bool = False,
    allow_aojiu: bool = False,
    forbid_three_same_ending: bool = False,
    rhyme_scheme: str | None = None,
) -> list[dict[str, str]]:
    if task_type != "instruction":
        raise ValueError(f"汉俳当前只支持 instruction，收到: {task_type}")

    pattern = "-".join(str(length) for length in line_lengths)
    rhyme_name = RHYME_NAMES.get(rhyme_dict_name, rhyme_dict_name)
    season_inputs = (season_word is not None, bool(season_words), season is not None)
    if sum(season_inputs) > 1:
        raise ValueError("季语、候选季语和季节只能配置其中一种")
    if season_word is not None:
        season_rule = (
            f"必须在正文中原样、自然地使用指定季语“{season_word.strip()}”，"
            "不得只在标题或创作分析中提及。"
        )
    elif season_words:
        candidates = "、".join(f"“{word.strip()}”" for word in season_words)
        season_rule = (
            f"必须且只能从候选季语 {candidates} 中选择一个，并在正文中原样、"
            "自然地使用；不得只在标题或创作分析中提及。"
        )
    elif season is not None:
        season_rule = (
            f"指定季节为“{season.strip()}”。必须在正文中使用一个无需解释即可明显指向"
            "该季节的具体季语或季节意象，不得只写季节名称代替具体意象。"
        )
    else:
        season_rule = (
            "未指定季语或季节，但正文仍必须自行选择并使用一个明显、具体的季语或"
            "季节意象。"
        )
    season_rule += (
        "读者必须仅凭正文即可判断相应季节；未加时令限定的云、月、风、雨、柳等"
        "一般景物不视为明显季语。"
    )

    prosody_rules = []
    if forbid_isolated_level:
        if allow_aojiu:
            prosody_rules.append("禁止未获补救的孤平，允许使用邻位平声完成拗救")
        else:
            prosody_rules.append("禁止孤平")
    elif allow_aojiu:
        prosody_rules.append("允许自然使用拗救，但不强制安排")
    if forbid_three_same_ending:
        prosody_rules.append("每行句尾不得出现三连平或三连仄")
    prosody_text = "；".join(prosody_rules) if prosody_rules else "不额外限定平仄格律"

    normalized_scheme = rhyme_scheme.upper().strip() if rhyme_scheme else None
    rhyme_descriptions = {
        "AAA": "三行句尾均押同一韵部",
        "ABA": "第一、三行句尾押同一韵部，第二行不押",
        "BAA": "第二、三行句尾押同一韵部，第一行不押",
    }
    if normalized_scheme and normalized_scheme not in rhyme_descriptions:
        raise ValueError(
            f"汉俳押韵格式仅支持 AAA、ABA、BAA 或不押韵，收到: {rhyme_scheme}"
        )
    if normalized_scheme:
        rhyme_text = (
            f"采用 {normalized_scheme} 式：{rhyme_descriptions[normalized_scheme]}；"
            f"依据{rhyme_name}，首个押韵句确定声调和韵部，后续不得换韵。"
        )
    else:
        rhyme_text = "不设置押韵要求。"

    rules = (
        "【汉俳规则】\n"
        f"- 格式：{pattern}，正文恰好三行，依次为"
        f"{line_lengths[0]}字、{line_lengths[1]}字、{line_lengths[2]}字\n"
        "- 句读：五字句严格按 2/3 划分，七字句严格按 2/2/3 划分；"
        "每个节奏段必须独立成意，不得把一个词拆到边界两侧。生成过程中程序会在边界"
        "临时插入顿号以提示节奏，最终输出会自动移除这些顿号\n"
        "- 行间只换行，行尾不输出逗号、句号等标点\n"
        f"- 季语：{season_rule}\n"
        f"- 格律：{prosody_text}\n"
        f"- 押韵：{rhyme_text}\n"
        "- 语言凝练，三行须共同构成一次完整的观察、转折或余韵"
    )
    planning_instruction = (
        "汉俳正式写作前，先输出一小段简短的创作规划，控制在 2 至 4 句：说明核心叙事"
        "如何分配到三行、准备使用的明显季语或季节意象、情景推进方式，以及押韵和格律的"
        "取舍。这段规划必须作为可见答案输出并以 [plan] 开头，不能放进 <think> 标签。"
        "规划只写创作方向，不要展开逐步思维链，不要提前写出完整诗句、分句或格律符号。"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是一位擅长汉俳创作的诗人，能够在极短篇幅中凝聚具体景象与情感。\n\n"
                + _output_contract(
                    form_name,
                    planning_instruction,
                    "创作规划",
                    "[plan]",
                )
            ),
        },
        {
            "role": "user",
            "content": (
                "【创作形式】\n"
                f"诗体：{form_name}\n"
                f"篇幅：{pattern}\n\n"
                f"{_narrative_section(requirement)}\n\n"
                f"{_style_section(theme)}\n\n"
                f"{rules}\n\n"
                f"{_final_section(form_name, '创作规划')}"
            ),
        },
    ]
    return _apply_thinking(messages, use_thinking)
