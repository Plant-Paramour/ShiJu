# 诗矩接口文档

本文档描述当前仓库实际提供的 Python 生成接口和 JavaScript 格律检查接口。项目目前不包含 HTTP JSON 服务、命令行参数解析器或持久化数据库。

## 1. 快速开始

最小运行入口是 `shiju.app.run`。实际使用时，只需构造 `AppConfig`，再调用 `run`：

```python
from pathlib import Path

from shiju.app import AppConfig, ModelConfig, SamplingConfig, run
from shiju.tasks import TaskRequest

config = AppConfig(
    model=ModelConfig(
        model_name="本地模型路径或 HuggingFace 模型名",
        quantization="8bit",
    ),
    task=TaskRequest(
        meter_type="排律",
        form_name="七言排律",
        num_lines=12,
        theme="秋江怀远",
        rhyme_dict_name="Pinshui",
        use_thinking=False,
        strict_polyphonic=True,
    ),
    sampling=SamplingConfig(temperature=0.7, top_p=0.8, top_k=20),
    rhyme_dir=Path("Rhyme"),
    meter_source=Path("Songci_Meter"),
    output_dir=Path("output"),
)
run(config)
```

`run` 会加载 tokenizer 和模型，建立韵书与词表索引，创建任务运行时，并执行 `num_generations` 次生成。生成结果会打印到标准输出；`save_output=True` 时追加保存到 `output/<form_name>/<form_name>.txt`。

## 2. 公共配置接口

### 2.1 `ModelConfig`

位置：`shiju.app.ModelConfig`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `model_name` | `str` | 必填 | HuggingFace 模型名或本地模型目录。传给 `AutoTokenizer` 和 `AutoModelForCausalLM`。 |
| `quantization` | `str` | `"8bit"` | 量化方式。支持 `none`、`fp16`、`float16`、空字符串、`8bit`、`int8`、`8`、`4bit`、`int4`、`nf4`、`4`。 |

### 2.2 `SamplingConfig`

位置：`shiju.app.SamplingConfig`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `max_new_tokens` | `int` | `4096` | 单次生成最多新增的 token 数。 |
| `temperature` | `float` | `0.6` | 采样温度，值越高随机性越强。 |
| `top_p` | `float` | `0.95` | nucleus sampling 的累计概率阈值。 |
| `top_k` | `int` | `20` | 每步最多保留的高概率 token 数。 |
| `min_p` | `float` | `0.0` | 最低相对概率阈值，传给模型生成接口。 |

### 2.3 `AppConfig`

位置：`shiju.app.AppConfig`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `model` | `ModelConfig` | 必填 | 模型及量化配置。 |
| `task` | `TaskRequest` | 必填 | 诗体、主题、韵书和诗体专用选项。 |
| `sampling` | `SamplingConfig` | `SamplingConfig()` | 采样配置。 |
| `use_constraints` | `bool` | `True` | 是否安装 `ConstrainedLogitsProcessor`。关闭后只执行模型原生采样。 |
| `num_generations` | `int` | `1` | 连续生成的作品数量。每次生成都会创建独立状态和约束会话。 |
| `save_output` | `bool` | `True` | 是否将生成结果追加保存到输出文件。 |
| `rhyme_dir` | `Path` | `Path("Rhyme")` | 韵书 JSON 所在目录。 |
| `meter_source` | `Path` | `Path("Songci_Meter")` | 宋词模板目录。唐诗、排律和汉俳不会读取该目录。 |
| `output_dir` | `Path` | `Path("output")` | 输出根目录。 |
| `boundary_coherence_penalty` | `float` | `50.0` | 句内节奏边界处命中常见双字词时的 logits 惩罚。不能为负数。 |

## 3. 任务接口

### 3.1 `TaskRequest`

