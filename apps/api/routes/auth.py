from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from ..auth import auth_secret, bearer_token, decode_token, issue_token
from ..schemas import LoginModel, ChangePasswordModel

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def current_user(request: Request, authorization: str | None = None, *, required: bool = True):
    token = bearer_token(authorization) or request.cookies.get("shiju_token")
    payload = decode_token(token, request.app.state.settings.auth_secret or auth_secret())
    user = request.app.state.users.get(str(payload["sub"])) if payload else None
    if user is None and required:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


@router.post("/login")
def login(body: LoginModel, request: Request, response: Response):
    user = request.app.state.users.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = issue_token(user["id"], user["username"], request.app.state.settings.auth_secret)
    response.set_cookie("shiju_token", token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"token": token, "user": user}


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("shiju_token")


@router.get("/me")
def me(request: Request, authorization: str | None = Header(default=None)):
    return current_user(request, authorization)


@router.post("/change-password")
def change_password(body: ChangePasswordModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.change_password(user["id"], body.old_password, body.new_password):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    return {"status": "updated"}
