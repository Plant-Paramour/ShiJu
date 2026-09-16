# CLAUDE.md

## 项目概述

诗矩是一个基于 HuggingFace `LogitsProcessor` 的中国古典诗词约束生成系统。系统在模型逐 token 生成时，根据字数、句读、平仄和韵部规则筛选候选 token。

当前仓库只保留核心生成链路，支持两种约束来源：

- 字间规则约束型：当前用于五言、七言绝句和律诗，通过二四六分明、句尾平仄、押韵、孤平和三连同等规则动态计算约束。
- 格律模板严格约束型：当前用于宋词，从 `Songci_Meter/*.json` 读取逐字平仄、句读、阕结构和韵组。

俳句、排律、骈文、曲牌和歌词尚未接入。

## 当前结构

```text
main.py                 # 保持可直接运行的薄入口
shiju/
  app.py                # 模型加载、生成循环和输出
  domain.py             # 公共领域类型
  data.py               # 韵书与格律模板仓储
  vocab.py              # tokenizer 词表约束索引
  state.py              # 通用生成状态机
  constraints.py        # 模板型与字间规则型约束会话
  policies.py           # 候选 token 校验与惩罚策略
  processor.py          # 通用 LogitsProcessor
  prompts.py            # Prompt 构建
  tasks.py              # 任务工厂与配置
Rhyme/*.json            # 韵书
Songci_Meter/*.json     # 宋词格律模板
tests/                  # 不依赖真实模型的单元与回归测试
output/                 # 生成结果
```

## 生成数据流

1. `RhymeLexicon` 加载指定韵书。
2. 宋词任务由 `MeterTemplateRepository` 解析一次模板；Prompt 与约束会话共享同一变体。
3. `VocabIndex` 遍历 tokenizer 词表，建立平仄模式和韵部到 token ID 的索引。
4. 任务工厂创建通用状态机、对应的约束会话及候选策略。
5. 通用 `ConstrainedLogitsProcessor` 解析 `[content]` 后的正文增量，推进状态并过滤 logits。

## 运行

项目当前使用本地代码配置：

```bash
python main.py
```

运行测试：

```bash
pip install -e ".[dev]"
pytest
```

`main.py` 中保留模型路径、量化、诗体、主题、采样参数和输出设置。`one-shot` 与 `completion` Prompt 仍需要仓库外部的 `PoeTone-main/data/cipai_data.json`，当前仓库不提供该数据，因此不是自包含工作流。

依赖文件：

- `requirements.txt`：当前本地环境版本。
- `new_requirements.txt`：服务器 CUDA 12.8 环境版本及安装说明。

## 数据约定

### 韵书

`Rhyme/*.json` 使用“韵部 -> 声调名称 -> 字列表”结构。运行时将包含“平”的声调归入平声，其余归入仄声。

### 宋词模板

每个文件包含 `name`、`default_variant` 和 `variants`。变体包含：

- `rhyme_type`
- `number_of_stanzas`
- `stanzaN.num_lines`
- `stanzaN.lines`
- `stanzaN.rhyme_X_positions`

格律字符串中：

- `平`、`仄`：固定平仄。
- `中`：平仄均可。
- `/`：token 不得跨越的句内节奏边界，不直接输出。
- `、`：固定输出的顿号。

## 关键行为

- `[title]` 和 `[content]` 是程序与模型输出之间的协议；约束仅在检测到 `[content]` 后启用。
- 每次生成必须创建新的状态机和约束会话，避免韵部锁定与正文状态泄漏到下一次生成。
- BPE token 必须通过 `tokenizer.decode([token_id])` 获取真实文本。
- 唐诗保留完整 verifier、核心规则兜底和最终放行三级策略。
- 句内 token 不得跨越 `/` 指定的边界；边界两侧形成常见双字词时会施加粘连惩罚。

本仓库不包含评估模块，也没有拆分出的诗体专用处理器文件；说明文档只描述当前实际存在的核心生成链路。
