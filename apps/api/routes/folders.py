from fastapi import APIRouter, Header, HTTPException, Request

from ..schemas import FolderCreateModel, FolderPatchModel
from .auth import current_user

router = APIRouter(prefix="/v1/conversation-folders", tags=["conversation-folders"])


@router.get("")
def list_folders(request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    return {"items": request.app.state.users.list_folders(user["id"])}


@router.post("", status_code=201)
def create_folder(body: FolderCreateModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    return request.app.state.users.create_folder(user["id"], body.name)


@router.patch("/{folder_id}")
def update_folder(folder_id: str, body: FolderPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.update_folder(folder_id, user["id"], body.name):
        raise HTTPException(status_code=404, detail="folder not found")
    return {"id": folder_id, "name": body.name}
