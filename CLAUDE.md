# CLAUDE.md


虚拟环境： `C:\ProgramData\anaconda3\envs\ShiJu`

## 项目概述

诗矩是一个基于 HuggingFace `LogitsProcessor` 的中国古典诗词约束生成系统。系统在模型逐 token 生成时，根据字数、句读、平仄和韵部规则筛选候选 token。

当前仓库只保留核心生成链路，支持两种约束来源：

- 字间规则约束型：当前用于五言、七言绝句、律诗、排律，以及 5-7-5、3-5-3 汉俳。唐诗和排律通过二四六分明、替对粘、句尾平仄、押韵、孤平和三连同等规则动态计算约束；汉俳按任务配置组合孤平、拗救、三连同和押韵规则。
- 格律模板严格约束型：当前用于宋词，从 `Songci_Meter/*.json` 读取逐字平仄、句读、阕结构和韵组。

骈文、曲牌和歌词尚未接入。

## 工程文档

- `docs/API.md`：面向调用者的 Python 接口、配置参数、支持矩阵、底层协议和错误说明。
- `docs/DEVELOPMENT.md`：面向开发者的模块边界、生成生命周期、约束顺序、扩展方法、数据格式和测试门槛。
- `web/prosody-checker/README.md`：独立格律检查前端的运行、评分规则、数据依赖和部署说明。

修改公共配置、任务工厂、约束协议或数据格式时，必须同步更新以上文档。`CLAUDE.md` 只保留项目级快速上下文，详细参数以 `docs/API.md` 为准。

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
evaluation/             # 论文批量评估代码与评估输入输出
web/prosody-checker/    # 可独立部署的浏览器端格律检查系统
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

运行格律检查前端（必须从仓库根目录启动静态服务器）：

```bash
python -m http.server 8000 --bind 127.0.0.1
```

浏览器访问 `http://127.0.0.1:8000/web/prosody-checker/`。前端核心测试使用
`node --test web/prosody-checker/tests/core.test.mjs`。

`main.py` 中保留模型路径、量化、诗体、主题、采样参数和输出设置。`one-shot` 与 `completion` Prompt 仍需要仓库外部的 `PoeTone-main/data/cipai_data.json`，当前仓库不提供该数据，因此不是自包含工作流。

汉俳通过 `TaskRequest(meter_type="汉俳", ...)` 接入，并使用 `HanpaiOptions` 配置：

```python
from shiju.tasks import HanpaiOptions, TaskRequest

TaskRequest(
    meter_type="汉俳",
    form_name="汉俳",
    theme="初秋离别",
    rhyme_dict_name="Xinyun",
    use_thinking=False,           # 启用 /no_think，无模型思考过程
    strict_polyphonic=True,       # True：所有读音均须合法；False：存在合法读音即可
    hanpai=HanpaiOptions(
        line_pattern="5-7-5",       # 或 3-5-3
        season_word="寒蝉",          # 指定一个季语
        season_words=(),             # 或提供多个候选，由模型选择一个
        season=None,                 # 或只指定季节；三者均不填时自动选择明显季语
        forbid_isolated_level=True,
        allow_aojiu=True,
        forbid_three_same_ending=True,
        rhyme_scheme="ABA",         # AAA、ABA、BAA 或 None
    ),
)
```

汉俳正文固定输出三行，行间只换行。五字句按 2/3、七字句按 2/2/3 设置 token 跨界限制；生成时在内部句读处强制插入临时顿号，让模型明确感知节奏段，保存结果前自动移除。正文始终必须包含明显季语；未选择的平仄格律与押韵规则不会被解码器隐式启用。

排律通过 `TaskRequest(meter_type="排律", ...)` 接入。`form_name` 仅使用“`五言排律`”或“`七言排律`”，句数由独立的 `num_lines` 参数指定，例如 `num_lines=16`。句数必须是不少于十句的偶数且不设上限。排律固定使用平韵，首句可押可不押，偶数句押韵并锁定同一韵部；约束层负责字数、替对粘、平仄、孤平、拗救和三连同，逐联对仗仅通过提示词要求。

关系型诗体会在每个候选 token 后用动态规划检查当前句是否仍存在合法的完整平仄路径，提前过滤会同时触发孤平、三平尾或三仄尾等组合死路。`TaskRequest.strict_polyphonic` 控制多音字策略：默认 `True` 时所有读音都必须满足当前约束；设为 `False` 时，只要至少一个读音满足约束即可放行。

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

`evaluation/` 保留论文批量评估程序；`web/prosody-checker/` 将其中的平仄与押韵业务改写为无模型、无后端状态的浏览器端检查器。两者与 `shiju/` 的约束生成链路相互独立，但共享 `Rhyme/` 和 `Songci_Meter/` 数据。

## 工程化边界

- 当前公开运行入口是 `shiju.app.run(AppConfig)`，不是 HTTP API；服务化时应在外层增加请求校验和结果存储。
- 服务化入口现位于 `apps/api` 和 `apps/gpu_worker`；部署和工具协议以 `docs/DISTRIBUTED_ARCHITECTURE.md` 为准。控制面不得导入 GPU 依赖。
- 格律检查器公开的是 `web/prosody-checker/core.js` 的纯函数接口，不提供 HTTP JSON API；当前数据规模下优先静态部署，不在 2 核 2G 服务器上增加无必要的应用进程。
- 格律检查器默认采用多音字放行、拗救关闭；页面可切换严格多音字模式和拗救。宋词只应用多音字模式，不应用拗救。
- 一次生成必须独占自己的 `GenerationStateMachine`、constraint session 和 logits processor，禁止跨请求共享。
- 新诗体应通过 profile/session、policy、separator policy 和 task factory 接入，不能复制模型生成循环。
- 约束规则属于硬约束，prompt 中的主题、对仗、自然度等要求仍属于模型软约束；两者不能混写。
- `strict_polyphonic` 默认开启。新增涉及多音字的规则时，必须同时验证严格模式和放行模式。
