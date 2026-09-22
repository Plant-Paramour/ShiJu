from __future__ import annotations

from pathlib import Path
import uuid
import sqlite3

from fastapi import APIRouter, Header, HTTPException, Request

from .auth import current_user
from ..schemas import PoemPatchModel, CollectionCreateModel, CollectionPatchModel, CollectionItemModel, ProfilePatchModel

router = APIRouter(prefix="/v1/profile", tags=["profile"])


def _valid_image_bytes(content_type: str, content: bytes) -> bool:
    if content_type == "image/png":
        return (
            len(content) >= 24
            and content.startswith(b"\x89PNG\r\n\x1a\n")
            and content[12:16] == b"IHDR"
            and int.from_bytes(content[16:20], "big") > 0
            and int.from_bytes(content[20:24], "big") > 0
        )
    if content_type == "image/webp":
        return len(content) >= 20 and content[:4] == b"RIFF" and content[8:12] == b"WEBP" and content[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
    return len(content) >= 16 and content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")


@router.get("/me")
def profile_me(request: Request, authorization: str | None = Header(default=None)):
    return current_user(request, authorization)


@router.patch("/me")
def patch_profile(body: ProfilePatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    try:
        return request.app.state.users.update_profile(user["id"], body.model_dump(exclude_none=True))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="这个昵称已被使用") from exc


@router.post("/me/avatar")
async def upload_avatar(request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(status_code=415, detail="头像仅支持 JPG、PNG 或 WebP")
    content = await request.body()
    if not content or len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="头像大小必须在 2MB 以内")
    if not _valid_image_bytes(content_type, content):
        raise HTTPException(status_code=422, detail="头像文件内容无效")
    directory = request.app.state.settings.database_path.parent / "avatars"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{user['id']}-{uuid.uuid4().hex[:12]}{extensions[content_type]}"
    Path(directory, filename).write_bytes(content)
    return request.app.state.users.update_profile(user["id"], {"avatar_url": f"/media/avatars/{filename}"})


@router.get("/poems")
def poems(request: Request, authorization: str | None = Header(default=None), work_type: str | None = None, favorite: bool = False):
    user = current_user(request, authorization)
    items = request.app.state.users.list_favorite_poems(user["id"]) if favorite else request.app.state.users.list_poems(user["id"])
    if work_type: items = [item for item in items if item.get("work_type") == work_type]
    return {"items": items}


@router.patch("/poems/{poem_id}")
def patch_poem(poem_id: str, body: PoemPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.update_poem(poem_id, user["id"], body.model_dump(exclude_none=True)): raise HTTPException(status_code=404, detail="poem not found")
    return {"status": "updated"}


@router.delete("/poems/{poem_id}")
def delete_poem(poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.delete_poem(poem_id, user["id"]): raise HTTPException(status_code=404, detail="poem not found")
    return {"status": "deleted"}


@router.post("/poems/{poem_id}/favorite")
def favorite_poem(poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.set_favorite(user["id"], poem_id, True): raise HTTPException(status_code=404, detail="poem not found")
    return {"favorite": True}


@router.delete("/poems/{poem_id}/favorite")
def unfavorite_poem(poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.set_favorite(user["id"], poem_id, False): raise HTTPException(status_code=404, detail="poem not found")
    return {"favorite": False}


@router.get("/poem-collections")
def collections(request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization); return {"items": request.app.state.users.list_poem_collections(user["id"])}


@router.post("/poem-collections", status_code=201)
def create_collection(body: CollectionCreateModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization); return request.app.state.users.create_poem_collection(user["id"], body.name)


@router.patch("/poem-collections/{collection_id}")
def patch_collection(collection_id: str, body: CollectionPatchModel, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.update_poem_collection(collection_id, user["id"], body.name): raise HTTPException(status_code=404, detail="collection not found")
    return {"id": collection_id, "name": body.name}


@router.delete("/poem-collections/{collection_id}")
def delete_collection(collection_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.delete_poem_collection(collection_id, user["id"]): raise HTTPException(status_code=404, detail="collection not found")
    return {"status": "deleted"}


@router.post("/poem-collections/{collection_id}/items")
def add_collection_item(collection_id: str, request: Request, body: CollectionItemModel | None = None, poem_id: str | None = None, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    selected_poem_id = body.poem_id if body is not None else poem_id
    if not selected_poem_id or not request.app.state.users.collection_item(collection_id, selected_poem_id, user["id"], True): raise HTTPException(status_code=404, detail="collection or poem not found")
    return {"status": "added"}


@router.get("/poem-collections/{collection_id}/items")
def collection_items(collection_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    return {"items": request.app.state.users.list_collection_items(collection_id, user["id"])}


@router.get("/poems/{poem_id}")
def poem_detail(poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    with request.app.state.users.database.connect() as db:
        row = db.execute("SELECT p.*,u.username AS author_username,u.display_name AS author_display_name FROM poems p JOIN users u ON u.id=p.user_id WHERE p.id=?", (poem_id,)).fetchone()
        favorite = db.execute("SELECT 1 FROM poem_favorites WHERE poem_id=? AND user_id=?", (poem_id, user["id"])).fetchone() is not None
    if not row: raise HTTPException(status_code=404, detail="poem not found")
    value = request.app.state.users._poem_row(row)
    value["favorite"] = favorite
    return value


@router.delete("/poem-collections/{collection_id}/items/{poem_id}")
def remove_collection_item(collection_id: str, poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.collection_item(collection_id, poem_id, user["id"], False): raise HTTPException(status_code=404, detail="collection or poem not found")
    return {"status": "removed"}
