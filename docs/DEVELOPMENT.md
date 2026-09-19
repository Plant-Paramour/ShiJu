# 诗矩工程开发指南

本文档面向继续维护和工程化改造本项目的开发者。内容以当前实现为准；如果设计发生变化，应同时更新 `CLAUDE.md`、`docs/API.md` 和本文件。

## 1. 代码分层

```text
main.py                 示例启动配置，不承载业务逻辑
shiju/app.py            模型加载、生成循环、输出保存
shiju/tasks.py          任务请求、工厂注册、运行时组装
shiju/processor.py      通用 HuggingFace LogitsProcessor
shiju/state.py          诗文正文状态机和控制器
shiju/constraints.py    布局、平仄、押韵等约束 session
shiju/candidates.py     token 解码、候选文本和可达性判断
shiju/policies.py       候选拒绝规则、惩罚和策略降级
shiju/vocab.py          tokenizer 词表离线索引
shiju/data.py           韵书和宋词模板读取
shiju/domain.py         跨模块不可变领域类型
shiju/tone_rules.py     可组合的平仄规则
shiju/prompts.py        各诗体 prompt 构建
```

依赖方向应保持为：

```text
app -> tasks -> processor -> state / constraints / policies / vocab
                                  \-> domain / data / candidates / tone_rules
```

`domain.py`、`data.py` 和 `tone_rules.py` 不应反向依赖应用层；诗体差异优先放在 profile/session、policy 或 separator policy 中，不要复制一套新的生成循环。

## 2. 一次生成的生命周期

1. `app.run` 加载 tokenizer、模型和指定韵书。
2. `VocabIndex` 遍历 tokenizer 词表，索引纯汉字/英文 token 的平仄模式及韵部。
3. 任务工厂根据 `TaskRequest` 创建 profile、prompt、separator policy、policy tiers 和 `ProcessorConfig`。
4. 每次作品生成时，`TaskRuntime.create_processor` 新建状态机和 session。
5. processor 等待 `[content]`，之后解析正文增量并推进状态。
6. 文本阶段先根据 profile 得到 `AllowedPattern`，再由 `VocabLookup` 映射为 token ID。
7. 候选依次通过 policy tier；separator 阶段只开放标点、顿号或换行 token。
8. 诗体完成后根据配置生成收尾换行/EOS，应用层解码并执行 `output_transform`。

状态推进依赖 tokenizer 解码出的正文增量，而不是模型 token 的数量。一个 token 可能包含多个汉字，也可能包含前导空格；所有位置计算都以清洗后的正文字符为准。

## 3. 约束处理顺序

正文 token 的实际筛选顺序如下：

1. `GenerationController` 根据行、字位置和下一处边界限制 token 长度。
2. profile 生成当前可接受的平仄/押韵模式。
3. `VocabIndex.resolve_patterns` 过滤词表 token，并按 `strict_polyphonic` 处理多音字。
4. `TangVerifierPolicy`、`HanpaiVerifierPolicy` 等做跨字符规则验证。
5. 通用重复惩罚、边界粘连惩罚等策略调整 logits。
6. 若当前 tier 没有任何候选，按 `ProcessorConfig` 选择降级、放宽韵部或保留原始 logits。

### 多音字语义

严格模式的判断是：候选字的所有读音都必须满足当前约束；放行模式的判断是：至少存在一个合法读音。这个量词必须在所有相关层保持一致：

- 词表层：严格模式要求 token 的所有平仄组合都命中允许模式。
- 规则层：严格模式要求所有组合通过规则；放行模式只要求一个组合通过。
- 动态规划层：严格模式要求存在同一条后续路径，使当前前缀的所有读音都能完成；不能对每种读音分别选择互相冲突的未来路径。

新增规则时，必须明确它对多音字采用哪一种量词，并补充两种模式的测试。

### 关系型诗体动态规划

`has_viable_tang_completion` 会将当前句字符转换为平仄选项，并在剩余位置上搜索完整声调路径。最终路径检查：

- 二四六位置的基本平仄；
- 允许时的拗救条件；
- 句尾平/仄要求；
- 三连平或三连仄；
- 孤平及拗救。

该判断使用 `lru_cache`，因为目标句最长为七字，状态空间很小。若未来支持更长句式或词级语言约束，不要直接扩大暴力枚举，应将状态压缩为位置、最近声调、韵部和规则状态，并保留缓存或迭代式 DP。

当前 DP 推演的是声调可达性，词义、对仗和自然度仍由模型 prompt、重复惩罚及后续评估负责；不要把 prompt 要求误认为硬约束。

## 4. 如何新增诗体

建议按以下边界实现：

1. 在 `domain.py` 中复用现有 `LineLayout`、`GenerationLayout` 和 `AllowedPattern`；只有确有跨诗体语义时才新增领域类型。
2. 在 `constraints.py` 新增 profile 和 session，负责布局、位置平仄和韵部状态，不直接操作 logits。
3. 如需特殊的候选校验，在 `policies.py` 增加 `CandidatePolicy`；返回 `None` 表示拒绝，不要在 policy 中修改状态机。
4. 如需特殊标点或换行，在 `processor.py` 增加 `SeparatorPolicy` 实现。
5. 在 `prompts.py` 增加 prompt 构建函数。
6. 在 `tasks.py` 增加 options、factory，并在 `default_task_registry` 注册。
7. 在 `tests/` 为格式解析、profile/session、processor 和工厂分别添加测试。
8. 更新 `docs/API.md` 的支持矩阵、参数表和异常说明。

不要为新诗体复制 `app.run` 或 `ConstrainedLogitsProcessor`。只有当生成协议本身改变时，才考虑扩展应用层。

## 5. 数据格式

### 韵书

`Rhyme/*.json` 使用以下结构：

