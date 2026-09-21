# 诗矩轻量 Agent

`apps/agent` 是常驻控制面上的轻量工具调用 Agent。它直接实现 OpenAI-compatible
Chat Completions 工具循环，不依赖 LangChain 或其他 Agent 框架。

## 1. 能力与边界

查询工具直接读取仓库中的确定性数据：

| 工具 | 用途 |
| --- | --- |
| `list_rhyme_books` | 列出中华新韵、平水韵、词林正韵和中华通韵 |
| `lookup_rhyme` | 查询汉字的平仄、韵部及按平仄区分的韵部 |
| `get_rhyme_part` | 按韵部和可选平仄反查收录字 |
| `list_ci_meters` | 列出本地词牌及变体 |
| `get_ci_meter` | 查询词牌逐句平仄、句读、阕结构和韵组 |
| `list_supported_forms` | 查询唐诗、宋词、汉俳和排律支持范围 |

有副作用的生成操作采用“透明方案 + 受控提交”协议：

```text
用户提出创作或重写
        |
        v
prepare_generation / prepare_rewrite
保存规范化方案，公开可编辑提示词
        |
        v
网页修改并提交 / 后续纯文本确认
直接提交现有异步任务 API
```

Agent 在当前轮只调用 `prepare_*`，不得同轮调用 `submit_*`，也不得再次向用户索要确认。
Web 页面完整展示 `requirement`、候选数、诗体、篇式、韵书、多音字模式、句数和拗救配置；
用户点击“提交生成”或“提交重写”后直接进入本地模型，不再把编辑结果作为聊天消息发送给
Agent。CLI 或后续纯文本消息仍可通过明确确认调用 `submit_*`。

`submit_*` 只接收 `proposal_id`，实际任务参数取自已保存方案。宿主代码同时检查：

- 不允许在准备方案的同一轮提交；
- `proposal_id` 必须是当前方案；
- 仅预览方案时不得提交；
- 同一方案只能成功提交一次；
- 方案 ID 同时作为任务 API 的 `Idempotency-Key`。

因此，即使上游模型没有遵守系统提示，也不能提交过期方案或在提交时偷偷改参数。

## 2. 本地运行

安装控制面和 Agent 依赖：

```bash
pip install -e ".[api,agent]"
```

先配置并启动已有任务 API：

```powershell
$env:SHIJU_AGENT_TOKEN = "local-agent-token"
shiju-api
```

另开终端配置 OpenAI-compatible 服务。`SHIJU_LLM_BASE_URL` 可以是服务根地址、以
`/v1` 结尾的地址，或完整的 `/chat/completions` 地址：

```powershell
$env:SHIJU_LLM_BASE_URL = "https://provider.example/v1"
$env:SHIJU_LLM_API_KEY = "replace-with-real-key"
$env:SHIJU_LLM_MODEL = "provider-model-name"
$env:SHIJU_POETRY_API_BASE_URL = "http://127.0.0.1:8000"
$env:SHIJU_AGENT_TOKEN = "local-agent-token"
shiju-agent
```

不要把真实密钥写入仓库。CLI 支持 `/reset` 清空会话、`/exit` 退出。

通过现有网页测试时，不需要运行 `shiju-agent` CLI。增加以下开关后直接启动
`shiju-api`：

```powershell
$env:SHIJU_WEB_AGENT_ENABLED = "true"
shiju-api
```

打开 `http://127.0.0.1:8000/web/prosody-checker/#chat`。FastAPI 会同源提供网页、
韵书和词牌数据，并在服务端调用上游模型；浏览器不会收到上游 API 密钥。网页会为每个
新对话分配独立的内存会话。

当前 Web 对话入口用于本机联调，没有用户登录和用量限额。`SHIJU_WEB_AGENT_ENABLED`
默认关闭；正式对公网开放前必须先接入账号鉴权、用户级限流和调用费用配额。

查询工具不需要 GPU Worker。生成和重写会正常进入 SQLite 队列；未启动 Worker 时，
Agent 会报告 `waiting_for_worker=true`。需要实际生成结果时，再按
`docs/DISTRIBUTED_ARCHITECTURE.md` 启动 `shiju-gpu-worker`。

## 3. 对话行为

创作请求中的 `requirement` 是 Agent 提炼后实际交给生成器的详细提示，`theme` 保留简短
主题。该提示词会由宿主完整展示，并在网页中提供编辑入口。例如用户说“写一首秋夜思乡
的七绝”，Agent 应准备包含意象、情绪、章法和禁忌的完整方案，由网页公开并供用户修改；
Agent 不再重复确认，也不替网页按钮抢先提交。
未指定候选数时默认生成 1 首；`candidate_count` 支持 1 至 5。

用户要求修改并生成时，Agent 更新方案后停在可编辑方案阶段，由用户点击按钮直接提交。
局部重写还必须从当前消息或上下文取得完整原文和从 1 开始的目标句号，GPU 侧仍使用
现有重写协议保证非目标句不变。

本地 CLI 的会话和待确认方案目前只保存在内存中。接入 Web 账号体系时，应把会话消息和
待确认方案存入数据库，并按用户与会话隔离；不要把这个内存状态共享为全局单例。

## 4. 兼容性

客户端使用 `/chat/completions` 的 `tools`、`tool_choice`、`assistant.tool_calls` 和
`role=tool` 协议。上游服务必须真正支持 OpenAI-compatible 函数调用；只兼容普通文本
对话、但不返回结构化 `tool_calls` 的服务无法驱动本 Agent。

官方协议参考：[OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling)。
