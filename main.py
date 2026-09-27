"""chunk 评分实验启动入口。运行：python main.py"""

from __future__ import annotations

from pathlib import Path


MODEL_PATH = r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B"
# 七言绝句四句，每句内部按 2/2/3 固定句读生成。
CHUNK_LENGTHS = "2,2,3,2,2,3,2,2,3,2,2,3"
PROMPT = """请创作一首新韵七言绝句，主题为中秋夜晚思念远方亲友并送上祝福。

创作脉络：
1. 首句从仰望天空写起，描绘今夜中秋明月圆满皎洁、夜空清朗的实景。
2. 次句转向远方，想象亲友此刻身在他乡，或许也正仰望明月。
3. 第三句写彼此虽相隔两地，却共赏同一轮月，借普照的月光表达心灵相通。
4. 末句真诚祝愿亲友平安、身体康健、一切安好，并含有期待再次相聚之意。

情绪由静谧赏月，渐生淡淡思念，继而转为温馨的心灵连接，最后落在温暖真挚的祝愿。
严格遵守七言绝句四句、每句七字；按每句 2/2/3 的句读组织语意；采用新韵，注意偶数句押韵。
语言凝练自然，意象清晰，避免生造词语、直白说理和堆砌陈词。
只输出诗题（可省略）与四句诗文，不要输出创作说明、格律标记或其他内容。"""
CANDIDATES_PER_CHUNK = 8
BATCHES = 3
POEMS_PER_BATCH = 2
TEMPERATURE = 0.8
TOP_P = 0.95
SEED = 20260927

# False、True 两种模式均执行，每种模式生成 3 批、每批 2 首。
LEXICON_REWARD_WEIGHT = 0.1
LEXICON_PATH = Path("shiju/二三字词表.csv")
OUTPUT_DIR = Path("experiments/chunk_scoring/results")


def main() -> None:
    from experiments.chunk_scoring.generate import main as run_experiment

    shared_args = [
        "--model", MODEL_PATH,
        "--prompt", PROMPT,
        "--chunks", CHUNK_LENGTHS,
        "--candidates", str(CANDIDATES_PER_CHUNK),
        "--batches", str(BATCHES),
        "--poems-per-batch", str(POEMS_PER_BATCH),
        "--seed", str(SEED),
        "--temperature", str(TEMPERATURE),
        "--top-p", str(TOP_P),
        "--lexicon", str(LEXICON_PATH),
        "--lambda", str(LEXICON_REWARD_WEIGHT),
    ]
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    print(f"加载模型：{MODEL_PATH}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    for reward_enabled, label in ((False, "reward_off"), (True, "reward_on")):
        print(f"\n===== 词表奖励 {'开启' if reward_enabled else '关闭'}：{BATCHES} 批 × {POEMS_PER_BATCH} 首 =====")
        argv = shared_args + ["--output", str(OUTPUT_DIR / f"{label}.jsonl")]
        if reward_enabled:
            argv.append("--lexicon-reward")
        run_experiment(argv, model=model, tokenizer=tokenizer)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[启动失败] {exc}")
        raise
