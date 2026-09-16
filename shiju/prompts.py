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
    requirement_text = f"\n详细写作要求：{requirement}\n" if requirement else ""
    output_contract = (
        "\n\n你的输出必须遵循以下格式：\n"
        "1. 首先以散文笔法输出创作构思分析，严禁在分析中写诗句或词句草稿。\n"
        f"2. 接着输出标题，格式为：{TITLE_MARKER}{name}·标题。\n"
        f"3. 最后输出正文，格式为：{CONTENT_MARKER}正文。\n\n"
        "关键要求：两个标记不可省略、修改或替换；正文必须使用纯中文古典诗词语言，"
        "不得包含“平”“仄”“中”“/”等格律符号、段落标记、注脚、序号或解释性文字。"
    )

    if task_type == "zero-shot":
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位精通宋代词学的词人，深谙词牌格律、意象经营与章法布局之道，"
                    "擅长以典雅凝练的古典语汇营造深远意境。"
                    + output_contract
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请以《{name}》为词牌，以“{theme}”为主题创作一首宋词，"
                    f"用韵遵循《{rhyme_name}》。\n\n创作要领：\n"
                    "- 意象须鲜明生动，情景交融，忌空洞堆砌\n"
                    "- 语言须典雅凝练，善用比兴寄托，忌直白如白话\n"
                    "- 章法须有层次，注意上下阕之间的意脉承接与转折\n"
                    f"{requirement_text}\n请开始创作。"
                ),
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
                        "并能融会贯通、推陈出新。请研读范例后创作具有独立艺术价值的新词。"
                        + output_contract
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"这是一首以《{name}》为词牌的范例：\n\n{example}\n\n"
                        f"请揣摩其意象、章法和语言风格，以“{theme}”为主题创作全新的词。"
                        f"用韵遵循《{rhyme_name}》，效仿神韵而非字句。{requirement_text}"
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
                        "下阕须承接上阕意脉，又能翻出新意并升华主题，且必须完全原创。"
                        + output_contract
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"这是《{name}》的上阕：\n\n{first_half}\n\n"
                        f"请围绕“{theme}”创作全新的下阕，用韵遵循《{rhyme_name}》。"
                        f"下阕须承接意脉、深化情感或转出新境。{requirement_text}"
                    ),
                },
            ]
        return _apply_thinking(messages, use_thinking)

    if task_type != "instruction":
        raise ValueError(f"宋词不支持任务类型: {task_type}")

    rules = [
        f"【{name}】格律要求：",
        f"采用变体：{template.variant_name}",
        f"用韵依据：《{rhyme_name}》",
        f"韵式：{template.rhyme_type}",
        "“/”仅表示句内节奏边界且不输出，“、”表示必须输出顿号。"
        "格律符号只供理解，严禁出现在正文中。",
    ]
    for stanza in template.stanzas:
        rules.append(f"第{stanza.index + 1}阕：")
        for line_index, line in enumerate(stanza.lines, start=1):
            rhyme_note = f"，押第{line.rhyme_group}组韵" if line.rhyme_group else ""
            rules.append(
                f"- 第{line_index}句（{line.layout.length}字）：{line.raw_pattern}{rhyme_note}"
            )
    rule_text = "\n".join(rules)
    messages = [
        {
            "role": "system",
            "content": (
                "你是一位精通宋代词学的词人，深谙词牌格律、意象经营与章法布局，"
                "追求字字珠玑、句句有意。创作前必须分别从题旨立意、章法布局、意象选择、"
                "用典化用和用韵策略五方面进行散文分析，每项二至三句；"
                "严禁在分析部分提前写出任何诗句或词句草稿。" + output_contract
            ),
        },
        {
            "role": "user",
            "content": (
                f"请创作一首符合古典词学审美的宋词。\n\n主题：“{theme}”\n"
                f"词牌：《{name}》\n用韵依据：《{rhyme_name}》\n"
                "创作要求：意象须有画面感、情景交融；语言须典雅凝练，善用比兴与用典；"
                "上下阕须层次递进、意脉贯通；炼字须精当，音韵须和谐。\n"
                f"{requirement_text}\n以下格律只供理解，绝不可在正文中复述：\n"
                f"{rule_text}\n请严格按分析、标题、正文的顺序输出。"
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
    requirement_text = f"\n详细写作要求：{requirement}\n" if requirement else ""
    length_name = "五言" if line_length == 5 else "七言"
    form_type = "绝句" if num_lines == 4 else "律诗"
    rules = (
        f"【{form_name}】格律要求（{length_name}{form_type}）：\n"
        f"用韵依据：《{rhyme_name}》\n"
        f"- 每句 {line_length} 字，共 {num_lines} 句\n"
        "- 严格遵守二四六分明：第2字决定基调，第4字与第2字相反，第6字与第2字相同\n"
        "- 奇数句以仄声收尾，偶数句以平声收尾\n"
        "- 所有偶数句必须押同一韵部，一韵到底\n"
        "- 避免孤平、三连平、三连仄\n"
        "- 不以“的”“些”“么”“了”等现代白话虚词入诗"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是一位唐代诗人。请根据诗体、主题和格律要求创作唐诗。"
                "首先写出对主题的理解和布局分析；接着换行输出"
                f" `{TITLE_MARKER}{form_name}·标题`；最后换行输出 `{CONTENT_MARKER}正文`。"
                "两个标记不可省略、修改或替换。正文不得包含段落标记、注脚、额外说明或格律文本。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请创作一首唐诗。\n主题：“{theme}”\n体裁：《{form_name}》"
                f"（{length_name}{form_type}）\n用韵依据：《{rhyme_name}》\n"
                f"{requirement_text}\n必须遵守以下格律：\n{rules}\n"
                f"请先输出分析，再输出 `{TITLE_MARKER}{form_name}·标题`，"
                f"最后输出 `{CONTENT_MARKER}正文`。"
            ),
        },
    ]
    return _apply_thinking(messages, use_thinking)
