from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from .auth import current_user
from ..schemas import AdminUserCreateModel, AdminUserPatchModel, ForumSectionModel, ForumSectionPatchModel, PermissionModel, ReportResolutionModel

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def admin_user(request: Request, authorization: str | None):
    user = current_user(request, authorization)
    if user.get("role") != "admin": raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.get("/stats")
def stats(request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization)
    with request.app.state.forum.database.connect() as db:
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("users", "forum_sections", "forum_threads", "forum_replies", "forum_reports")}
    return counts


@router.get("/users")
def users(request: Request, authorization: str | None = Header(default=None), q: str | None = None, page: int = 1, limit: int = 50):
    admin_user(request, authorization); return request.app.state.users.list_users(q=q, page=page, limit=limit)


@router.post("/users", status_code=201)
def create_user(body: AdminUserCreateModel, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization)
    try: return request.app.state.users.create_user(body.username, body.password, body.display_name, body.role)
    except Exception as exc: raise HTTPException(status_code=409, detail="用户名已存在") from exc


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: AdminUserPatchModel, request: Request, authorization: str | None = Header(default=None)):
    actor = admin_user(request, authorization)
    if user_id == actor["id"] and body.role == "user": raise HTTPException(status_code=400, detail="不能移除自己的管理员权限")
    data = body.model_dump(exclude_none=True); role = data.pop("role", None)
    if data: request.app.state.users.update_profile(user_id, data)
    if role: request.app.state.users.set_role(user_id, role)
    user = request.app.state.users.get(user_id)
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request, authorization: str | None = Header(default=None)):
    actor = admin_user(request, authorization)
    if user_id == actor["id"]: raise HTTPException(status_code=400, detail="不能删除当前管理员")
    if not request.app.state.users.delete_user(user_id): raise HTTPException(status_code=404, detail="用户不存在或不可删除")


@router.post("/sections", status_code=201)
def create_section(body: ForumSectionModel, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization)
    try: return request.app.state.forum.create_section(**body.model_dump())
    except Exception as exc: raise HTTPException(status_code=409, detail="分区名称或 slug 已存在") from exc


@router.patch("/sections/{section_id}")
def patch_section(section_id: str, body: ForumSectionPatchModel, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization)
    if not request.app.state.forum.update_section(section_id, body.model_dump(exclude_none=True)): raise HTTPException(status_code=404, detail="分区不存在")
    return request.app.state.forum.get_section(section_id)


@router.delete("/sections/{section_id}", status_code=204)
def delete_section(section_id: str, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization)
    if not request.app.state.forum.delete_section(section_id): raise HTTPException(status_code=404, detail="分区不存在")


@router.get("/sections/{section_id}/permissions")
def permissions(section_id: str, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization); return {"items": request.app.state.forum.list_permissions(section_id)}


@router.get("/sections/{section_id}/moderators")
def moderators(section_id: str, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization); return {"items": request.app.state.forum.list_moderators(section_id)}


@router.put("/sections/{section_id}/moderators/{user_id}")
def add_moderator(section_id: str, user_id: str, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization); request.app.state.forum.set_moderator(section_id, user_id, True); return {"section_id": section_id, "user_id": user_id, "role": "moderator"}


@router.delete("/sections/{section_id}/moderators/{user_id}", status_code=204)
def remove_moderator(section_id: str, user_id: str, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization); request.app.state.forum.set_moderator(section_id, user_id, False)


@router.put("/sections/{section_id}/permissions/{user_id}")
def set_permission(section_id: str, user_id: str, body: PermissionModel, request: Request, authorization: str | None = Header(default=None)):
    admin_user(request, authorization); request.app.state.forum.set_permission(user_id, section_id, body.permission); return {"user_id": user_id, "section_id": section_id, "permission": body.permission}


@router.get("/reports")
def reports(request: Request, authorization: str | None = Header(default=None), report_status: str | None = "open"):
    admin_user(request, authorization); return {"items": request.app.state.forum.list_reports(report_status)}


@router.patch("/reports/{report_id}")
def resolve_report(report_id: str, body: ReportResolutionModel, request: Request, authorization: str | None = Header(default=None)):
    user = admin_user(request, authorization)
    if not request.app.state.forum.resolve_report(report_id, user["id"], body.status, body.note): raise HTTPException(status_code=404, detail="举报不存在")
    return {"status": body.status}