```json
{
  "韵部名称": {
    "平声名称": ["字一", "字二"],
    "仄声名称": ["字三"]
  }
}
```

`RhymeLexicon` 将包含“平”的声调名称归为 `平`，其他声调归为 `仄`。同一字可以存在多个声调或多个韵部，因此不能用单值字典替代现有查询接口。

### 宋词模板

每个 `Songci_Meter/<词牌>.json` 应包含：

```json
{
  "name": "词牌名",
  "default_variant": "变体名",
  "variants": [
    {
      "name": "变体名",
      "rhyme_type": "平韵",
      "number_of_stanzas": 1,
      "stanza1": {
        "num_lines": 1,
        "lines": ["中平中仄/平仄"]
      }
    }
  ]
}
```

实际模板可使用：

- `平`：固定平声；
- `仄`：固定仄声；
- `中`：平仄均可；
- `/`：句内 token 不得跨越的边界；
- `、`：强制顿号。

模板由 `MeterTemplateRepository` 解析为 `MeterTemplate`、`MeterLine` 和 `LineLayout`。不要在 processor 中重新解析原始 JSON。

## 6. 测试与质量门槛

本仓库测试不依赖真实模型，使用 fake tokenizer、fake vocab 和 fake lexicon 覆盖核心行为。运行：

```bash
pip install -e ".[dev]"
pytest
```

修改约束相关代码时至少检查：

- 候选 token 不跨越句读边界；
- 句尾和押韵锁定仍然正确；
- 多音字严格/放行模式各有正反例；
- 当前前缀不存在完整合法路径时会提前拒绝；
- 生成多次时 session 和韵部状态不泄漏；
- processor 在候选为空时遵守配置的降级行为。

真实模型生成属于集成验证，不应作为单元测试依赖。执行集成验证时，应记录模型名、tokenizer 版本、韵书、任务配置和采样参数，保证结果可复现。

## 7. 工程化改造建议

当前 `app.run` 同时负责依赖加载、任务构造、生成和文件输出。后续拆分服务化或批处理时，建议保持以下边界：

- `ModelRunner`：只负责模型/tokenizer 生命周期和一次生成；
- `TaskBuilder`：只负责从请求构造 `TaskRuntime`；
- `GenerationSession`：封装一次作品的 processor、状态和元数据；
- `OutputSink`：负责文件、数据库或 API 响应，不让 `app.py` 直接决定存储；
- `GenerationResult`：明确保存原始模型输出、清洗后输出、错误和配置快照。

服务层不应共享 `GenerationController`、constraint session 或 processor 实例。它们包含可变的当前行、韵部锁定和文本进度，只能属于单次生成。

## 8. 独立格律检查前端

`web/prosody-checker/` 是与模型生成链路解耦的静态子应用：

```text
index.html              # 表单和结果语义结构
styles.css              # 响应式样式
app.js                  # DOM、数据加载、缓存和渲染
core.js                 # 无 DOM 的解析与评分纯函数
tests/core.test.mjs     # Node 核心回归测试
README.md               # 运行、部署和评分说明
```

浏览器按选择按需加载一个韵书，并缓存对应 Promise；六个宋词模板在初始化时合计只有数 KB。输入不会发送到服务器，渲染统一使用 `textContent`。单次检查只遍历作品字符和少量韵组，时间复杂度近似 `O(n + r)`，其中 `n` 是正文字符数，`r` 是参与押韵的韵脚数。

页面将多音字模式映射到 `strictPolyphonic`，将拗救开关映射到 `allowAoJiu`。新增平仄或韵部规则时必须同时测试严格/放行两个量词；新增孤平规则时必须测试拗救开关两种状态。宋词是逐字模板检查，不应用拗救。

桌面布局保持单视口工作区：检查前输入面板紧凑居中，检查后左右分栏，逐句结果使用自适应网格；超长内容只允许面板内部滚动。`900px` 以下恢复页面滚动并切换单列，避免用压缩字号牺牲移动端可读性。

开发服务器必须从仓库根目录启动，因为页面通过 `../../Rhyme/` 和 `../../Songci_Meter/` 读取共享数据。不要直接双击 `index.html`，浏览器的 `file://` 模式会阻止模块和 JSON 请求。

部署时将仓库根目录中的 `web/prosody-checker/`、`Rhyme/`、`Songci_Meter/` 保持相对层级交给 Nginx、Caddy 或对象存储静态托管即可。当前数据规模和计算量不需要应用后端；2 核 2G 服务器只承担压缩、缓存和静态文件传输。只有需要保存作品、用户鉴权、跨设备历史记录或统一审计时，才增加后端 API。

修改评分逻辑时至少运行：

```bash
node --test web/prosody-checker/tests/core.test.mjs
pytest
```

同时在浏览器复验唐诗、宋词、俳句、排律切换，宋词模板中的 `中`，错误字/多音字样式，以及窄屏无页面级横向溢出。

## 9. 服务化边界

双服务器部署的完整约定见 `docs/DISTRIBUTED_ARCHITECTURE.md`。新增代码必须遵守：

- `apps/api` 不得导入 `torch`、`transformers`、`shiju.app` 或 `shiju.generation`；
- GPU 模型只能由 `ModelRunner` 持有，单次任务不得重复加载模型；
- HTTP 层只负责校验、鉴权和任务状态，不直接创建格律 session；
- Worker 任务之间不得共享 controller、processor 或 rewrite session；
- 重写固定内容由程序拼接，禁止依赖模型复述原文；
- 数据库变更必须新增 `apps/api/migrations/NNN_name.sql`，不得在线修改旧 migration。

本地运行控制面需要 `pip install -e ".[api]"`；GPU Worker 需要按 CUDA 环境安装
PyTorch 后执行 `pip install -e ".[gpu]"`。
