from __future__ import annotations

import re

from fastapi import APIRouter, Header, HTTPException, Request

from .auth import current_user
from ..schemas import ForumDraftModel, ForumReactionModel, ForumReplyCreateModel, ForumReplyPatchModel, ForumReportModel, ForumThreadCreateModel, ForumThreadPatchModel

router = APIRouter(prefix="/v1/forum", tags=["forum"])

MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\u4e00-\u9fff]{2,64})")


def _user(request: Request, authorization: str | None, *, required: bool = True):
    return current_user(request, authorization, required=required)


def _section_or_404(request: Request, section_id: str):
    section = request.app.state.forum.get_section(section_id)
    if not section: raise HTTPException(status_code=404, detail="分区不存在")
    return section


def _can_write(request: Request, user: dict, section_id: str):
    section = _section_or_404(request, section_id)
    if section["is_locked"] and user.get("role") != "admin": raise HTTPException(status_code=423, detail="分区已锁定")
    if request.app.state.forum.permission(user["id"], section["id"]) not in {"write", "moderate"} and user.get("role") != "admin": raise HTTPException(status_code=403, detail="没有发帖权限")
    return section


def _notify_mentions(request: Request, content: str, actor_id: str, thread_id: str, reply_id: str | None, notified: set[str] | None = None) -> set[str]:
    recipients = notified if notified is not None else set()
    usernames = set(MENTION_RE.findall(content))
    if not usernames: return recipients
    placeholders = ",".join("?" for _ in usernames)
    with request.app.state.forum.database.connect() as db:
        rows = db.execute(f"SELECT id FROM users WHERE username COLLATE NOCASE IN ({placeholders})", tuple(usernames)).fetchall()
    for row in rows:
        if row["id"] not in recipients:
            request.app.state.forum.create_notification(row["id"], "mention", actor_id, thread_id, reply_id)
            recipients.add(row["id"])
    return recipients


@router.get("/sections")
def sections(request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization, required=False); return {"items": request.app.state.forum.list_sections(user["id"] if user else None)}


@router.get("/sections/{section_id}/threads")
def section_threads(section_id: str, request: Request, authorization: str | None = Header(default=None), page: int = 1, limit: int = 20, q: str | None = None, sort: str = "latest", tag: str | None = None):
    user = _user(request, authorization, required=False); section = _section_or_404(request, section_id)
    if request.app.state.forum.permission(user["id"] if user else None, section["id"]) == "none": raise HTTPException(status_code=403, detail="无权访问该分区")
    return request.app.state.forum.list_threads(section["id"], user["id"] if user else None, page=page, limit=limit, q=q, sort=sort, tag=tag)


@router.get("/threads")
def all_threads(request: Request, authorization: str | None = Header(default=None), page: int = 1, limit: int = 20, q: str | None = None, sort: str = "latest", tag: str | None = None):
    user = _user(request, authorization, required=False); return request.app.state.forum.list_threads(None, user["id"] if user else None, page=page, limit=limit, q=q, sort=sort, tag=tag)


@router.post("/sections/{section_id}/threads", status_code=201)
def create_thread(section_id: str, body: ForumThreadCreateModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); section = _can_write(request, user, section_id)
    try:
        thread = request.app.state.forum.create_thread(user["id"], section["id"], body.title, body.content, body.tags, body.poem_ids)
        _notify_mentions(request, body.content, user["id"], thread["id"], None)
        request.app.state.forum.clear_drafts(user["id"], "thread")
        return thread
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization, required=False); thread = request.app.state.forum.get_thread(thread_id, increment_view=True, user_id=user["id"] if user else None)
    if not thread: raise HTTPException(status_code=404, detail="主题帖不存在")
    if request.app.state.forum.permission(user["id"] if user else None, thread["section_id"]) == "none": raise HTTPException(status_code=403, detail="无权访问该主题帖")
    return thread


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: str, body: ForumThreadPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); thread = request.app.state.forum.get_thread(thread_id)
    if not thread: raise HTTPException(status_code=404, detail="主题帖不存在")
    moderate = request.app.state.forum.permission(user["id"], thread["section_id"]) == "moderate" or user.get("role") == "admin"
    if thread["author"]["id"] != user["id"] and not moderate: raise HTTPException(status_code=403, detail="只能编辑自己的主题帖")
    fields = body.model_dump(exclude_none=True)
    if fields.get("section_id") and not moderate: raise HTTPException(status_code=403, detail="只有版主可以移动主题")
    if not request.app.state.forum.update_thread(thread_id, user["id"], fields, moderate=moderate): raise HTTPException(status_code=404, detail="主题帖不存在")
    return request.app.state.forum.get_thread(thread_id, user_id=user["id"])


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); thread = request.app.state.forum.get_thread(thread_id)
    if not thread: raise HTTPException(status_code=404, detail="主题帖不存在")
    moderate = request.app.state.forum.permission(user["id"], thread["section_id"]) == "moderate" or user.get("role") == "admin"
    if not moderate and thread["author"]["id"] != user["id"]: raise HTTPException(status_code=403, detail="无权删除该主题帖")
    if not request.app.state.forum.delete_thread(thread_id, user["id"], moderate=moderate): raise HTTPException(status_code=404, detail="主题帖不存在")


