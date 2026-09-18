# Evaluation 评估体系

## 目录结构

```
evaluation/
├── raw/                     # 实验人员拖入的原始 output（未经处理）
│   ├── constrained_decoding/    # 约束解码生成结果
│   └── free_decoding/           # 自由生成结果
│
├── cleaned/                 # 清洗后的诗歌内容 + 大模型评分 txt（同目录放）
│   ├── constrained_decoding/
│   └── free_decoding/
│
├── results/                 # 所有评分 JSON 输出
│   ├── auto_score/              # pypinyin 规则自动评分
│   │   ├── constrained_decoding/
│   │   │   ├── {Model}/             # per-file 详细 evaluation JSON
│   │   │   └── {Model}_summary.json # per-model 汇总
│   │   ├── free_decoding/
│   │   └── comparison.json         # 约束 vs 自由 对比
│   └── llm_judge/               # 大模型三维度评分汇总
│       ├── full.json                # 完整版（含逐作品明细）
│       └── compact.json             # 精简版（仅汇总，15 分制）
│
├── csv/                     # 最终分析用 CSV
│   ├── per_work_detail.csv      # 表1：逐作品明细
│   └── summary.csv              # 表2：按模型×约束×诗/词汇总
│
├── clean_output.py          # ① 清洗脚本
├── auto_score.py            # ② 规则评分脚本
├── parse_llm_scores.py      # ③ LLM 评分解析脚本
├── generate_csv.py          # ④ CSV 生成脚本
└── README.md
```

## 数据流

```
experiments 生成
      │
      ▼ (实验人员手动拖入)
evaluation/raw/
      │
      ├──→ ① clean_output.py  ──→  evaluation/cleaned/
      │                                    │
      │                                    ▼ (实验人员手动放入大模型评分 txt)
      │                               evaluation/cleaned/  (作品 + 评分同目录)
      │
      ├──→ ② auto_score.py    ──→  evaluation/results/auto_score/
      │      （读取 cleaned/，与 LLM 评分使用同一份清洗后文本）
      │
      └──→ ③ parse_llm_scores.py ──→ evaluation/results/llm_judge/
                                            │
                                            ▼
                                      ④ generate_csv.py
                                            │
                                            ▼
                                     evaluation/csv/
```

## 脚本说明

### ① clean_output.py — 数据清洗

- **输入**: `raw/constrained_decoding/` 和 `raw/free_decoding/` 中的 per-theme txt 文件
- **输出**: `cleaned/` 中按 `{Model}-{唐诗/宋词}.txt` 合并的文件
- **功能**: 解析原始输出中的 `[title]` 和 `[content]`，去重合并

### ② auto_score.py — pypinyin 规则评分

- **输入**: `cleaned/` 中按 `{Model}-{唐诗/宋词}.txt` 合并后的清洗文本
- **输出**: `results/auto_score/` 中 per-file JSON + per-model summary JSON
- **评分维度**: 结构(40%) + 平仄(30%) + 押韵(30%)
- **命令行**:
  ```bash
  python auto_score.py --meter ../Songci_Meter --input cleaned --output results/auto_score
  ```

### ③ parse_llm_scores.py — 大模型评分解析

- **输入**: `cleaned/` 中 `*评分(N).txt` 格式的评分文件
- **输出**: `results/llm_judge/full.json` + `compact.json`
- **功能**: 自动匹配任意评分模型（不限于 Deepseek），支持多轮平均

### ④ generate_csv.py — CSV 汇总

- **输入**: `results/auto_score/` + `results/llm_judge/full.json`
- **输出**: `csv/per_work_detail.csv` + `csv/summary.csv`

## CSV 表说明

### per_work_detail.csv（表1）

每行一首作品，约束与自由成对排列。

| 列名 | 说明 |
|---|---|
| 模型 | 生成模型名称 |
| 体裁 | 具体诗体/词牌（如 七律、南乡子） |
| 主题 | 写作主题 |
| 作品内容 | 诗歌正文 |
| 是否约束 | 是=约束解码 / 否=自由生成 |
| 结构分数 | 规则评分 — 字数结构得分 |
| 平仄分数 | 规则评分 — 平仄得分 |
| 押韵分数 | 规则评分 — 押韵得分 |
| 形式规则总分 | 规则评分 — 加权总分 |
| 语言分数 | LLM 评分 — 语言维度 |
| 逻辑分数 | LLM 评分 — 逻辑维度 |
| 意境分数 | LLM 评分 — 意境维度 |
| 写作总分 | LLM 评分 — 加权总分 |

### summary.csv（表2）

按模型×是否约束×诗/词 汇总均值。

| 列名 | 说明 |
|---|---|
| 模型 | 生成模型名称 |
| 是否约束 | 是/否 |
| 诗/词 | 诗=唐诗 / 词=宋词 |
| 结构均分 | 结构分数均值 |
| 平仄均分 | 平仄分数均值 |
| 押韵均分 | 押韵分数均值 |
| 形式规则总分 | 规则加权总分均值 |
| 语言均分 | 语言分数均值 |
| 逻辑均分 | 逻辑分数均值 |
| 意境均分 | 意境分数均值 |
| 写作均分 | LLM 加权总分均值 |

## 典型工作流

```bash
# 1. 将原始 output 拖入 raw/ 对应子目录

# 2. 清洗数据
python clean_output.py

# 3. 规则评分
python auto_score.py

# 4. 将大模型评分 txt 放入 cleaned/ 对应子目录（与作品文件同目录）

# 5. 解析 LLM 评分
python parse_llm_scores.py

# 6. 生成 CSV
python generate_csv.py
```