位置：`shiju.tasks.TaskRequest`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `meter_type` | `str` | 必填 | 任务类型。当前支持 `宋词`、`唐诗`、`汉俳`、`排律`。 |
| `form_name` | `str` | 必填 | 具体格式名称。见下方支持矩阵。 |
| `theme` | `str` | 必填 | 主题或内容方向，会进入 prompt。 |
| `rhyme_dict_name` | `str` | 必填 | 韵书文件名去掉 `.json` 的名称，如 `Xinyun`、`Pinshui`。 |
| `task_type` | `str` | `"instruction"` | 任务模式。宋词支持 `instruction`、`zero-shot`、`one-shot`、`completion`；唐诗、排律、汉俳当前只支持 `instruction`。 |
| `requirement` | `str` | `""` | 附加创作要求，会组合进 prompt。 |
| `use_thinking` | `bool` | `True` | 是否允许模型使用思考模式。关闭时由 prompt 追加 `/no_think`。 |
| `strict_polyphonic` | `bool` | `True` | 多音字策略。`True` 要求所有读音都满足当前约束；`False` 只需存在一个合法读音。该配置同时作用于平仄、押韵和诗体规则。 |
| `cipai_data_path` | `str` | `"PoeTone-main/data/cipai_data.json"` | 宋词非 instruction 任务所需的外部词牌数据路径。当前仓库不提供该文件。 |
| `num_lines` | `int | None` | `None` | 排律句数。排律必须单独指定为不少于 10 的偶数；其他诗体忽略该字段。 |
| `hanpai` | `HanpaiOptions` | 默认实例 | 汉俳专用配置。 |
| `tang` | `TangOptions` | 默认实例 | 绝句与律诗专用配置。 |
| `pailv` | `PailvOptions` | 默认实例 | 排律专用配置。 |

`strict_polyphonic` 是全局任务参数，而不是只对排律生效的开关。底层直接使用 `VocabIndex` 或 verifier 时，也可以通过同名参数单独选择模式。

### 3.2 `HanpaiOptions`

位置：`shiju.tasks.HanpaiOptions`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `line_pattern` | `str` | `"5-7-5"` | 汉俳行长。支持 `5-7-5`、`575`、`五七五`、`3-5-3`、`353`、`三五三`。 |
| `season_word` | `str | None` | `None` | 指定必须出现在正文中的季语。 |
| `season_words` | `tuple[str, ...]` | `()` | 季语候选集合。模型必须选择其中一个；不能与 `season_word`、`season` 同时设置。 |
| `season` | `str | None` | `None` | 只指定季节，由模型自行选择具体季语；不能与另外两项同时设置。 |
| `forbid_isolated_level` | `bool` | `False` | 是否禁止孤平。 |
| `allow_aojiu` | `bool` | `False` | 是否允许使用邻位平声拗救。 |
| `forbid_three_same_ending` | `bool` | `False` | 是否禁止句尾三连平或三连仄。 |
| `rhyme_scheme` | `str | None` | `None` | 押韵格式。支持 `AAA`、`ABA`、`BAA` 或不押韵。 |

`HanpaiOptions.__post_init__` 会校验三种季语配置互斥、字符串非空以及候选集合没有空值。

### 3.3 `TangOptions`

位置：`shiju.tasks.TangOptions`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `allow_aojiu` | `bool` | `False` | 是否允许绝句、律诗使用与 Web 检查器一致的本句自救、特拗交换和对句相救。 |

### 3.4 `PailvOptions`

位置：`shiju.tasks.PailvOptions`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `allow_aojiu` | `bool` | `True` | 排律是否允许拗救。排律固定平韵，首句可押可不押，偶数句押韵并锁定同一韵部。 |

### 3.5 支持矩阵

| `meter_type` | `form_name` | 主要约束 |
| --- | --- | --- |
| `宋词` | `Songci_Meter/*.json` 中存在的词牌 | 模板逐字平仄、句读、阕结构和韵组。默认选用模板 `default_variant`。 |
| `唐诗` | `五言绝句`、`七言绝句`、`五言律诗`、`七言律诗`，以及带 `仄韵` 的对应形式 | 二四六分明、替对粘、句尾平仄、押韵、孤平、拗救和三连同。 |
| `排律` | `五言排律`、`七言排律` | `num_lines` 为不少于 10 的偶数；固定平韵、偶数句押韵、替对粘及关系型格律规则。 |
| `汉俳` | `汉俳` | 三行变长布局、可选季语、孤平、拗救、三连同和 AAA/ABA/BAA 押韵。 |

格式解析函数分别为 `parse_tang_format`、`parse_pailv_format` 和 `parse_hanpai_format`。格式不支持或排律句数非法时抛出 `ValueError`。

### 3.6 格式解析函数

这些函数只做格式参数解析，不访问模型或文件。

`parse_tang_format(form_name: str) -> tuple[int, int, str]`：