@router.get("/threads/{thread_id}/replies")
def replies(thread_id: str, request: Request, authorization: str | None = Header(default=None), page: int = 1, limit: int = 50, parent_reply_id: str | None = None):
    user = _user(request, authorization, required=False); thread = request.app.state.forum.get_thread(thread_id)
    if not thread: raise HTTPException(status_code=404, detail="主题帖不存在")
    return request.app.state.forum.list_replies(thread_id, page=page, limit=limit, user_id=user["id"] if user else None, parent_reply_id=parent_reply_id)


@router.post("/threads/{thread_id}/replies", status_code=201)
def create_reply(thread_id: str, body: ForumReplyCreateModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); thread = request.app.state.forum.get_thread(thread_id)
    if not thread: raise HTTPException(status_code=404, detail="主题帖不存在")
    _can_write(request, user, thread["section_id"])
    reply = request.app.state.forum.create_reply(user["id"], thread_id, body.content, body.parent_reply_id, body.quoted_reply_id, body.poem_ids)
    if reply is None: raise HTTPException(status_code=423, detail="主题帖已锁定或内容不可发布")
    notified = set()
    owner_id = thread["author"]["id"]
    request.app.state.forum.create_notification(owner_id, "reply", user["id"], thread_id, reply["id"])
    notified.add(owner_id)
    if body.parent_reply_id:
        with request.app.state.forum.database.connect() as db: parent = db.execute("SELECT author_id FROM forum_replies WHERE id=?", (body.parent_reply_id,)).fetchone()
        if parent and parent["author_id"] not in notified:
            request.app.state.forum.create_notification(parent["author_id"], "mention", user["id"], thread_id, reply["id"])
            notified.add(parent["author_id"])
    _notify_mentions(request, body.content, user["id"], thread_id, reply["id"], notified)
    with request.app.state.forum.database.connect() as db: followers = db.execute("SELECT user_id FROM forum_thread_follows WHERE thread_id=?", (thread_id,)).fetchall()
    for follower in followers:
        if follower["user_id"] not in notified:
            request.app.state.forum.create_notification(follower["user_id"], "thread_followed", user["id"], thread_id, reply["id"])
            notified.add(follower["user_id"])
    request.app.state.forum.clear_drafts(user["id"], "reply", thread_id)
    return reply


@router.patch("/replies/{reply_id}")
def patch_reply(reply_id: str, body: ForumReplyPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization)
    with request.app.state.forum.database.connect() as db: row = db.execute("SELECT r.author_id,t.section_id FROM forum_replies r JOIN forum_threads t ON t.id=r.thread_id WHERE r.id=?", (reply_id,)).fetchone()
    if not row: raise HTTPException(status_code=404, detail="回复不存在")
    moderate = request.app.state.forum.permission(user["id"], row["section_id"]) == "moderate" or user.get("role") == "admin"
    if row["author_id"] != user["id"] and not moderate: raise HTTPException(status_code=403, detail="只能编辑自己的回复")
    if not request.app.state.forum.update_reply(reply_id, user["id"], body.content, moderate=moderate): raise HTTPException(status_code=404, detail="回复不存在")
    return {"status": "updated"}


