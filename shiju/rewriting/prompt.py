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
    requirement = request.requirement.strip() or "保持原作题旨并提升语言自然度与诗意。"
    return [
        {
            "role": "system",
            "content": (
                "你是一位精通古典诗词格律的编辑。你只改写指定诗句，其他诗句仅作上下文。"
                "不要输出隐藏思维过程或 <think> 标签。"
            ),
        },
        {
            "role": "user",
            "content": (
                "/no_think\n"
                f"请改写{targets}。\n"
                f"改写要求：{requirement}\n\n"
                "先用一句话说明准备如何调整立意、意象或收束方式；不得在这句话中提前写出"
                "完整候选诗句。随后只输出指定句，不得复述未修改部分。\n\n"
                "严格使用以下格式：\n"
                f"{PLAN_MARKER}一句修改思路，单行、不超过80字并以句号结束。\n"
                f"{REWRITE_MARKER}\n"
                "按原句序输出替换诗句\n\n"
                f"【目标句】\n{target_text}\n\n"
                f"【完整原诗】\n{poem.source}"
            ),
        },
    ]