| 参数 | 含义 | 返回值 |
| --- | --- | --- |
| `form_name` | 五言/七言和绝句/律诗名称；名称含“仄韵”且含“韵”时使用仄韵，否则使用平韵。 | `(line_length, num_lines, rhyme_type)`，例如 `(7, 8, "平韵")`。 |

`parse_pailv_format(form_name: str, num_lines: int | None) -> tuple[int, int]`：

| 参数 | 含义 |
| --- | --- |
| `form_name` | 必须严格为 `五言排律` 或 `七言排律`。 |
| `num_lines` | 必须是不少于 10 的偶数。 |

返回 `(line_length, num_lines)`。

`parse_hanpai_format(line_pattern: str) -> tuple[int, int, int]`：

| 参数 | 含义 |
| --- | --- |
| `line_pattern` | 支持 `5-7-5`、`575`、`五七五`、`3-5-3`、`353`、`三五三`，并兼容全角连接号、空格和 `×`。 |

返回三行字数元组，例如 `(5, 7, 5)`。

## 4. 运行时接口

### 4.1 `TaskContext`

位置：`shiju.tasks.TaskContext`

任务工厂的依赖注入对象。应用层通常不需要手动创建，但扩展诗体或测试工厂时会使用。

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `tokenizer` | `TokenizerLike` | HuggingFace tokenizer 或兼容实现。必须支持 `get_vocab`、`decode`、`encode` 和 `eos_token_id`。 |
| `vocab` | `VocabLookup` | 词表约束索引，通常是 `VocabIndex`。 |
| `lexicon` | `RhymeLexicon` | 韵书查询对象。 |
| `meter_source` | `Path` | 宋词模板根目录。 |
| `boundary_coherence_penalty` | `float` | 句读边界粘连惩罚。 |

### 4.2 `TaskRuntime`

位置：`shiju.tasks.TaskRuntime`

任务工厂返回的不可变运行时描述，包含 prompt、约束 profile、分隔符策略、候选策略和处理器配置。

| 成员 | 类型 | 含义 |
| --- | --- | --- |
| `profile` | `ConstraintProfile` | 句子布局和约束会话工厂。 |
| `messages` | `list[dict[str, str]]` | 传给 `tokenizer.apply_chat_template` 的消息列表。 |
| `separator_policy` | `SeparatorPolicy` | 控制顿号、标点和换行 token。 |
| `policy_tiers` | `tuple[PolicyTier, ...]` | 候选策略层，按顺序尝试；一层有候选即停止降级。 |
| `processor_config` | `ProcessorConfig` | logits 处理器的兜底、押韵和多音字配置。 |
| `output_transform` | `Callable[[str], str]` | 保存和输出前的文本转换，默认原样返回。 |

方法：

```python
runtime.create_processor(vocab, tokenizer, input_prompt_len)
runtime.process_output(text)
```

`create_processor` 每次调用都会新建 `GenerationStateMachine` 和约束 session，不能跨生成复用 processor。

### 4.3 `ProcessorConfig`

位置：`shiju.processor.ProcessorConfig`

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `relax_rhyme_on_empty` | `bool` | `False` | 押韵候选为空时，重试一次但忽略韵部约束。 |
| `raw_on_no_candidates` | `bool` | `False` | 当前正文候选为空时保留原始 logits，但屏蔽 EOS。 |
| `raw_after_policy_failure` | `bool` | `False` | 所有策略层拒绝时保留原始 logits。 |
| `release_constraints_after_finish` | `bool` | `False` | 诗体完成后允许生成收尾换行和 EOS。 |
| `separator_empty_returns_raw` | `bool` | `False` | 分隔符候选为空时保留原始 logits。 |
| `strict_polyphonic` | `bool` | `True` | 传给词表索引的多音字策略。 |

默认任务工厂已经为各诗体设置合适的兜底组合；业务代码一般只修改 `TaskRequest`，不直接修改此配置。

### 4.4 任务注册表

`default_task_registry() -> TaskFactoryRegistry` 返回内置注册表，默认注册四类任务：`宋词`、`唐诗`、`汉俳`、`排律`。

`TaskFactoryRegistry.register(meter_type: str, factory: TaskFactory) -> None`：

| 参数 | 含义 |
| --- | --- |
| `meter_type` | 任务类型名称；创建请求时必须与 `TaskRequest.meter_type` 一致。 |
| `factory` | 实现 `create(request, context) -> TaskRuntime` 的工厂对象。 |

