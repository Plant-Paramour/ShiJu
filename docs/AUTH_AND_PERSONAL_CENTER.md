# 登录、会话与个人中心

## 测试账号

应用初始化时会自动创建三个测试用户：`Test1`、`Test2`、`Test3`。开发环境密码与用户名相同，例如 `Test1 / Test1`。

生产环境应通过 `SHIJU_AUTH_SECRET` 配置独立的签名密钥，并在首次部署后替换测试账号密码。

## 接口

- `POST /v1/auth/login`：用户名密码登录，返回 Bearer token，同时写入 HttpOnly Cookie。
- `GET /v1/auth/me`：读取当前登录用户。
- `POST /v1/auth/logout`：清除登录 Cookie。
- `GET /v1/conversations`：读取当前用户的历史对话。
- `POST /v1/conversations`：新建对话。
- `GET /v1/conversations/{id}`：读取对话及消息。
- `POST /v1/agent/chat`：登录后会将用户消息和助手回复写入对应对话；匿名调用仍保留兼容性，但不会写入用户历史。
- `GET /v1/profile/poems`：读取当前用户生成成功后自动归档的诗词。

前端将 token 保存在浏览器本地存储中，并在对话区恢复历史会话。生成任务返回 `job_id` 后，聊天区通过 `GET /v1/poetry/jobs/{job_id}` 定时更新可展开的进度气泡；任务完成时结果会进入个人中心。
