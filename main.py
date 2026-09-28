"""Chunk 评分实验入口。运行：python main.py [实验参数]

默认执行 shiju 格律约束下的 chunk 内模型分数实验，不启用词表奖励。
命令行参数会覆盖下方默认配置，完整参数见 experiments/chunk_scoring/generate.py --help。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence


MODEL_PATH = r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B"
CHUNK_LENGTHS = "2,2,3"
LINE_COUNT = 4
CANDIDATES_PER_CHUNK = 8
BATCHES = 1
POEMS_PER_BATCH = 2
TEMPERATURE = 0.8
TOP_P = 0.95
SELECTION_TEMPERATURE = 0.5
SEED = 20260927

PROMPT = """
请创作一首新韵七言绝句，主题为中秋夜晚思念远方亲友并送上祝福。

创作脉络：
1. 首句从仰望天空写起，描绘今夜中秋明月圆满皎洁、夜空清朗的实景。
2. 次句转向远方，想象亲友此刻身在他乡，或许也正仰望明月。
3. 第三句写彼此虽相隔两地，却共赏同一轮月，借普照的月光表达心灵相通。
4. 末句升华，可以表达祝福，也可以用其他更委婉的方式发挥。总之心意第一。

情绪由静谧赏月，渐生淡淡思念，继而转为温馨的心灵连接，最后升华或者祝福。
严格遵守七言绝句四句、每句七字；按每句 2/2/3 的句读组织语意；采用新韵，注意偶数句押韵。
语言凝练自然，意象清晰，避免生造词语、直白说理和堆砌陈词。
只输出诗题（可省略）与四句诗文，不要输出创作说明、格律标记或其他内容。
"""

OUTPUT_DIR = Path("experiments/chunk_scoring/results") / datetime.now().strftime("%Y%m%d_%H%M%S")


def main(argv: Sequence[str] | None = None) -> None:
    from experiments.chunk_scoring.generate import main as run_experiment

    defaults = [
        "--constraint-backend", "shiju",
        "--model", MODEL_PATH,
        "--quantization", "8bit",
        "--prompt", PROMPT,
        "--chunks", CHUNK_LENGTHS,
        "--line-count", str(LINE_COUNT),
        "--meter-type", "唐诗",
        "--form-name", "七言绝句",
        "--rhyme-dict", "Xinyun",
        "--theme", "中秋夜思念远方亲友并送上祝福",
        "--candidates", str(CANDIDATES_PER_CHUNK),
        "--batches", str(BATCHES),
        "--poems-per-batch", str(POEMS_PER_BATCH),
        "--seed", str(SEED),
        "--temperature", str(TEMPERATURE),
        "--top-p", str(TOP_P),
        "--selection-temperature", str(SELECTION_TEMPERATURE),
        "--output", str(OUTPUT_DIR / "chunk_scoring.jsonl"),
    ]
    # 将用户参数放在默认值之后，使其可覆盖实验配置。
    run_experiment([*defaults, *(list(argv) if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    main()