`TaskFactoryRegistry.create(request: TaskRequest, context: TaskContext) -> TaskRuntime` 根据请求选择工厂；未知类型抛出 `ValueError`。通过注册表接入新诗体时，应同时补齐 prompt、profile/session、separator policy 和测试。

## 5. 数据访问接口

### 5.1 `RhymeLexicon`

位置：`shiju.data.RhymeLexicon`

构造函数：`RhymeLexicon(rhyme_dict_path: str | Path)`。参数 `rhyme_dict_path` 是韵书 JSON 路径；文件不存在或 JSON 结构无法读取时抛出异常。

| 方法 | 参数 | 返回值和含义 |
| --- | --- | --- |
| `get_pingze(char)` | 单个汉字 `char` | 该字的平仄选项列表，元素为 `"平"` 或 `"仄"`。 |
| `get_rhyme_part(char)` | 单个汉字 `char` | 该字可能属于的韵部列表。 |
| `get_rhyme_part_by_tone(char, tone)` | 汉字 `char`、平仄 `tone` | 指定平仄下的韵部列表。 |
| `iter_rhyme_entries()` | 无 | 迭代所有 `(char, part, tone)` 韵书条目。 |

不要假设一个字只有一个平仄或一个韵部。

### 5.2 `MeterTemplateRepository`

位置：`shiju.data.MeterTemplateRepository`

构造函数：`MeterTemplateRepository(source: str | Path)`，其中 `source` 是宋词模板目录。

`get(name: str, variant_name: str | None = None) -> MeterTemplate`：

| 参数 | 含义 |
| --- | --- |
| `name` | 词牌名称，对应目录中的 `<name>.json`。 |
| `variant_name` | 可选变体名；省略时使用 JSON 中的 `default_variant`。 |

返回解析后的 `MeterTemplate`。模板文件不存在、变体不存在或模板结构非法时抛出 `ValueError`。

### 5.3 `VocabIndex`

位置：`shiju.vocab.VocabIndex`

构造函数：`VocabIndex(tokenizer: TokenizerLike, rhyme_lexicon: RhymeLookup)`。构造时会完整遍历 tokenizer 词表并建立索引，词表很大时可能耗时和占用较多内存。

| 方法 | 参数 | 返回值和含义 |
| --- | --- | --- |
| `text_for_token(token_id)` | token ID | 通过 tokenizer 解码并清洗后的 token 文本；未索引时返回空字符串。 |
| `common_bigrams()` | 无 | 所有已索引的双字 token 集合，用于边界粘连惩罚。 |
| `resolve_patterns(patterns, ignore_rhyme=False, strict_polyphonic=True)` | 允许模式序列、是否忽略押韵、是否严格处理多音字 | 满足模式的 token ID 集合。 |

## 6. 底层扩展协议

### `TokenizerLike`

```python
class TokenizerLike(Protocol):
    eos_token_id: int
    def get_vocab(self) -> dict[str, int]: ...
    def decode(self, token_ids, **kwargs) -> str: ...
    def encode(self, text: str, **kwargs) -> list[int]: ...
```

`decode([token_id])` 是约束判断 token 文本的唯一可信来源。不能用词表 key 直接代替，因为 BPE token 可能含前导空格或特殊编码。

### `VocabLookup`

必须提供 `text_for_token`、`common_bigrams` 和 `resolve_patterns`。`resolve_patterns(patterns, ignore_rhyme=False, strict_polyphonic=True)` 返回允许的 token ID 集合。

### `ConstraintProfile` / `ConstraintSession`

`ConstraintProfile` 提供 `layout` 和 `create_session()`；session 提供：

```python
allowed_patterns(state, max_length) -> Sequence[AllowedPattern]
observe_text(state, text) -> None
candidate_context(state) -> Any
```

session 允许保存押韵锁定、当前联次等生成内状态，因此必须每次生成新建。

### `CandidatePolicy` / `PolicyTier`

策略签名为：

```python
evaluate(token_id, context) -> float | None
```

返回 `None` 表示拒绝 token，返回非负浮点数表示接受并追加 penalty。`PolicyTier` 内的策略全部通过后才接受候选；多个 tier 按顺序降级。

## 7. 输出协议与错误

