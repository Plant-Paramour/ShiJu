"""chunk 评分实验启动入口。运行：python main.py"""

from __future__ import annotations

from pathlib import Path


MODEL_PATH = r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B"
# 五言："2,3"；七言："2,2,3"；宋词按 / 划分后填写对应字数。
CHUNK_LENGTHS = "2,2,3"
PROMPT = "请创作一句写秋夜江面的古典诗句，只输出诗句正文。"
CANDIDATES_PER_CHUNK = 8
TEMPERATURE = 0.8
TOP_P = 0.95

# False：只按模型 chunk 分数；True：加入词表微弱正向奖励。
LEXICON_REWARD_ENABLED = False
LEXICON_REWARD_WEIGHT = 0.1
LEXICON_PATH = Path("shiju/二三字词表.csv")


def main() -> None:
    from experiments.chunk_scoring.generate import main as run_experiment

    argv = [
        "--model", MODEL_PATH,
        "--prompt", PROMPT,
        "--chunks", CHUNK_LENGTHS,
        "--candidates", str(CANDIDATES_PER_CHUNK),
        "--temperature", str(TEMPERATURE),
        "--top-p", str(TOP_P),
        "--lexicon", str(LEXICON_PATH),
        "--lambda", str(LEXICON_REWARD_WEIGHT),
    ]
    if LEXICON_REWARD_ENABLED:
        argv.append("--lexicon-reward")
    run_experiment(argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[启动失败] {exc}")
        raise
