from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from .database import Database


class ForumRepository:
    """论坛数据访问层，集中处理内容、互动和分区治理。"""

    TAG_RE = re.compile(r"#([^#\s]{1,32})#")

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _author(row: Any, prefix: str = "") -> dict[str, Any]:
        return {"id": row[f"{prefix}author_id"], "username": row[f"{prefix}username"], "display_name": row[f"{prefix}display_name"] or row[f"{prefix}username"], "avatar_url": row[f"{prefix}avatar_url"]}

    @staticmethod
    def _strip_user_fields(item: dict[str, Any]) -> dict[str, Any]:
        for key in ("username", "display_name", "avatar_url"):
            item.pop(key, None)
        return item

    def _permission(self, db, user_id: str | None, section_id: str) -> str:
        if not user_id: return "read"
        user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if user and user["role"] in {"admin", "developer"}: return "moderate"
        if db.execute("SELECT 1 FROM forum_section_moderators WHERE section_id=? AND user_id=?", (section_id, user_id)).fetchone(): return "moderate"
        row = db.execute("SELECT permission FROM forum_permissions WHERE user_id=? AND section_id=?", (user_id, section_id)).fetchone()
        return row["permission"] if row else "write"

    def permission(self, user_id: str | None, section_id: str) -> str:
        with self.database.connect() as db: return self._permission(db, user_id, section_id)

    def list_sections(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.connect() as db:
            rows = db.execute("""SELECT s.*, COUNT(DISTINCT t.id) AS thread_count, COUNT(r.id) AS reply_count,
                COALESCE(p.permission, 'read') AS permission FROM forum_sections s
                LEFT JOIN forum_threads t ON t.section_id=s.id AND t.deleted_at IS NULL
                LEFT JOIN forum_replies r ON r.thread_id=t.id AND r.deleted_at IS NULL
                LEFT JOIN forum_permissions p ON p.section_id=s.id AND p.user_id=? GROUP BY s.id, p.permission
                ORDER BY s.sort_order, s.created_at""", (user_id,)).fetchall()
            return [{**dict(row), "moderator_count": db.execute("SELECT COUNT(*) FROM forum_section_moderators WHERE section_id=?", (row["id"],)).fetchone()[0]} for row in rows]

    def get_section(self, section_id: str) -> dict[str, Any] | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM forum_sections WHERE id=? OR slug=?", (section_id, section_id)).fetchone()
        return dict(row) if row else None

    def create_section(self, name: str, slug: str, description: str = "", sort_order: int = 0) -> dict[str, Any]:
        now, section_id = time.time(), str(uuid.uuid4())
        with self.database.connect() as db:
            db.execute("INSERT INTO forum_sections(id,name,slug,description,sort_order,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (section_id, name.strip(), slug.strip(), description.strip(), sort_order, now, now))
            row = db.execute("SELECT * FROM forum_sections WHERE id=?", (section_id,)).fetchone()
        return dict(row)

    def update_section(self, section_id: str, fields: dict[str, Any]) -> bool:
        allowed = {k: fields[k] for k in ("name", "slug", "description", "sort_order", "is_locked") if k in fields}
        if not allowed: return False
        allowed["updated_at"] = time.time()
        with self.database.connect() as db: result = db.execute(f"UPDATE forum_sections SET {','.join(f'{k}=?' for k in allowed)} WHERE id=?", (*allowed.values(), section_id))
        return result.rowcount == 1

    def delete_section(self, section_id: str) -> bool:
        with self.database.connect() as db: return db.execute("DELETE FROM forum_sections WHERE id=?", (section_id,)).rowcount == 1

    def _tag_ids(self, db, tags: list[str]) -> list[str]:
        ids = []
        for raw in tags:
            name = raw.strip().strip("#")[:32]
            if not name: continue
            slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.lower()).strip("-") or uuid.uuid4().hex[:12]
            db.execute("INSERT OR IGNORE INTO forum_tags(id,name,slug,created_at) VALUES (?,?,?,?)", (str(uuid.uuid4()), name, slug, time.time()))
            ids.append(db.execute("SELECT id FROM forum_tags WHERE name=?", (name,)).fetchone()["id"])
        return ids

    def _sync_tags(self, db, thread_id: str, tags: list[str]) -> list[str]:
        ids = self._tag_ids(db, tags); db.execute("DELETE FROM forum_thread_tags WHERE thread_id=?", (thread_id,))
        for tag_id in ids: db.execute("INSERT OR IGNORE INTO forum_thread_tags(thread_id,tag_id) VALUES (?,?)", (thread_id, tag_id))
        return [db.execute("SELECT name FROM forum_tags WHERE id=?", (tag_id,)).fetchone()[0] for tag_id in ids]

    @staticmethod
    def _poem_refs(rows: list[Any]) -> list[dict[str, Any]]:
        items = []
        for row in rows:
            item = dict(row)
            item["evaluation"] = json.loads(item.pop("evaluation_json")) if item.get("evaluation_json") else None
            items.append(item)
        return items

    def _thread_item(self, row: Any, db=None, user_id: str | None = None) -> dict[str, Any]:
        item = dict(row); item["author"] = self._author(row); self._strip_user_fields(item)
        if db is not None:
            item["tags"] = [r[0] for r in db.execute("SELECT tg.name FROM forum_tags tg JOIN forum_thread_tags tt ON tt.tag_id=tg.id WHERE tt.thread_id=? ORDER BY tg.name", (item["id"],)).fetchall()]
            item["poems"] = self._poem_refs(db.execute("SELECT p.id,p.title,p.content,p.work_type,p.form_name,p.meter_type,p.created_at,p.evaluation_json,u.id AS author_id,u.display_name AS author_display_name FROM forum_content_poems cp JOIN poems p ON p.id=cp.poem_id JOIN users u ON u.id=p.user_id WHERE cp.thread_id=? ORDER BY cp.position", (item["id"],)).fetchall())
            item["last_reply_author"] = None
            if item.get("last_reply_author_id"):
                last = db.execute("SELECT id,username,display_name,avatar_url FROM users WHERE id=?", (item["last_reply_author_id"],)).fetchone()
                if last: item["last_reply_author"] = {"id": last["id"], "username": last["username"], "display_name": last["display_name"] or last["username"], "avatar_url": last["avatar_url"]}
            item["following"] = bool(user_id and db.execute("SELECT 1 FROM forum_thread_follows WHERE user_id=? AND thread_id=?", (user_id, item["id"])).fetchone())
            for reaction in ("like", "question"):
                item[f"{reaction}_count"] = db.execute("SELECT COUNT(*) FROM forum_reactions WHERE thread_id=? AND reaction_type=?", (item["id"], reaction)).fetchone()[0]
                item[f"{'liked' if reaction == 'like' else 'questioned'}_by_me"] = bool(user_id and db.execute("SELECT 1 FROM forum_reactions WHERE thread_id=? AND user_id=? AND reaction_type=?", (item["id"], user_id, reaction)).fetchone())
        return item

    def list_threads(self, section_id: str | None, user_id: str | None, *, page: int = 1, limit: int = 20, q: str | None = None, sort: str = "latest", tag: str | None = None) -> dict[str, Any]:
        page, limit = max(page, 1), min(max(limit, 1), 100); clauses = ["t.deleted_at IS NULL"]; args: list[Any] = []
        if section_id: clauses.append("t.section_id=?"); args.append(section_id)
        if q:
            pattern = f"%{q.strip()}%"; clauses.append("(t.title LIKE ? OR t.content LIKE ? OR u.username LIKE ? OR COALESCE(u.display_name,'') LIKE ? OR EXISTS (SELECT 1 FROM forum_thread_tags st JOIN forum_tags sq ON sq.id=st.tag_id WHERE st.thread_id=t.id AND sq.name LIKE ?))"); args.extend([pattern] * 5)
        if tag: clauses.append("EXISTS (SELECT 1 FROM forum_thread_tags st JOIN forum_tags sq ON sq.id=st.tag_id WHERE st.thread_id=t.id AND sq.slug=?)"); args.append(tag)
        where = " AND ".join(clauses)
        reply_count = "(SELECT COUNT(*) FROM forum_replies rr WHERE rr.thread_id=t.id AND rr.deleted_at IS NULL)"
        order = {"hot": f"(t.view_count + {reply_count} * 4) DESC, t.updated_at DESC", "replies": f"{reply_count} DESC, t.updated_at DESC", "views": "t.view_count DESC, t.updated_at DESC"}.get(sort, "t.updated_at DESC")
        with self.database.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM forum_threads t JOIN users u ON u.id=t.author_id WHERE {where}", args).fetchone()[0]
            rows = db.execute(f"""SELECT t.*,u.username,u.display_name,u.avatar_url,(SELECT COUNT(*) FROM forum_replies r WHERE r.thread_id=t.id AND r.deleted_at IS NULL) AS reply_count_cache
                FROM forum_threads t JOIN users u ON u.id=t.author_id WHERE {where} ORDER BY t.is_pinned DESC,t.is_featured DESC,{order} LIMIT ? OFFSET ?""", (*args, limit, (page - 1) * limit)).fetchall()
            items = []
            for row in rows:
                item = self._thread_item(row, db, user_id); item["reply_count"] = row["reply_count_cache"]; items.append(item)
        return {"items": items, "page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}

    def get_thread(self, thread_id: str, *, increment_view: bool = False, user_id: str | None = None) -> dict[str, Any] | None:
        with self.database.connect() as db:
            if increment_view: db.execute("UPDATE forum_threads SET view_count=view_count+1 WHERE id=?", (thread_id,))
            row = db.execute("SELECT t.*,s.name AS section_name,s.slug AS section_slug,u.id AS author_id,u.username,u.display_name,u.avatar_url FROM forum_threads t JOIN forum_sections s ON s.id=t.section_id JOIN users u ON u.id=t.author_id WHERE t.id=? AND t.deleted_at IS NULL", (thread_id,)).fetchone()
            if not row: return None
            item = self._thread_item(row, db, user_id); item["reply_count"] = db.execute("SELECT COUNT(*) FROM forum_replies WHERE thread_id=? AND deleted_at IS NULL", (thread_id,)).fetchone()[0]; return item

    def _content_allowed(self, db, content: str) -> bool:
        return not any(word and word in content for word in (r[0] for r in db.execute("SELECT word FROM forum_sensitive_words WHERE active=1").fetchall()))

    def create_thread(self, user_id: str, section_id: str, title: str, content: str, tags: list[str] | None = None, poem_ids: list[str] | None = None) -> dict[str, Any]:
        now, thread_id = time.time(), str(uuid.uuid4()); tags = tags or self.TAG_RE.findall(f"{title}\n{content}")
        with self.database.connect() as db:
            if not self._content_allowed(db, f"{title}\n{content}"): raise ValueError("内容包含暂不可发布的敏感词")
            db.execute("INSERT INTO forum_threads(id,section_id,author_id,title,content,created_at,updated_at,last_reply_at) VALUES (?,?,?,?,?,?,?,?)", (thread_id, section_id, user_id, title.strip(), content.strip(), now, now, now)); self._sync_tags(db, thread_id, tags)
            for position, poem_id in enumerate(poem_ids or []):
                if db.execute("SELECT 1 FROM poems WHERE id=?", (poem_id,)).fetchone(): db.execute("INSERT INTO forum_content_poems(id,thread_id,poem_id,position) VALUES (?,?,?,?)", (str(uuid.uuid4()), thread_id, poem_id, position))
        return self.get_thread(thread_id, user_id=user_id)  # type: ignore[return-value]

    def update_thread(self, thread_id: str, user_id: str, fields: dict[str, Any], *, moderate: bool = False) -> bool:
        allowed_keys = ("title", "content", "is_pinned", "is_locked", "is_featured", "section_id") if moderate else ("title", "content"); allowed = {k: fields[k] for k in allowed_keys if k in fields}; tags = fields.get("tags")
        if not allowed and tags is None: return False
        allowed["updated_at"] = time.time()
        with self.database.connect() as db:
            owner = "" if moderate else " AND author_id=?"; params = (*allowed.values(), thread_id, *(() if moderate else (user_id,))); result = db.execute(f"UPDATE forum_threads SET {','.join(f'{k}=?' for k in allowed)} WHERE id=?{owner}", params)
            if result.rowcount and tags is not None: self._sync_tags(db, thread_id, tags)
        return result.rowcount == 1

    def delete_thread(self, thread_id: str, user_id: str, *, moderate: bool = False) -> bool:
        with self.database.connect() as db: result = db.execute("UPDATE forum_threads SET deleted_at=?,updated_at=? WHERE id=?" + ("" if moderate else " AND author_id=?"), (time.time(), time.time(), thread_id) if moderate else (time.time(), time.time(), thread_id, user_id))
        return result.rowcount == 1

    def _reply_item(self, row: Any, db, user_id: str | None = None) -> dict[str, Any]:
        item = dict(row); item["author"] = self._author(row); self._strip_user_fields(item)
        item["poems"] = self._poem_refs(db.execute("SELECT p.id,p.title,p.content,p.work_type,p.form_name,p.meter_type,p.created_at,p.evaluation_json,u.id AS author_id,u.display_name AS author_display_name FROM forum_content_poems cp JOIN poems p ON p.id=cp.poem_id JOIN users u ON u.id=p.user_id WHERE cp.reply_id=? ORDER BY cp.position", (item["id"],)).fetchall())
        item["child_count"] = db.execute("SELECT COUNT(*) FROM forum_replies WHERE parent_reply_id=? AND deleted_at IS NULL", (item["id"],)).fetchone()[0]
        item["parent_author"] = None
        if item.get("parent_reply_id"):
            parent = db.execute("SELECT u.id,u.username,u.display_name,u.avatar_url FROM forum_replies r JOIN users u ON u.id=r.author_id WHERE r.id=?", (item["parent_reply_id"],)).fetchone()
            if parent: item["parent_author"] = {"id": parent["id"], "username": parent["username"], "display_name": parent["display_name"] or parent["username"], "avatar_url": parent["avatar_url"]}
        for reaction in ("like", "question"):
            item[f"{reaction}_count"] = db.execute("SELECT COUNT(*) FROM forum_reactions WHERE reply_id=? AND reaction_type=?", (item["id"], reaction)).fetchone()[0]
            item[f"{'liked' if reaction == 'like' else 'questioned'}_by_me"] = bool(user_id and db.execute("SELECT 1 FROM forum_reactions WHERE reply_id=? AND user_id=? AND reaction_type=?", (item["id"], user_id, reaction)).fetchone())
        return item

    def list_replies(self, thread_id: str, *, page: int = 1, limit: int = 50, user_id: str | None = None, parent_reply_id: str | None = None) -> dict[str, Any]:
        page, limit = max(page, 1), min(max(limit, 1), 100); clause = "thread_id=? AND deleted_at IS NULL"; args: list[Any] = [thread_id]
        if parent_reply_id is not None: clause += " AND parent_reply_id=?"; args.append(parent_reply_id)
        with self.database.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM forum_replies WHERE {clause}", args).fetchone()[0]
            rows = db.execute(f"SELECT r.*,u.id AS author_id,u.username,u.display_name,u.avatar_url FROM forum_replies r JOIN users u ON u.id=r.author_id WHERE {clause} ORDER BY r.floor_no,r.created_at,r.id LIMIT ? OFFSET ?", (*args, limit, (page - 1) * limit)).fetchall()
            items = [self._reply_item(row, db, user_id) for row in rows]
        return {"items": items, "page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}

    def create_reply(self, user_id: str, thread_id: str, content: str, parent_reply_id: str | None = None, quoted_reply_id: str | None = None, poem_ids: list[str] | None = None) -> dict[str, Any] | None:
        now, reply_id = time.time(), str(uuid.uuid4())
        with self.database.connect() as db:
            thread = db.execute("SELECT is_locked FROM forum_threads WHERE id=? AND deleted_at IS NULL", (thread_id,)).fetchone()
            if not thread or thread["is_locked"] or not self._content_allowed(db, content): return None
            if parent_reply_id and not db.execute("SELECT 1 FROM forum_replies WHERE id=? AND thread_id=? AND deleted_at IS NULL", (parent_reply_id, thread_id)).fetchone(): return None
            if quoted_reply_id and not db.execute("SELECT 1 FROM forum_replies WHERE id=? AND thread_id=? AND deleted_at IS NULL", (quoted_reply_id, thread_id)).fetchone(): return None
            floor = db.execute("SELECT COALESCE(MAX(floor_no),0)+1 FROM forum_replies WHERE thread_id=?", (thread_id,)).fetchone()[0]
            db.execute("INSERT INTO forum_replies(id,thread_id,author_id,content,floor_no,parent_reply_id,quoted_reply_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (reply_id, thread_id, user_id, content.strip(), floor, parent_reply_id, quoted_reply_id, now, now)); db.execute("UPDATE forum_threads SET updated_at=?,last_reply_id=?,last_reply_at=?,last_reply_author_id=? WHERE id=?", (now, reply_id, now, user_id, thread_id))
            for position, poem_id in enumerate(poem_ids or []):
                if db.execute("SELECT 1 FROM poems WHERE id=?", (poem_id,)).fetchone(): db.execute("INSERT INTO forum_content_poems(id,reply_id,poem_id,position) VALUES (?,?,?,?)", (str(uuid.uuid4()), reply_id, poem_id, position))
        with self.database.connect() as db:
            row = db.execute("SELECT r.*,u.id AS author_id,u.username,u.display_name,u.avatar_url FROM forum_replies r JOIN users u ON u.id=r.author_id WHERE r.id=?", (reply_id,)).fetchone(); return self._reply_item(row, db, user_id)

    def update_reply(self, reply_id: str, user_id: str, content: str, *, moderate: bool = False) -> bool:
        with self.database.connect() as db: result = db.execute("UPDATE forum_replies SET content=?,updated_at=? WHERE id=? AND deleted_at IS NULL" + ("" if moderate else " AND author_id=?"), (content.strip(), time.time(), reply_id) if moderate else (content.strip(), time.time(), reply_id, user_id))
        return result.rowcount == 1

    def delete_reply(self, reply_id: str, user_id: str, *, moderate: bool = False) -> bool:
        with self.database.connect() as db: result = db.execute("UPDATE forum_replies SET deleted_at=?,updated_at=? WHERE id=?" + ("" if moderate else " AND author_id=?"), (time.time(), time.time(), reply_id) if moderate else (time.time(), time.time(), reply_id, user_id))
        return result.rowcount == 1

    def toggle_reaction(self, user_id: str, reaction_type: str, *, thread_id: str | None = None, reply_id: str | None = None) -> dict[str, Any]:
        target_clause = "thread_id=?" if thread_id else "reply_id=?"; target = thread_id or reply_id
        with self.database.connect() as db:
            existing = db.execute(f"SELECT id FROM forum_reactions WHERE user_id=? AND {target_clause} AND reaction_type=?", (user_id, target, reaction_type)).fetchone()
            if existing: db.execute("DELETE FROM forum_reactions WHERE id=?", (existing["id"],)); active = False
            else:
                other = "question" if reaction_type == "like" else "like"; db.execute(f"DELETE FROM forum_reactions WHERE user_id=? AND {target_clause} AND reaction_type=?", (user_id, target, other)); db.execute("INSERT INTO forum_reactions(id,user_id,thread_id,reply_id,reaction_type,created_at) VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), user_id, thread_id, reply_id, reaction_type, time.time())); active = True
            counts = {kind: db.execute(f"SELECT COUNT(*) FROM forum_reactions WHERE {target_clause} AND reaction_type=?", (target, kind)).fetchone()[0] for kind in ("like", "question")}
            mine = {kind: bool(db.execute(f"SELECT 1 FROM forum_reactions WHERE user_id=? AND {target_clause} AND reaction_type=?", (user_id, target, kind)).fetchone()) for kind in ("like", "question")}
            owner = db.execute("SELECT author_id FROM forum_threads WHERE id=?", (thread_id,)).fetchone() if thread_id else db.execute("SELECT author_id FROM forum_replies WHERE id=?", (reply_id,)).fetchone()
        return {"active": active, "reaction_type": reaction_type, "count": counts[reaction_type], "counts": counts, "mine": mine, "owner_id": owner["author_id"] if owner else None}

    def follow_thread(self, user_id: str, thread_id: str, following: bool) -> bool:
        with self.database.connect() as db:
            if following: db.execute("INSERT OR IGNORE INTO forum_thread_follows(user_id,thread_id,created_at) VALUES (?,?,?)", (user_id, thread_id, time.time()))
            else: db.execute("DELETE FROM forum_thread_follows WHERE user_id=? AND thread_id=?", (user_id, thread_id))
        return True

    def create_notification(self, user_id: str, notification_type: str, actor_id: str | None = None, thread_id: str | None = None, reply_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        if not user_id or user_id == actor_id: return
        with self.database.connect() as db: db.execute("INSERT INTO forum_notifications(id,user_id,actor_id,notification_type,thread_id,reply_id,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), user_id, actor_id, notification_type, thread_id, reply_id, json.dumps(payload or {}, ensure_ascii=False), time.time()))

    def list_notifications(self, user_id: str, page: int = 1, limit: int = 30) -> dict[str, Any]:
        page, limit = max(1, page), min(max(1, limit), 100)
        with self.database.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM forum_notifications WHERE user_id=?", (user_id,)).fetchone()[0]; unread = db.execute("SELECT COUNT(*) FROM forum_notifications WHERE user_id=? AND read_at IS NULL", (user_id,)).fetchone()[0]; rows = db.execute("SELECT n.*,u.username AS actor_username,u.display_name AS actor_display_name,u.avatar_url AS actor_avatar_url,r.content AS reply_content,t.content AS thread_content FROM forum_notifications n LEFT JOIN users u ON u.id=n.actor_id LEFT JOIN forum_replies r ON r.id=n.reply_id LEFT JOIN forum_threads t ON t.id=n.thread_id WHERE n.user_id=? ORDER BY n.created_at DESC LIMIT ? OFFSET ?", (user_id, limit, (page - 1) * limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json", "{}") or "{}")
            if not payload.get("content"):
                original = item.get("reply_content") or item.get("thread_content")
                if original:
                    payload["content"] = original
            item.pop("reply_content", None); item.pop("thread_content", None)
            item["payload"] = payload
            items.append(item)
        return {"items": items, "page": page, "limit": limit, "total": total, "unread": unread}

    def mark_notifications_read(self, user_id: str, notification_id: str | None = None) -> int:
        with self.database.connect() as db:
            clause = "user_id=? AND read_at IS NULL"; args: list[Any] = [user_id]
            if notification_id: clause += " AND id=?"; args.append(notification_id)
            return db.execute(f"UPDATE forum_notifications SET read_at=? WHERE {clause}", (time.time(), *args)).rowcount

    def save_draft(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        now, draft_id = time.time(), str(uuid.uuid4()); kind, thread_id = fields["kind"], fields.get("thread_id")
        with self.database.connect() as db:
            existing = db.execute("SELECT id FROM forum_drafts WHERE user_id=? AND kind=? AND thread_id IS ?", (user_id, kind, thread_id)).fetchone()
            if existing:
                draft_id = existing["id"]; db.execute("UPDATE forum_drafts SET section_id=?,title=?,content=?,tags_json=?,updated_at=? WHERE id=?", (fields.get("section_id"), fields.get("title", ""), fields.get("content", ""), json.dumps(fields.get("tags", []), ensure_ascii=False), now, draft_id))
            else: db.execute("INSERT INTO forum_drafts(id,user_id,kind,thread_id,section_id,title,content,tags_json,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (draft_id, user_id, kind, thread_id, fields.get("section_id"), fields.get("title", ""), fields.get("content", ""), json.dumps(fields.get("tags", []), ensure_ascii=False), now))
        return {"id": draft_id, **{k: fields.get(k) for k in ("kind", "thread_id", "section_id", "title", "content", "tags")}, "updated_at": now}

    def list_drafts(self, user_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self.database.connect() as db: rows = db.execute("SELECT * FROM forum_drafts WHERE user_id=?" + (" AND kind=?" if kind else "") + " ORDER BY updated_at DESC", (user_id, kind) if kind else (user_id,)).fetchall()
        return [{**dict(row), "tags": json.loads(row["tags_json"] or "[]")} for row in rows]

    def delete_draft(self, user_id: str, draft_id: str) -> bool:
        with self.database.connect() as db: return db.execute("DELETE FROM forum_drafts WHERE id=? AND user_id=?", (draft_id, user_id)).rowcount == 1

    def clear_drafts(self, user_id: str, kind: str, thread_id: str | None = None) -> int:
        with self.database.connect() as db:
            return db.execute("DELETE FROM forum_drafts WHERE user_id=? AND kind=? AND thread_id IS ?", (user_id, kind, thread_id)).rowcount

    def public_profile(self, user_id: str) -> dict[str, Any] | None:
        with self.database.connect() as db:
            user = db.execute("SELECT id,username,display_name,bio,avatar_url,created_at FROM users WHERE id=?", (user_id,)).fetchone()
            if not user: return None
            poems = self._poem_refs(db.execute("SELECT id,title,content,work_type,form_name,meter_type,evaluation_json,created_at FROM poems WHERE user_id=? AND is_public=1 ORDER BY created_at DESC", (user_id,)).fetchall())
            threads = [dict(row) for row in db.execute("SELECT id,title,created_at,updated_at,view_count FROM forum_threads WHERE author_id=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 50", (user_id,)).fetchall()]
            replies = [dict(row) for row in db.execute("SELECT r.id,r.thread_id,r.content,r.floor_no,r.created_at,t.title AS thread_title FROM forum_replies r JOIN forum_threads t ON t.id=r.thread_id WHERE r.author_id=? AND r.deleted_at IS NULL AND t.deleted_at IS NULL ORDER BY r.created_at DESC LIMIT 50", (user_id,)).fetchall()]
            followers = db.execute("SELECT COUNT(*) FROM forum_follows WHERE followed_id=?", (user_id,)).fetchone()[0]
            following = db.execute("SELECT COUNT(*) FROM forum_follows WHERE follower_id=?", (user_id,)).fetchone()[0]
        return {**dict(user), "poems": poems, "threads": threads, "replies": replies, "follower_count": followers, "following_count": following}

    def set_permission(self, user_id: str, section_id: str, permission: str) -> None:
        with self.database.connect() as db: db.execute("INSERT INTO forum_permissions(user_id,section_id,permission,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id,section_id) DO UPDATE SET permission=excluded.permission,updated_at=excluded.updated_at", (user_id, section_id, permission, time.time()))

    def list_permissions(self, section_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as db: rows = db.execute("SELECT p.*,u.username,u.display_name FROM forum_permissions p JOIN users u ON u.id=p.user_id WHERE p.section_id=? ORDER BY u.username", (section_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_moderator(self, section_id: str, user_id: str, active: bool) -> None:
        with self.database.connect() as db:
            if active: db.execute("INSERT OR IGNORE INTO forum_section_moderators(section_id,user_id,created_at) VALUES (?,?,?)", (section_id, user_id, time.time()))
            else: db.execute("DELETE FROM forum_section_moderators WHERE section_id=? AND user_id=?", (section_id, user_id))

    def list_moderators(self, section_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as db: rows = db.execute("SELECT u.id,u.username,u.display_name,u.avatar_url,m.created_at FROM forum_section_moderators m JOIN users u ON u.id=m.user_id WHERE m.section_id=? ORDER BY u.username", (section_id,)).fetchall()
        return [dict(row) for row in rows]

    def follow(self, follower_id: str, followed_id: str, following: bool) -> bool:
        with self.database.connect() as db:
            if following: db.execute("INSERT OR IGNORE INTO forum_follows(follower_id,followed_id,created_at) VALUES (?,?,?)", (follower_id, followed_id, time.time()))
            else: db.execute("DELETE FROM forum_follows WHERE follower_id=? AND followed_id=?", (follower_id, followed_id))
        return True

    def list_following(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as db: rows = db.execute("SELECT u.id,u.username,u.display_name,u.avatar_url,f.created_at FROM forum_follows f JOIN users u ON u.id=f.followed_id WHERE f.follower_id=? ORDER BY f.created_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def report(self, reporter_id: str, reason: str, thread_id: str | None = None, reply_id: str | None = None) -> dict[str, Any]:
        report_id, now = str(uuid.uuid4()), time.time()
        with self.database.connect() as db: db.execute("INSERT INTO forum_reports(id,reporter_id,thread_id,reply_id,reason,created_at) VALUES (?,?,?,?,?,?)", (report_id, reporter_id, thread_id, reply_id, reason.strip(), now)); row = db.execute("SELECT * FROM forum_reports WHERE id=?", (report_id,)).fetchone()
        return dict(row)

    def list_reports(self, status: str | None = "open") -> list[dict[str, Any]]:
        clause = "WHERE r.status=?" if status else ""; args = (status,) if status else ()
        with self.database.connect() as db: rows = db.execute(f"SELECT r.*,u.username AS reporter_username FROM forum_reports r JOIN users u ON u.id=r.reporter_id {clause} ORDER BY r.created_at DESC", args).fetchall()
        return [dict(row) for row in rows]

    def resolve_report(self, report_id: str, moderator_id: str, status: str, note: str) -> bool:
        with self.database.connect() as db:
            row = db.execute("SELECT reporter_id FROM forum_reports WHERE id=?", (report_id,)).fetchone(); result = db.execute("UPDATE forum_reports SET status=?,moderator_id=?,resolution_note=?,resolved_at=? WHERE id=?", (status, moderator_id, note.strip(), time.time(), report_id))
        if result.rowcount and row: self.create_notification(row["reporter_id"], "report_resolved", moderator_id, payload={"status": status, "note": note})
        return result.rowcount == 1