模型输出必须包含 `[content]` 标记。可选的 `[title]`、`[plan]` 或 `<think>` 内容由 prompt 约定；约束处理器只在检测到 `[content]` 后启用。

常见错误：

| 异常 | 常见原因 |
| --- | --- |
| `ValueError: 不支持的生成类型` | `meter_type` 不在注册表中。 |
| `ValueError: 排律格式...` | `form_name` 不是五言/七言排律，或 `num_lines` 不是不少于 10 的偶数。 |
| `ValueError: 汉俳格式...` | `line_pattern` 不在支持集合中。 |
| `ValueError: 文件不存在` | 韵书、宋词模板路径不正确。 |
| `ValueError: 不支持的量化参数` | `ModelConfig.quantization` 不受支持。 |
| `RuntimeError` | 模型加载、CUDA、显存或生成阶段错误；应用层会清理 CUDA cache 后重新抛出。 |

## 8. 浏览器端格律检查接口

位置：`web/prosody-checker/core.js`。这些接口不依赖 DOM，可以在浏览器模块、Node 测试或未来的服务端 JavaScript 中直接导入。所有分数范围均为 `0` 到 `100`。

### 8.1 `buildLexicon(rawData)`

将韵书 JSON 构造成查询对象。

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `rawData` | `Record<string, Record<string, string[]>>` | `韵部 -> 声调名称 -> 汉字列表`。声调名称含“平”归为平声，其余归为仄声。 |

返回对象提供 `lookup(char)`。查询结果包含 `tones`、`parts`、`partsByTone` 和 `polyphonic`；未收录字返回空集合。`polyphonic` 表示该字在当前韵书中存在多个“平仄 + 韵部”组合，不等同于现代汉语词典的全部读音定义。

### 8.2 文本与模板接口

| 接口 | 参数 | 返回值和含义 |
| --- | --- | --- |
| `parsePoem(text)` | `text: string` | 提取 `[content]` 后正文，按标点和换行分句，只保留汉字，返回 `string[]`。 |
| `flattenMeter(variant)` | `variant: object` | 将宋词变体展平为逐句模板、韵组和阕尾位置。`、` 会拆成两个检查分句，`/` 只作为节奏边界移除。 |
| `formatMeterTemplate(variant)` | `variant: object` | 返回用于页面展示的分阕模板；移除 `/`，原样保留 `中` 和 `、`。 |

### 8.3 评分接口

| 接口 | 参数 | 含义 |
| --- | --- | --- |
| `evaluateSongci(text, variant, lexicon, options?)` | 正文、词牌变体、韵书查询对象和可选判定参数 | 按指定词牌变体逐字检查；拗救参数不适用于模板型宋词。 |
| `evaluateTang(text, options, lexicon)` | `options.charCount` 为 `5` 或 `7`；`options.form` 为 `jueju` 或 `lvshi` | 按用户指定的字数和绝句/律诗检查。除 `jueju` 外当前均按八句律诗处理。 |
| `evaluatePailv(text, lexicon, options?)` | 正文、韵书查询对象和可选判定参数 | 自动从有效句中判定五言或七言，并要求不少于十句的偶数句。 |
| `evaluateBestTangForm(text, lexicon, options?, current?)` | 正文、韵书查询对象、可选判定参数和当前诗式 | 比较五/七言绝句、律诗与排律，返回结构、平仄、押韵三项算术平均分最高的候选；同分时优先保持当前诗式。 |
| `evaluateHaiku(text, lexicon, options?)` | 正文、韵书查询对象和可选判定参数 | 按三行 `5-7-5` 检查。其平仄规则是本项目汉俳约束的前端适配，不是论文原评估器的覆盖项。 |

`text` 接受中文标点、英文标点和换行。`lexicon` 必须是 `buildLexicon` 的返回值。宋词 `variant` 对应 `Songci_Meter/*.json` 中 `variants` 的单个元素。

判定参数：

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `strictPolyphonic` | `boolean` | `false` | `true` 时一个字的所有韵书读音均须满足当前平仄或韵部；`false` 时存在一个合法读音即可。 |
| `polyphonicMode` | `automatic`、`strict` 或 `permissive` | 未指定 | `automatic` 按平仄、韵部和拗救上下文选定读法；另两项分别对应严格和放行。未指定时兼容旧的 `strictPolyphonic` 参数。 |
| `allowAoJiu` | `boolean` | `false` | 是否接受唐诗、排律和俳句中符合规则的相邻平声拗救。宋词忽略此参数。 |

