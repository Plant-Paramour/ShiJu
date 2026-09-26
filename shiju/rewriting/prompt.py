from __future__ import annotations

from ..contracts import RewritePoemRequest
from ..domain import PLAN_MARKER, REWRITE_MARKER
from .parser import ParsedPoem


def build_rewrite_messages(
    request: RewritePoemRequest,
    poem: ParsedPoem,
) -> list[dict[str, str]]:
    targets = "、".join(f"第{number}句" for number in request.target_line_numbers)
    target_text = "\n".join(
        f"- 第{line.number}句：{line.text}"
        for line in poem.lines
        if line.number in request.target_line_numbers
    )
    fixed_text = "\n".join(
        f"- 第{line.number}句：{line.text}"
        for line in poem.lines
        if line.number not in request.target_line_numbers
    ) or "- 无（全部重写）"
    requirement = request.requirement.strip() or "保持原作题旨并提升语言自然度与诗意。"
    return [
        {
            "role": "system",
            "content": (
                "你是一位精通古典诗词格律的编辑。你改写指定诗句，并逐字保留其他诗句。"
                "不要输出隐藏思维过程或 <think> 标签。"
            ),
        },
        {
            "role": "user",
            "content": (
                "/no_think\n"
                f"请改写{targets}。\n"
                f"改写要求：{requirement}\n\n"
                "先用一句话说明如何让改写句与所有保留句在语义和章法上衔接；不得在这句话中"
                "提前写出完整候选诗句。随后输出完整诗稿。保留句会在解码时被逐字固定，"
                "它们也是续写后文的真实上下文；不要把前一目标句的意思误当成保留句。\n\n"
                "严格使用以下格式：\n"
                f"{PLAN_MARKER}一句修改思路，单行、不超过80字并以句号结束。\n"
                f"{REWRITE_MARKER}\n"
                f"按原句序输出完整的 {len(poem.lines)} 句诗稿\n\n"
                "【目标句：负面样本】\n"
                "以下是原诗中需要替换的句子。不得原样复述，也不要只做无意义的同义替换；"
                "应根据改写要求生成有实质变化的新句。\n"
                f"{target_text}\n\n"
                f"【逐字保留句】\n{fixed_text}\n\n"
                f"【完整原诗】\n{poem.source}"
            ),
        },
    ]
