# Chunk 评分实验

这个目录是独立实验，不修改 `shiju/` 的生产生成链路。

实验目标：在同一个固定句读边界上，对候选 chunk 比较两种排序：

- 关闭词表奖励：只按模型提供的 chunk logprob 排序；
- 开启词表奖励：模型分数加一个很小的正向词表奖励。

候选文件使用 JSONL，每行一个候选：

```json
{"chunk": "春风", "model_logprob": -3.2, "token_count": 2}
```

`model_logprob` 是模型生成该 chunk 时各 token logprob 的总和。评分器会按 chunk 汉字数归一化，因此不要求一个古典词必须是单独 token。

运行：

```powershell
python experiments/chunk_scoring/compare.py candidates.jsonl
python experiments/chunk_scoring/compare.py candidates.jsonl --lexicon-reward --lambda 0.1
```

词表路径默认使用 `shiju/二三字词表.csv`，也可以通过 `--lexicon` 指定。

## 使用本地 Qwen3 生成

需要安装项目的 GPU 依赖（`torch`、`transformers`）。例如七言句按 `2/2/3`：

```powershell
python experiments/chunk_scoring/generate.py `
  --prompt "请创作一句写秋夜江面的古典诗句，只输出诗句正文。" `
  --chunks 2,2,3 `
  --candidates 8
```

启用词表弱奖励进行对照：

```powershell
python experiments/chunk_scoring/generate.py `
  --prompt "请创作一句写秋夜江面的古典诗句，只输出诗句正文。" `
  --chunks 2,2,3 `
  --candidates 8 `
  --lexicon-reward `
  --lambda 0.1
```

`--model` 默认就是本机的 Qwen3-4B 缓存路径。脚本会在每个固定 chunk 边界筛选恰好对应字数的候选，输出每个候选的模型分数、词表奖励和总分。当前实验按每个 chunk 选择最高分候选，尚未接入生产格律状态机、平仄或押韵约束。