唐诗的两个参数与 `charCount`、`form` 放在同一个 `options` 对象中；其他评分器使用独立的第四或第三个可选参数对象。

统一返回对象：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `kind` | `songci`、`tang`、`pailv` 或 `haiku` | 评分器类型。 |
| `structureScore` | `number` | 结构分，保留最多两位小数。 |
| `tonalScore` | `number` | 平仄分，保留最多两位小数。 |
| `rhymeScore` | `number` | 押韵分，保留最多两位小数。 |
| `lines` | `EvaluatedLine[]` | 分句及逐字标注，页面据此渲染黑体和红色。 |
| `errors` | `Set<string>` | 错误位置集合，键格式为 `句索引:字索引`，索引从 0 开始。 |
| `issues` | `string[]` | 字数、句数等结构问题。 |
| `rhymeGroups` | `RhymeGroup[]` | 每个韵组的韵脚、主韵部、匹配数和组分。 |
| `polyphonicDecisions` | `PolyphonicDecision[]` | 自动模式下已按上下文选定读法的多音字位置、声调、韵部、理由和展示文案。 |
| `stats` | `object` | 参与评分字符数、匹配数及诗体专用统计。 |

逐字对象的关键字段为：`char` 原字、`tone` 展示平仄、`tones` 可选平仄、`polyphonic` 是否多音、`error` 是否错误、`expected` 当前位置期望。自动模式还会提供 `selectedTone`、`selectedPart` 和 `decisionReason`。一个字同时是多音字和错误字时，错误状态优先显示红色粗体。

### 8.4 分数公式

- 宋词结构分：`字数正确的对应分句数 / 模板分句总数 * 100`。缺句按不正确计，超出模板的分句不增加分数，与论文评估代码一致。
- 唐诗结构分：先计算 `字数正确的实有句数 / 实有句数 * 100`；总句数不符合所选绝句或律诗时，结构分最高为 `50`，与论文评估代码一致。
- 排律结构分：沿用唐诗的逐句字数比例；少于十句或句数为奇数时，结构分最高为 `50`。
- 俳句结构分：`字数正确的对应行数 / 3 * 100`，期望行长依次为 `5、7、5`。
- 平仄分：`(参与检查字符数 - 不合规位置数) / 参与检查字符数 * 100`。宋词等价写作 `合规字符数 / 参与检查字符数 * 100`。
- 单韵组押韵分：`命中主韵部的韵脚数 / 该组有效韵脚数 * 100`。主韵部是该组韵脚中出现次数最多的韵部。
- 宋词存在多个韵组时，最终押韵分取各韵组得分的算术平均。

页面展示结构、平仄和押韵三项分数；智能选式另用三项算术平均进行候选比较并在摘要显示。它不是论文批量评估中的加权总分；结构错误同时列在 `issues`。

### 8.5 页面参数映射

| 页面参数 | 可选值 | 作用 |
| --- | --- | --- |
| 体裁 | `tang`、`songci`、`haiku`、`pailv` | 选择评分器。 |
| 韵书 | `Xinyun`、`Pinshui`、`Cilin`、`Tongyun` | 分别加载中华新韵、平水韵、词林正韵、中华通韵。 |
| 唐诗字数 | `5`、`7` | 每句期望字数。 |
| 唐诗篇式 | `jueju`、`lvshi` | 期望四句或八句。 |
| 宋词词牌 | `Songci_Meter/*.json` 文件 | 选择词牌模板。 |
| 宋词变体 | 模板 `variants[].name` | 选择具体逐字格律和韵组。 |
| 多音字 | `automatic`、`strict`、`permissive` | 映射为 `polyphonicMode`，其中自动模式为页面默认值。 |
| 智能选式 | 开、关 | 唐诗和排律开启时调用 `evaluateBestTangForm`；宋词和俳句禁用。默认开启。 |
| 拗救 | 开、关 | 映射为 `allowAoJiu`。默认关闭；宋词模式禁用。 |

无论采用哪种多音字模式，多音字仍以黑体标注。自动模式会展示系统采用的上下文读法，未能由规则唯一确定的字仍保留“平/仄”供人工复核。严格模式的量词语义与生成接口 `TaskRequest.strict_polyphonic=True` 一致。
