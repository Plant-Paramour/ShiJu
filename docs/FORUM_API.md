# 论坛、用户与管理员 API

论坛功能已接入现有 FastAPI 控制面，数据使用同一个 SQLite 数据库。除分区列表、主题列表、主题详情、用户搜索外，其余写操作均需要登录。

## 论坛

- `GET /v1/forum/sections`：分区列表和主题/回复统计。
- `GET /v1/forum/sections/{section_id}/threads?page=1&limit=20&q=`：主题分页。
- `POST /v1/forum/sections/{section_id}/threads`：创建主题，正文支持 Markdown 文本。
- `GET /v1/forum/threads/{thread_id}`：主题详情并增加浏览量。
- `PATCH/DELETE /v1/forum/threads/{thread_id}`：作者编辑/删除；管理员可管理任意主题。
- `GET/POST /v1/forum/threads/{thread_id}/replies`：回复分页和创建。
- `PATCH/DELETE /v1/forum/replies/{reply_id}`：作者编辑/删除，管理员可管理任意回复。
- `POST /v1/forum/reports`：举报主题或回复，二者必须且只能提供一个。

普通登录用户默认可以在未单独配置权限的分区发帖；管理员可以将用户权限设为 `none`、`read`、`write` 或 `moderate`。

## 用户

- `GET /v1/profile/me`、`PATCH /v1/profile/me`：读取和更新显示名、简介、头像地址。
- `GET /v1/forum/users/{user_id}`：公开用户资料。
- `GET /v1/forum/users/search?q=`：搜索用户。
- `POST/DELETE /v1/forum/users/{user_id}/follow`：关注/取消关注。
- `GET /v1/forum/following`：当前用户的关注列表。

## 管理员

管理员默认账号为 `admin`，默认密码为 `admin123`；生产环境可用 `SHIJU_ADMIN_PASSWORD` 覆盖首次创建密码，并应立即修改密码。

- `GET /v1/admin/stats`：用户、分区、主题、回复、举报统计。
- `GET/POST/PATCH/DELETE /v1/admin/users...`：用户列表、创建、编辑角色、删除。
- `POST/PATCH/DELETE /v1/admin/sections...`：分区管理。
- `GET/PUT /v1/admin/sections/{section_id}/permissions...`：分区权限管理。
- `GET/PATCH /v1/admin/reports...`：举报审核和处理。
