from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .auth import hash_password, verify_password
from .database import Database


class UserRepository:
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
                (conversation_id, user_id, title[:120] or "新建对话", now, now),
            )
        return {"id": conversation_id, "title": title[:120] or "新建对话", "created_at": now, "updated_at": now}

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
    ) -> dict[str, Any]:
        now = time.time()
        message_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            inserted = connection.execute(
                "INSERT INTO messages(id, conversation_id, role, content, created_at, status, job_id) SELECT ?, id, ?, ?, ?, ?, ? FROM conversations WHERE id = ? AND user_id = ?",
                (message_id, role, content, now, status, job_id, conversation_id, user_id),
            )
            if inserted.rowcount != 1:
                raise ValueError("conversation not found")
            connection.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '新建对话' AND ? = 'user' THEN substr(?, 1, 80) ELSE title END WHERE id = ? AND user_id = ?",
                (now, role, content, conversation_id, user_id),
            )
        return {
            "id": message_id,
            "role": role,
            "content": content,
            "status": status,
            "job_id": job_id,
            "created_at": now,
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
                SET content = ?, status = ?, job_id = ?
                WHERE id = ? AND conversation_id IN (
                    SELECT id FROM conversations WHERE id = ? AND user_id = ?
                )
                """,
                (content, status, job_id, message_id, conversation_id, user_id),
            )
            if updated.rowcount != 1:
                raise ValueError("message not found")
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )

    def list_messages(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT m.id, m.role, m.content, m.status, m.job_id, m.created_at FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.conversation_id = ? AND c.user_id = ? ORDER BY m.created_at, m.id",
                (conversation_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

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
            result = connection.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?", (title[:120] or "新建对话", time.time(), conversation_id, user_id))
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
