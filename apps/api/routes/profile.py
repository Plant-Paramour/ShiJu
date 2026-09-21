from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from .auth import current_user
from ..schemas import PoemPatchModel, CollectionCreateModel, CollectionPatchModel, CollectionItemModel

router = APIRouter(prefix="/v1/profile", tags=["profile"])


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


@router.delete("/poem-collections/{collection_id}/items/{poem_id}")
def remove_collection_item(collection_id: str, poem_id: str, request: Request, authorization: str | None = Header(default=None)):
    user = current_user(request, authorization)
    if not request.app.state.users.collection_item(collection_id, poem_id, user["id"], False): raise HTTPException(status_code=404, detail="collection or poem not found")
    return {"status": "removed"}
