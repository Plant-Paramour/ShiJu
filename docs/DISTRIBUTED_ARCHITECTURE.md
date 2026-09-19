# 诗矩双服务器架构

本文档规定诗矩从本地脚本演进为“常驻控制面 + 按需 GPU Worker”的实现边界。当前
MVP 不包含用户、论坛、真实 Agent 和云厂商自动开关机。

## 1. 部署角色

```text
用户 / 未来 Agent
        |
        v
2 核 2G / 3M 常驻服务器
FastAPI + SQLite + 任务调度
        |
        | HTTPS，Worker 主动领取
        v
T4 GPU 服务器
Qwen3-4B 8bit + 约束解码
```

常驻服务器只安装 `.[api]` 依赖，不能导入 `torch`。它负责请求校验、Agent 工具
接口、幂等、任务持久化、租约和结果查询。T4 服务器安装 `.[gpu]`，模型权重提前
存放在本机；运行期间模型、tokenizer 和按韵书构造的词表索引保持复用。

GPU Worker 只发起出站请求，不开放公网推理端口。3M 链路只传输小型 JSON，不传输
模型、checkpoint 或大体积日志。

## 2. 代码边界

```text
shiju/
  constraints.py / state.py / policies.py / processor.py  格律核心
  contracts.py                                      公共 JSON 协议
  generation/                                       GPU 模型运行层
  rewriting/                                        指定句解析、规划和协议
  service/                                          面向 Worker 的应用服务
apps/
  api/                                              常驻控制面
  gpu_worker/                                       T4 主动领取进程
deploy/systemd/                                     两端进程配置
```

`shiju` 的格律核心不得依赖 FastAPI、SQLite 或论坛业务。`apps/api` 只能导入轻量合同、
数据库和调度代码。`apps/gpu_worker` 是唯一组合模型运行层与远程任务协议的入口。

旧的 `shiju.app.run(AppConfig)` 继续可用，但内部复用 `ModelRunner` 和
`GenerationEngine`，不再拥有独立的生成实现。

## 3. 公共工具接口

所有外部接口使用独立 Agent Bearer Token：

| 工具 | HTTP 接口 | 含义 |
| --- | --- | --- |
| `generate_poem` | `POST /v1/poetry/jobs/generate` | 提交整首生成 |
| `rewrite_poem_lines` | `POST /v1/poetry/jobs/rewrite` | 提交指定句重写 |
| `get_poetry_job` | `GET /v1/poetry/jobs/{job_id}` | 查询状态和结果 |

提交接口返回 HTTP `202`：

```json
{
  "job_id": "UUID",
  "status": "queued",
  "waiting_for_worker": true
}
```

`Idempotency-Key` 可用于安全重试。同一键和相同请求返回原任务；同一键对应不同请求
返回 `409`。

内部 Worker 使用另一枚 Bearer Token，并调用：

- `POST /internal/v1/workers/claim`
- `POST /internal/v1/jobs/{job_id}/heartbeat`
- `POST /internal/v1/jobs/{job_id}/complete`
- `POST /internal/v1/jobs/{job_id}/fail`

任务状态为 `queued`、`running`、`succeeded`、`failed`、`cancelled`。Worker 单任务
并发，心跳间隔 15 秒，默认租约 300 秒，过期任务最多尝试两次。

## 4. 引导式重写

重写不是让模型重新复述整首诗。程序解析原诗并保存每句字符跨度，模型只生成目标句，
最后由程序替换目标跨度。非目标文本因此可以做到字节级不变。

模型输出协议为：

```text
[plan]以流光与鬓雪承接岁月主题，再以诗中芳春收束不朽之意。
[rewrite]
休怕流光侵鬓雪，诗篇依旧驻芳春。
```

- `[plan]` 后只能有一句、单行、不超过 80 字且以句号结束的修改思路。
- Qwen 原生 thinking 关闭；显式规划不能包含完整候选诗句。
- `[rewrite]` 出现前，约束处理器不推进格律状态。
- `[rewrite]` 出现后，处理器只允许目标句的格律候选。
- 128 个新增 token 内没有进入 `[rewrite]` 时终止本次采样并重试一次。
- 两次协议失败返回 `MODEL_PROTOCOL_ERROR`，不能接受未约束文本。
- 固定前后文共同预锁起式与韵部；上下文无严格解返回
  `CONTEXT_CONSTRAINT_CONFLICT`。
- 支持任意一至四句，包括不连续句。固定间隔由 `RewriteController` 在同一格律会话中
  自动消费。

结果始终包含 `revision_note`、`replacements`、`full_text`、`display_text` 和格律
验证；前端或 Agent 应向用户展示 `display_text`。

## 5. SQLite 与可靠性

SQLite 使用 WAL、10 秒 busy timeout 和版本化 SQL migration。API 固定为单 Uvicorn
Worker。任务领取使用 `BEGIN IMMEDIATE`，保证同一任务不会被两个 GPU Worker 同时领取。

任务执行时记录 Worker、尝试次数和租约截止时间。Worker 异常退出后，下一个领取请求
会恢复过期任务；达到最大尝试次数后任务进入 `failed`。API 重启不会丢失排队任务和
已完成结果。

MVP 的 `ManualGpuProvider` 不调用云厂商接口。提交任务时如果没有在线 Worker，返回
`waiting_for_worker: true`，由运维人员启动 T4。未来云厂商适配器只能实现
`ensure_running/status/request_stop`，不能侵入任务或格律代码。

## 6. 部署

常驻服务器：

```bash
python -m venv .venv
.venv/bin/pip install -e ".[api]"
sudo cp deploy/systemd/shiju-api.service /etc/systemd/system/
sudo cp deploy/systemd/api.env.example /etc/shiju/api.env
```

必须替换两枚默认 Token，并将 `/var/lib/shiju` 授权给 `shiju` 用户。API 只监听
`127.0.0.1:8000`，由现有 HTTPS 反向代理对外暴露。

GPU 服务器应先按 CUDA 环境安装对应 PyTorch，再安装 `.[gpu]`，配置模型本地路径：

```bash
.venv/bin/pip install -e ".[gpu]"
sudo cp deploy/systemd/shiju-gpu-worker.service /etc/systemd/system/
sudo cp deploy/systemd/gpu-worker.env.example /etc/shiju/gpu-worker.env
```

两端均使用 journald。健康检查为 `/health/live` 和 `/health/ready`。生产环境不得使用
示例 Token，也不得让 GPU Worker 绕过 HTTPS 访问公网控制面。

## 7. 后续阶段

1. 接入云厂商 GPU 开关机 API 和空闲关机策略。
2. 用 OpenAPI Schema 注册真实 Agent 工具。
3. 增加用户、会话、作品和论坛数据库，不与任务表混写领域逻辑。
4. 数据量或控制面实例数增长后，再将 SQLite 迁移到 PostgreSQL；MVP 不引入 Redis
   或 Celery。

