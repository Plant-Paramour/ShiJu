from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .auth import hash_password, verify_password
from .database import Database


class UserRepository:
    ROLE_LEVELS = {"user": 0, "admin": 10, "developer": 20}
    def __init__(self, database: Database):
        self.database = database

    def seed_defaults(self) -> None:
        with self.database.connect() as connection:
            for username in ("Test1", "Test2", "Test3"):
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE username = ?", (username,)
                ).fetchone()
                if exists is None:
                    connection.execute(
                        "INSERT INTO users(id, username, password_hash, display_name) VALUES (?, ?, ?, ?)",
                        (str(uuid.uuid4()), username, hash_password(username), username),
                    )
            admin_password = __import__("os").getenv("SHIJU_ADMIN_PASSWORD", "admin123")
            exists = connection.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone()
            if exists is None:
                connection.execute(
                    "INSERT INTO users(id, username, password_hash, display_name, role) VALUES (?, ?, ?, ?, 'admin')",
                    (str(uuid.uuid4()), "admin", hash_password(admin_password), "管理员"),
                )
            else:
                connection.execute("UPDATE users SET role='admin' WHERE username='admin'")
            developer_username = __import__("os").getenv("SHIJU_DEVELOPER_USERNAME", "").strip()
            if developer_username:
                connection.execute(
                    "UPDATE users SET role='developer' WHERE username=?",
                    (developer_username,),
                )

    def migrate_legacy_tree(self) -> None:
        """为旧线性对话补齐父链，并建立可继续使用的主分支。"""
        with self.database.connect() as connection:
            conversations = connection.execute("SELECT id FROM conversations").fetchall()
            for conversation in conversations:
                conversation_id = conversation[0]
                branch = connection.execute("SELECT id FROM conversation_branches WHERE conversation_id=? LIMIT 1", (conversation_id,)).fetchone()
                if branch is not None:
                    continue
                rows = connection.execute("SELECT id,parent_message_id FROM messages WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,)).fetchall()
                previous = None
                for row in rows:
                    if row[1] is None and previous is not None:
                        connection.execute("UPDATE messages SET parent_message_id=?,updated_at=COALESCE(updated_at,created_at) WHERE id=?", (previous, row[0]))
                    previous = row[0]
                now = time.time()
                connection.execute("INSERT INTO conversation_branches(id,conversation_id,head_message_id,title,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), conversation_id, previous, "主线", 1, now, now))

    @staticmethod
    def _user(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "created_at": row["created_at"],
            "role": row["role"] if "role" in row.keys() else "user",
            "bio": row["bio"] if "bio" in row.keys() else "",
            "avatar_url": row["avatar_url"] if "avatar_url" in row.keys() else None,
            "notify_on_reaction": bool(row["notify_on_reaction"]) if "notify_on_reaction" in row.keys() else True,
        }

    def update_profile(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {key: fields[key] for key in ("display_name", "bio", "avatar_url", "notify_on_reaction") if key in fields}
        if not allowed: return self.get(user_id)
        assignments = ",".join(f"{key}=?" for key in allowed)
        with self.database.connect() as connection:
            connection.execute(f"UPDATE users SET {assignments} WHERE id=?", (*allowed.values(), user_id))
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def list_users(self, *, q: str | None = None, page: int = 1, limit: int = 50) -> dict[str, Any]:
        page = max(page, 1); limit = min(max(limit, 1), 100); offset = (page - 1) * limit
        clause = "WHERE username LIKE ? OR display_name LIKE ?" if q else ""; args = (f"%{q.strip()}%", f"%{q.strip()}%") if q else ()
        with self.database.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM users {clause}", args).fetchone()[0]
            rows = connection.execute(f"SELECT * FROM users {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return {"items": [self._user(row) for row in rows], "page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}

    def create_user(self, username: str, password: str, display_name: str | None = None, role: str = "user") -> dict[str, Any]:
        if role not in self.ROLE_LEVELS:
            raise ValueError("invalid role")
        user_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            connection.execute("INSERT INTO users(id,username,password_hash,display_name,role) VALUES (?,?,?,?,?)", (user_id, username.strip(), hash_password(password), (display_name or username).strip(), role))
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._user(row)

    def register(self, username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
        return self.create_user(username, password, display_name, "user")

    def create_reset_token(self, username: str) -> str | None:
        import hashlib
        import secrets
        with self.database.connect() as connection:
            row = connection.execute("SELECT id FROM users WHERE username=?", (username.strip(),)).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            connection.execute("INSERT INTO auth_reset_tokens(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], time.time() + 3600, time.time()))
        return token

    def reset_password(self, token: str, new_password: str) -> bool:
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.database.connect() as connection:
            row = connection.execute("SELECT user_id FROM auth_reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (token_hash, time.time())).fetchone()
            if not row:
                return False
            connection.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), row["user_id"]))
            connection.execute("UPDATE auth_reset_tokens SET used_at=? WHERE token_hash=?", (time.time(), token_hash))
        return True

    def set_role(self, user_id: str, role: str) -> bool:
        if role not in self.ROLE_LEVELS:
            raise ValueError("invalid role")
        with self.database.connect() as connection:
            result = connection.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        return result.rowcount == 1

    def delete_user(self, user_id: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("DELETE FROM users WHERE id=? AND username <> 'admin'", (user_id,))
        return result.rowcount == 1

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self._user(row)

    def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None or not verify_password(old_password, row[0]): return False
            connection.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
        return True

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def list_conversations(self, user_id: str, *, include_deleted: bool = False, sort: str = "updated") -> list[dict[str, Any]]:
        order = "created_at ASC" if sort == "created" else "updated_at DESC"
        deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT id, title, folder_id, deleted_at, created_at, updated_at FROM conversations WHERE user_id = ? {deleted_clause} ORDER BY {order}",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, user_id: str, title: str = "新建对话") -> dict[str, Any]:
        now = time.time()
        conversation_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, user_id, title[:15] or "新建对话", now, now),
            )
            connection.execute(
                "INSERT INTO conversation_branches(id, conversation_id, root_message_id, head_message_id, title, is_active, created_at, updated_at) VALUES (?, ?, NULL, NULL, ?, 1, ?, ?)",
                (str(uuid.uuid4()), conversation_id, "主线", now, now),
            )
        return {"id": conversation_id, "title": title[:15] or "新建对话", "created_at": now, "updated_at": now}

    def get_conversation(self, conversation_id: str, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, title, folder_id, deleted_at, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (conversation_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        *,
        status: str = "completed",
        job_id: str | None = None,
        parent_message_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        message_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            version_group_id = message_id
            version_number = 1
            if parent_message_id:
                parent = connection.execute(
                    "SELECT id, role, version_group_id, COALESCE(MAX(version_number), 1) AS version_number FROM messages WHERE id = ? AND conversation_id = ?",
                    (parent_message_id, conversation_id),
                ).fetchone()
                if parent is None:
                    raise ValueError("parent message not found in conversation")
                archived = connection.execute(
                    "SELECT version_group_id, MAX(version_number) AS version_number FROM message_versions WHERE id = ? AND conversation_id = ? GROUP BY version_group_id",
                    (parent_message_id, conversation_id),
                ).fetchone()
                # A version group represents edited messages only. Normal chat
                # turns also have a parent, but must start a new group.
                source = parent if parent and parent["role"] == role == "user" else None
                if source:
                    version_group_id = source["version_group_id"] or parent_message_id
                    version_number = int(source["version_number"] or 1) + 1
            inserted = connection.execute(
                "INSERT INTO messages(id, conversation_id, role, content, created_at, status, job_id, version_group_id, version_number, parent_message_id, turn_id, updated_at) SELECT ?, id, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM conversations WHERE id = ? AND user_id = ?",
                (message_id, role, content, now, status, job_id, version_group_id, version_number, parent_message_id, turn_id, now, conversation_id, user_id),
            )
            if inserted.rowcount != 1:
                raise ValueError("conversation not found")
            connection.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '新建对话' AND ? = 'user' THEN substr(?, 1, 15) ELSE title END WHERE id = ? AND user_id = ?",
                (now, role, content, conversation_id, user_id),
            )
            if version_group_id != message_id:
                connection.execute(
                    "INSERT OR IGNORE INTO message_versions(id, conversation_id, version_group_id, version_number, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), conversation_id, version_group_id, version_number, role, content, now),
                )
        return {
            "id": message_id,
            "role": role,
            "content": content,
            "status": status,
            "job_id": job_id,
            "created_at": now,
            "version_group_id": version_group_id,
            "version_number": version_number,
            "parent_message_id": parent_message_id,
            "turn_id": turn_id,
            "updated_at": now,
        }

    def update_message(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        *,
        content: str,
        status: str,
        job_id: str | None = None,
    ) -> None:
        now = time.time()
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE messages
                SET content = ?, status = ?, job_id = ?, updated_at = ?
                WHERE id = ? AND conversation_id IN (
                    SELECT id FROM conversations WHERE id = ? AND user_id = ?
                )
                """,
                (content, status, job_id, now, message_id, conversation_id, user_id),
            )
            if updated.rowcount != 1:
                raise ValueError("message not found")
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )

    def truncate_messages_from(self, message_id: str, conversation_id: str, user_id: str) -> bool:
        """Remove an edited user message and every response after it."""
        now = time.time()
        with self.database.connect() as connection:
            target = connection.execute(
                """
                SELECT m.created_at FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id = ? AND m.conversation_id = ? AND c.user_id = ? AND m.role = 'user'
                """,
                (message_id, conversation_id, user_id),
            ).fetchone()
            if target is None:
                return False
            current = connection.execute(
                "SELECT id, version_group_id, version_number, role, content, created_at FROM messages WHERE id = ? AND conversation_id = ?",
                (message_id, conversation_id),
            ).fetchone()
            if current:
                connection.execute(
                    "INSERT OR IGNORE INTO message_versions(id, conversation_id, version_group_id, version_number, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (current["id"], conversation_id, current["version_group_id"] or current["id"], current["version_number"], current["role"], current["content"], current["created_at"]),
                )
            connection.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ? AND (created_at > ? OR (created_at = ? AND id >= ?))
                """,
                (conversation_id, target["created_at"], target["created_at"], message_id),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )
        return True

    def list_messages(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT m.id, m.role, m.content, m.status, m.job_id, m.created_at, m.updated_at, m.version_group_id, m.version_number, m.parent_message_id, m.turn_id FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.conversation_id = ? AND c.user_id = ? ORDER BY m.created_at, m.id",
                (conversation_id, user_id),
            ).fetchall()
            versions = connection.execute(
                "SELECT version_group_id, version_number, role, content, created_at FROM message_versions WHERE conversation_id = ? ORDER BY version_group_id, version_number",
                (conversation_id,),
            ).fetchall()
            branches = [dict(row) for row in connection.execute("SELECT id,root_message_id,head_message_id FROM conversation_branches WHERE conversation_id=?", (conversation_id,)).fetchall()]
        by_group: dict[str, list[dict[str, Any]]] = {}
        for version in versions:
            item = dict(version)
            by_group.setdefault(item["version_group_id"], []).append(item)
        result = []
        for row in rows:
            item = dict(row)
            group = item.get("version_group_id") or item["id"]
            # A polluted legacy group may contain the assistant reply that was
            # created after a user message. Versions are role-local; never show
            # an assistant row as a user edit version.
            history = [version for version in by_group.get(group, []) if version["role"] == item["role"]]
            if not any(v["version_number"] == item.get("version_number") for v in history):
                if item["role"] == "user":
                    history.append({"version_group_id": group, "version_number": item.get("version_number", 1), "role": item["role"], "content": item["content"], "created_at": item["created_at"]})
            history.sort(key=lambda v: v["version_number"])
            item["versions"] = history if item["role"] == "user" else []
            result.append(item)
        by_id = {item["id"]: item for item in result}
        branch_members: dict[str, str] = {}
        for branch in branches:
            current_id = branch.get("head_message_id")
            visited: set[str] = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                current = by_id.get(current_id)
                if current is None:
                    break
                if current_id == branch.get("root_message_id") or current_id not in branch_members:
                    branch_members[current_id] = branch["id"]
                current_id = current.get("parent_message_id")
        by_parent: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
        for item in result:
            by_parent.setdefault((item.get("parent_message_id"), item["role"]), []).append(item)
        for item in result:
            siblings = by_parent.get((item.get("parent_message_id"), item["role"]), [])
            item["branch_id"] = branch_members.get(item["id"])
            item["siblings"] = [{"id": sibling["id"], "content": sibling["content"], "created_at": sibling["created_at"], "branch_id": branch_members.get(sibling["id"])} for sibling in siblings]
        return result

    def get_message(self, message_id: str, conversation_id: str, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND m.conversation_id=? AND c.user_id=?",
                (message_id, conversation_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def message_exists(self, message_id: str | None, conversation_id: str) -> bool:
        if not message_id:
            return False
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM messages WHERE id=? AND conversation_id=?", (message_id, conversation_id)
            ).fetchone() is not None

    def resolve_conversation_access(self, conversation_id: str, actor_id: str) -> str | None:
        """返回会话所有者；developer 可读取任意未归档会话。"""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT c.user_id FROM conversations c WHERE c.id=? AND c.deleted_at IS NULL AND (c.user_id=? OR EXISTS (SELECT 1 FROM users u WHERE u.id=? AND u.role='developer'))",
                (conversation_id, actor_id, actor_id),
            ).fetchone()
        return row[0] if row else None

    def list_message_tree(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        messages = self.list_messages(conversation_id, user_id)
        children: dict[str | None, list[str]] = {}
        for message in messages:
            children.setdefault(message.get("parent_message_id"), []).append(message["id"])
        for message in messages:
            message["children_ids"] = children.get(message["id"], [])
            message["depth"] = 0
            parent_id = message.get("parent_message_id")
            seen: set[str] = set()
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                parent = next((item for item in messages if item["id"] == parent_id), None)
                if parent is None:
                    message["tree_error"] = "missing_parent"
                    break
                message["depth"] += 1
                parent_id = parent.get("parent_message_id")
            if parent_id in seen:
                message["tree_error"] = "cycle"
        return messages

    def create_branch(self, conversation_id: str, user_id: str, *, root_message_id: str | None = None, head_message_id: str | None = None, title: str = "主线", activate: bool = True) -> dict[str, Any]:
        branch_id = str(uuid.uuid4())
        now = time.time()
        with self.database.connect() as connection:
            if connection.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=? AND deleted_at IS NULL", (conversation_id, user_id)).fetchone() is None:
                raise ValueError("conversation not found")
            if activate:
                connection.execute("UPDATE conversation_branches SET is_active=0 WHERE conversation_id=?", (conversation_id,))
            connection.execute(
                "INSERT INTO conversation_branches(id,conversation_id,root_message_id,head_message_id,title,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (branch_id, conversation_id, root_message_id, head_message_id, title[:80] or "主线", 1 if activate else 0, now, now),
            )
        return {"id": branch_id, "conversation_id": conversation_id, "root_message_id": root_message_id, "head_message_id": head_message_id, "title": title[:80] or "主线", "is_active": activate, "created_at": now, "updated_at": now}

    def list_branches(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT b.* FROM conversation_branches b JOIN conversations c ON c.id=b.conversation_id WHERE b.conversation_id=? AND c.user_id=? ORDER BY b.created_at,b.id", (conversation_id, user_id)).fetchall()
        return [dict(row) for row in rows]

    def get_active_branch(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        branches = self.list_branches(conversation_id, user_id)
        active = next((item for item in branches if item["is_active"]), None)
        if active:
            return active
        return self.create_branch(conversation_id, user_id)

    def ensure_branch_for_message(self, conversation_id: str, user_id: str, message_id: str | None = None) -> dict[str, Any]:
        branch = self.get_active_branch(conversation_id, user_id)
        if message_id:
            with self.database.connect() as connection:
                row = connection.execute("SELECT id FROM messages WHERE id=? AND conversation_id=?", (message_id, conversation_id)).fetchone()
            if row is None:
                raise ValueError("message not found")
            branch = self.create_branch(conversation_id, user_id, root_message_id=message_id, head_message_id=message_id, title="编辑分支")
        return branch

    def list_path_messages(self, conversation_id: str, user_id: str, head_message_id: str | None = None) -> list[dict[str, Any]]:
        messages = self.list_messages(conversation_id, user_id)
        by_id = {item["id"]: item for item in messages}
        if head_message_id is None:
            return []
        path = []
        current = by_id.get(head_message_id)
        while current:
            path.append(current)
            current = by_id.get(current.get("parent_message_id"))
        path.reverse()
        return path

    def activate_branch(self, branch_id: str, conversation_id: str, user_id: str) -> bool:
        with self.database.connect() as connection:
            valid = connection.execute("SELECT 1 FROM conversation_branches b JOIN conversations c ON c.id=b.conversation_id WHERE b.id=? AND b.conversation_id=? AND c.user_id=?", (branch_id, conversation_id, user_id)).fetchone()
            if not valid:
                return False
            connection.execute("UPDATE conversation_branches SET is_active=0 WHERE conversation_id=?", (conversation_id,))
            connection.execute("UPDATE conversation_branches SET is_active=1,updated_at=? WHERE id=?", (time.time(), branch_id))
        return True

    def activate_branch_for_message(self, message_id: str, conversation_id: str, user_id: str) -> str | None:
        """根据目标消息所在的分支激活分支，避免前端使用过期 branch_id。"""
        branches = self.list_branches(conversation_id, user_id)
        messages = self.list_messages(conversation_id, user_id)
        by_id = {item["id"]: item for item in messages}
        active = next((item for item in branches if item["is_active"]), None)
        candidates = []
        for branch in branches:
            current_id = branch.get("head_message_id")
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                if current_id == message_id:
                    candidates.append(branch)
                    break
                current = by_id.get(current_id)
                if current is None:
                    break
                current_id = current.get("parent_message_id")
            if branch.get("root_message_id") == message_id and branch not in candidates:
                candidates.append(branch)
        candidate = next((item for item in candidates if not active or item["id"] != active["id"]), None)
        if candidate is None:
            candidate = next(iter(candidates), None)
        if candidate is None or not self.activate_branch(candidate["id"], conversation_id, user_id):
            return None
        return candidate["id"]

    def update_branch_head(self, branch_id: str, message_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE conversation_branches SET head_message_id=?,updated_at=? WHERE id=?", (message_id, time.time(), branch_id))

    def update_branch_root_if_empty(self, branch_id: str, message_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE conversation_branches SET root_message_id=? WHERE id=? AND root_message_id IS NULL", (message_id, branch_id))

    def save_poem(self, user_id: str, job_id: str, job_request: dict[str, Any], result: dict[str, Any]) -> None:
        candidates = result.get("candidates") or []
        if not candidates and result.get("full_text"):
            candidates = [{"text": result["full_text"]}]
        with self.database.connect() as connection:
            for ordinal, candidate in enumerate(candidates, start=1):
                self._save_candidate_poem(connection, user_id, job_id, ordinal, job_request, candidate, candidate.get("evaluation"))

    def save_candidate_poem(
        self,
        user_id: str,
        job_id: str,
        ordinal: int,
        job_request: dict[str, Any],
        candidate: dict[str, Any],
        evaluation: dict[str, Any] | None = None,
    ) -> None:
        with self.database.connect() as connection:
            self._save_candidate_poem(connection, user_id, job_id, ordinal, job_request, candidate, evaluation)

    @staticmethod
    def _save_candidate_poem(connection, user_id, job_id, ordinal, job_request, candidate, evaluation) -> None:
        content = str(candidate.get("content") or candidate.get("text") or candidate.get("full_text") or candidate.get("display_text") or "").strip()
        if not content:
            return
        title = str(candidate.get("title") or job_request.get("theme") or "未命名诗作").strip()
        meter_type = str(job_request.get("meter_type") or "")
        work_type = str(job_request.get("work_type") or meter_type or "其他")
        evaluation_json = json.dumps(evaluation, ensure_ascii=False, separators=(",", ":")) if evaluation else None
        connection.execute(
            """
            INSERT INTO poems(id,user_id,job_id,title,content,meter_type,form_name,created_at,work_type,candidate_ordinal,evaluation_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id,candidate_ordinal) DO UPDATE SET
                title=excluded.title,content=excluded.content,meter_type=excluded.meter_type,
                form_name=excluded.form_name,work_type=excluded.work_type,
                evaluation_json=COALESCE(excluded.evaluation_json,poems.evaluation_json)
            """,
            (str(uuid.uuid4()), user_id, job_id, title, content, meter_type, job_request.get("form_name", ""), time.time(), work_type, ordinal, evaluation_json),
        )

    def list_poems(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT p.id,p.job_id,p.candidate_ordinal,p.title,p.content,p.work_type,p.meter_type,p.form_name,p.created_at,p.evaluation_json,p.is_public,EXISTS(SELECT 1 FROM poem_favorites f WHERE f.poem_id=p.id AND f.user_id=?) AS favorite,u.id AS author_id,u.username AS author_username,u.display_name AS author_display_name FROM poems p JOIN users u ON u.id=p.user_id WHERE p.user_id = ? ORDER BY p.created_at DESC",
                (user_id, user_id),
            ).fetchall()
        return [self._poem_row(row) for row in rows]

    def update_poem(self, poem_id: str, user_id: str, fields: dict[str, Any]) -> bool:
        allowed = {key: fields[key] for key in ("title", "content", "work_type", "meter_type", "form_name", "is_public") if key in fields}
        if not allowed: return False
        assignments = ",".join(f"{key}=?" for key in allowed)
        with self.database.connect() as connection:
            result = connection.execute(f"UPDATE poems SET {assignments} WHERE id=? AND user_id=?", (*allowed.values(), poem_id, user_id))
        return result.rowcount == 1

    def delete_poem(self, poem_id: str, user_id: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("DELETE FROM poems WHERE id=? AND user_id=?", (poem_id, user_id))
        return result.rowcount == 1

    def list_favorite_poems(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT p.id,p.job_id,p.candidate_ordinal,p.title,p.content,p.work_type,p.meter_type,p.form_name,p.created_at,p.evaluation_json,p.is_public,1 AS favorite,u.id AS author_id,u.username AS author_username,u.display_name AS author_display_name FROM poems p JOIN poem_favorites f ON f.poem_id=p.id JOIN users u ON u.id=p.user_id WHERE f.user_id=? ORDER BY f.created_at DESC", (user_id,)).fetchall()
        return [self._poem_row(row) for row in rows]

    @staticmethod
    def _poem_row(row) -> dict[str, Any]:
        value = dict(row)
        value["evaluation"] = json.loads(value.pop("evaluation_json")) if value.get("evaluation_json") else None
        return value

    def soft_delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("UPDATE conversations SET deleted_at=?, updated_at=? WHERE id=? AND user_id=? AND deleted_at IS NULL", (time.time(), time.time(), conversation_id, user_id))
        return result.rowcount == 1

    def restore_conversation(self, conversation_id: str, user_id: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("UPDATE conversations SET deleted_at=NULL, updated_at=? WHERE id=? AND user_id=?", (time.time(), conversation_id, user_id))
        return result.rowcount == 1

    def rename_conversation(self, conversation_id: str, user_id: str, title: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?", (title[:15] or "新建对话", time.time(), conversation_id, user_id))
        return result.rowcount == 1

    def move_conversation(self, conversation_id: str, user_id: str, folder_id: str | None) -> bool:
        with self.database.connect() as connection:
            if folder_id is not None and connection.execute("SELECT 1 FROM conversation_folders WHERE id=? AND user_id=?", (folder_id, user_id)).fetchone() is None:
                return False
            result = connection.execute("UPDATE conversations SET folder_id=?, updated_at=? WHERE id=? AND user_id=?", (folder_id, time.time(), conversation_id, user_id))
        return result.rowcount == 1

    def list_folders(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT id,name,created_at,updated_at FROM conversation_folders WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_folder(self, user_id: str, name: str) -> dict[str, Any]:
        now = time.time(); folder_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            connection.execute("INSERT INTO conversation_folders(id,user_id,name,created_at,updated_at) VALUES (?,?,?,?,?)", (folder_id, user_id, name[:120] or "未命名文件夹", now, now))
        return {"id": folder_id, "name": name[:120] or "未命名文件夹", "created_at": now, "updated_at": now}

    def update_folder(self, folder_id: str, user_id: str, name: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("UPDATE conversation_folders SET name=?,updated_at=? WHERE id=? AND user_id=?", (name[:120], time.time(), folder_id, user_id))
        return result.rowcount == 1

    def list_poem_collections(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT c.id,c.name,c.created_at,c.updated_at,COUNT(i.poem_id) AS count FROM poem_collections c LEFT JOIN poem_collection_items i ON i.collection_id=c.id WHERE c.user_id=? GROUP BY c.id ORDER BY c.updated_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_collection_items(self, collection_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("""SELECT p.id,p.job_id,p.candidate_ordinal,p.title,p.content,p.work_type,p.meter_type,p.form_name,p.created_at,p.evaluation_json,p.is_public,EXISTS(SELECT 1 FROM poem_favorites f WHERE f.poem_id=p.id AND f.user_id=?) AS favorite,u.id AS author_id,u.username AS author_username,u.display_name AS author_display_name
                FROM poem_collection_items i JOIN poem_collections c ON c.id=i.collection_id JOIN poems p ON p.id=i.poem_id JOIN users u ON u.id=p.user_id WHERE i.collection_id=? AND c.user_id=? ORDER BY i.created_at DESC""", (user_id, collection_id, user_id)).fetchall()
        return [self._poem_row(row) for row in rows]

    def create_poem_collection(self, user_id: str, name: str) -> dict[str, Any]:
        now = time.time(); collection_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            connection.execute("INSERT INTO poem_collections(id,user_id,name,created_at,updated_at) VALUES (?,?,?,?,?)", (collection_id, user_id, name[:120] or "未命名合集", now, now))
        return {"id": collection_id, "name": name[:120] or "未命名合集", "created_at": now, "updated_at": now, "count": 0}

    def update_poem_collection(self, collection_id: str, user_id: str, name: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("UPDATE poem_collections SET name=?,updated_at=? WHERE id=? AND user_id=?", (name[:120], time.time(), collection_id, user_id))
        return result.rowcount == 1

    def delete_poem_collection(self, collection_id: str, user_id: str) -> bool:
        with self.database.connect() as connection:
            result = connection.execute("DELETE FROM poem_collections WHERE id=? AND user_id=?", (collection_id, user_id))
        return result.rowcount == 1

    def set_favorite(self, user_id: str, poem_id: str, favorite: bool) -> bool:
        with self.database.connect() as connection:
            exists = connection.execute("SELECT 1 FROM poems WHERE id=?", (poem_id,)).fetchone()
            if exists is None: return False
            if favorite:
                connection.execute("INSERT OR IGNORE INTO poem_favorites(user_id,poem_id,created_at) VALUES (?,?,?)", (user_id, poem_id, time.time()))
            else:
                connection.execute("DELETE FROM poem_favorites WHERE user_id=? AND poem_id=?", (user_id, poem_id))
        return True

    def collection_item(self, collection_id: str, poem_id: str, user_id: str, add: bool) -> bool:
        with self.database.connect() as connection:
            owned = connection.execute("SELECT 1 FROM poem_collections WHERE id=? AND user_id=?", (collection_id, user_id)).fetchone()
            poem = connection.execute("SELECT 1 FROM poems WHERE id=?", (poem_id,)).fetchone()
            if owned is None or poem is None: return False
            if add:
                connection.execute("INSERT OR IGNORE INTO poem_collection_items(collection_id,poem_id,created_at) VALUES (?,?,?)", (collection_id, poem_id, time.time()))
            else:
                connection.execute("DELETE FROM poem_collection_items WHERE collection_id=? AND poem_id=?", (collection_id, poem_id))
        return True