@router.delete("/replies/{reply_id}", status_code=204)
def delete_reply(reply_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization)
    with request.app.state.forum.database.connect() as db: row = db.execute("SELECT r.author_id,t.section_id FROM forum_replies r JOIN forum_threads t ON t.id=r.thread_id WHERE r.id=?", (reply_id,)).fetchone()
    if not row: raise HTTPException(status_code=404, detail="回复不存在")
    moderate = request.app.state.forum.permission(user["id"], row["section_id"]) == "moderate" or user.get("role") == "admin"
    if not moderate and row["author_id"] != user["id"]: raise HTTPException(status_code=403, detail="无权删除该回复")
    if not request.app.state.forum.delete_reply(reply_id, user["id"], moderate=moderate): raise HTTPException(status_code=404, detail="回复不存在")


@router.post("/threads/{thread_id}/follow")
def follow_thread(thread_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); request.app.state.forum.follow_thread(user["id"], thread_id, True); return {"following": True}


@router.delete("/threads/{thread_id}/follow", status_code=204)
def unfollow_thread(thread_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); request.app.state.forum.follow_thread(user["id"], thread_id, False)


@router.post("/threads/{thread_id}/reaction")
def react_thread(thread_id: str, body: ForumReactionModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); result = request.app.state.forum.toggle_reaction(user["id"], body.reaction_type, thread_id=thread_id)
    if result["active"] and result.get("owner_id"):
        owner = request.app.state.users.get(result["owner_id"])
        if owner and owner.get("notify_on_reaction", True): request.app.state.forum.create_notification(owner["id"], f"reaction_{body.reaction_type}", user["id"], thread_id)
    result.pop("owner_id", None); return result


@router.post("/replies/{reply_id}/reaction")
def react_reply(reply_id: str, body: ForumReactionModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); result = request.app.state.forum.toggle_reaction(user["id"], body.reaction_type, reply_id=reply_id)
    if result["active"] and result.get("owner_id"):
        owner = request.app.state.users.get(result["owner_id"])
        if owner and owner.get("notify_on_reaction", True):
            with request.app.state.forum.database.connect() as db: target = db.execute("SELECT thread_id FROM forum_replies WHERE id=?", (reply_id,)).fetchone()
            request.app.state.forum.create_notification(owner["id"], f"reaction_{body.reaction_type}", user["id"], target["thread_id"] if target else None, reply_id)
    result.pop("owner_id", None); return result


@router.post("/reports", status_code=201)
def report(body: ForumReportModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization)
    if bool(body.thread_id) == bool(body.reply_id): raise HTTPException(status_code=422, detail="必须且只能举报一个主题帖或回复")
    return request.app.state.forum.report(user["id"], body.reason, body.thread_id, body.reply_id)


@router.get("/notifications")
def notifications(request: Request, authorization: str | None = Header(default=None), page: int = 1, limit: int = 30):
    user = _user(request, authorization); return request.app.state.forum.list_notifications(user["id"], page, limit)


@router.post("/notifications/read")
def notifications_read(request: Request, authorization: str | None = Header(default=None), notification_id: str | None = None):
    user = _user(request, authorization); return {"updated": request.app.state.forum.mark_notifications_read(user["id"], notification_id)}


@router.get("/drafts")
def drafts(request: Request, authorization: str | None = Header(default=None), kind: str | None = None):
    user = _user(request, authorization); return {"items": request.app.state.forum.list_drafts(user["id"], kind)}


@router.put("/drafts")
def save_draft(body: ForumDraftModel, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); return request.app.state.forum.save_draft(user["id"], body.model_dump())


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization)
    if not request.app.state.forum.delete_draft(user["id"], draft_id): raise HTTPException(status_code=404, detail="草稿不存在")


@router.post("/users/{target_id}/follow")
def follow(target_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization)
    if target_id == user["id"]: raise HTTPException(status_code=400, detail="不能关注自己")
    target = request.app.state.users.get(target_id)
    if not target: raise HTTPException(status_code=404, detail="用户不存在")
    request.app.state.forum.follow(user["id"], target_id, True); return {"following": True, "user": target}


@router.delete("/users/{target_id}/follow", status_code=204)
def unfollow(target_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); request.app.state.forum.follow(user["id"], target_id, False)


@router.get("/following")
def following(request: Request, authorization: str | None = Header(default=None)):
    user = _user(request, authorization); return {"items": request.app.state.forum.list_following(user["id"])}


@router.get("/users/search")
def search_users(request: Request, q: str = "", limit: int = 20):
    return request.app.state.users.list_users(q=q, page=1, limit=min(max(limit, 1), 50))


@router.get("/users/{user_id}")
def public_user(user_id: str, request: Request):
    user = request.app.state.forum.public_profile(user_id)
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    return user
