from pathlib import Path
import json
import time
import uuid

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import ApiSettings


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(ApiSettings(database_path=tmp_path / "forum.db", agent_token="a", worker_token="w")))


def _login(client: TestClient, username: str, password: str):
    response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_user_can_create_thread_reply_and_update_profile(tmp_path):
    client = _client(tmp_path)
    headers = _login(client, "Test1", "Test1")
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]

    created = client.post(
        f"/v1/forum/sections/{section_id}/threads",
        headers=headers,
        json={"title": "春日", "content": "山花如笑。"},
    )
    assert created.status_code == 201
    thread_id = created.json()["id"]
    assert client.post(
        f"/v1/forum/threads/{thread_id}/replies",
        headers=headers,
        json={"content": "好诗。"},
    ).status_code == 201
    assert client.patch("/v1/profile/me", headers=headers, json={"bio": "诗友"}).json()["bio"] == "诗友"


def test_admin_can_manage_users_and_section_permissions(tmp_path):
    client = _client(tmp_path)
    headers = _login(client, "admin", "admin123")
    created = client.post(
        "/v1/admin/users",
        headers=headers,
        json={"username": "moderator", "password": "moderator123", "role": "user"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]
    result = client.put(
        f"/v1/admin/sections/{section_id}/permissions/{user_id}",
        headers=headers,
        json={"permission": "moderate"},
    )
    assert result.status_code == 200
    assert result.json()["permission"] == "moderate"


def test_forum_reactions_notifications_drafts_and_registration(tmp_path):
    client = _client(tmp_path)
    registered = client.post("/v1/auth/register", json={"username": "new_member", "password": "password123"})
    assert registered.status_code == 201
    headers = {"Authorization": f"Bearer {registered.json()['token']}"}
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]
    thread = client.post(f"/v1/forum/sections/{section_id}/threads", headers=headers, json={"title": "带话题 #春日#", "content": "正文"}).json()
    reaction = client.post(f"/v1/forum/threads/{thread['id']}/reaction", headers=headers, json={"reaction_type": "like"})
    assert reaction.status_code == 200 and reaction.json()["active"] is True
    draft = client.put("/v1/forum/drafts", headers=headers, json={"kind": "thread", "section_id": section_id, "title": "草稿", "content": "未完成"})
    assert draft.status_code == 200
    assert client.get("/v1/forum/notifications", headers=headers).json()["unread"] == 0
    token = client.post("/v1/auth/password-reset/request", json={"username": "new_member"}).json()["reset_token"]
    assert client.post("/v1/auth/password-reset/confirm", json={"token": token, "new_password": "password456"}).status_code == 200


def test_profile_avatar_upload_is_controlled_and_served(tmp_path):
    client = _client(tmp_path)
    headers = _login(client, "Test1", "Test1")

    invalid = client.post("/v1/profile/me/avatar", headers={**headers, "Content-Type": "image/webp"}, content=b"RIFF-not-an-image")
    assert invalid.status_code == 422

    uploaded = client.post(
        "/v1/profile/me/avatar",
        headers={**headers, "Content-Type": "image/png"},
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01avatar",
    )
    assert uploaded.status_code == 200
    avatar_url = uploaded.json()["avatar_url"]
    assert avatar_url.startswith("/media/avatars/")
    assert client.get(avatar_url).status_code == 200
    assert client.patch("/v1/profile/me", headers=headers, json={"avatar_url": "https://example.com/x.png"}).status_code == 422


def test_conversation_delete_only_archives_and_can_restore(tmp_path):
    client = _client(tmp_path)
    headers = _login(client, "Test1", "Test1")
    conversation = client.post("/v1/conversations", headers=headers, json={"title": "待归档"}).json()

    assert client.delete(f"/v1/conversations/{conversation['id']}", headers=headers).status_code == 200
    assert not any(item["id"] == conversation["id"] for item in client.get("/v1/conversations", headers=headers).json()["items"])
    archived = client.get("/v1/conversations?include_deleted=true", headers=headers).json()["items"]
    assert next(item for item in archived if item["id"] == conversation["id"])["deleted_at"] is not None
    assert client.delete(f"/v1/conversations/{conversation['id']}/permanent", headers=headers).status_code in {404, 405}
    assert client.post(f"/v1/conversations/{conversation['id']}/restore", headers=headers).status_code == 200
    assert any(item["id"] == conversation["id"] for item in client.get("/v1/conversations", headers=headers).json()["items"])


def test_reply_tree_draft_cleanup_and_notification_recipients(tmp_path):
    client = _client(tmp_path)
    owner = _login(client, "Test1", "Test1")
    commenter = _login(client, "Test2", "Test2")
    other = _login(client, "Test3", "Test3")
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]

    client.put("/v1/forum/drafts", headers=owner, json={"kind": "thread", "section_id": section_id, "title": "草稿", "content": "待发布"})
    thread = client.post(f"/v1/forum/sections/{section_id}/threads", headers=owner, json={"title": "通知边界", "content": "正文"}).json()
    assert client.get("/v1/forum/drafts?kind=thread", headers=owner).json()["items"] == []

    first = client.post(f"/v1/forum/threads/{thread['id']}/replies", headers=commenter, json={"content": "@Test1 第一条评论"}).json()
    client.post(f"/v1/forum/threads/{thread['id']}/replies", headers=other, json={"content": "互不相关的评论"})
    nested = client.post(f"/v1/forum/threads/{thread['id']}/replies", headers=other, json={"content": "回复第二位诗友", "parent_reply_id": first["id"]})
    assert nested.status_code == 201
    assert nested.json()["parent_reply_id"] == first["id"]
    replies = client.get(f"/v1/forum/threads/{thread['id']}/replies", headers=owner).json()["items"]
    assert [item["floor_no"] for item in replies] == [1, 2, 3]
    assert next(item for item in replies if item["id"] == nested.json()["id"])["parent_author"]["username"] == "Test2"

    owner_notices = client.get("/v1/forum/notifications", headers=owner).json()["items"]
    assert sum(item["notification_type"] == "reply" for item in owner_notices) == 3
    commenter_notices = client.get("/v1/forum/notifications", headers=commenter).json()["items"]
    assert [item["notification_type"] for item in commenter_notices] == ["reply"]
    assert commenter_notices[0]["payload"]["content"] == "回复第二位诗友"
    assert not any(item["notification_type"] == "mention" for item in owner_notices + commenter_notices)

    client.put("/v1/forum/drafts", headers=other, json={"kind": "reply", "thread_id": thread["id"], "content": "回复草稿"})
    client.post(f"/v1/forum/threads/{thread['id']}/replies", headers=other, json={"content": "发布后清理"})
    assert client.get("/v1/forum/drafts?kind=reply", headers=other).json()["items"] == []


def test_reaction_preference_unique_nickname_and_author_deletion(tmp_path):
    client = _client(tmp_path)
    owner = _login(client, "Test1", "Test1")
    actor = _login(client, "Test2", "Test2")
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]
    thread = client.post(f"/v1/forum/sections/{section_id}/threads", headers=owner, json={"title": "可删除", "content": "正文"}).json()
    reply = client.post(f"/v1/forum/threads/{thread['id']}/replies", headers=actor, json={"content": "我的回复"}).json()

    assert client.patch("/v1/profile/me", headers=actor, json={"display_name": "Test1"}).status_code == 409
    client.patch("/v1/profile/me", headers=owner, json={"notify_on_reaction": False})
    client.post(f"/v1/forum/threads/{thread['id']}/reaction", headers=actor, json={"reaction_type": "like"})
    assert not any(item["notification_type"] == "reaction_like" for item in client.get("/v1/forum/notifications", headers=owner).json()["items"])
    client.patch("/v1/profile/me", headers=owner, json={"notify_on_reaction": True})
    client.post(f"/v1/forum/threads/{thread['id']}/reaction", headers=actor, json={"reaction_type": "question"})
    assert any(item["notification_type"] == "reaction_question" for item in client.get("/v1/forum/notifications", headers=owner).json()["items"])

    assert client.delete(f"/v1/forum/replies/{reply['id']}", headers=actor).status_code == 204
    assert client.delete(f"/v1/forum/threads/{thread['id']}", headers=owner).status_code == 204
    assert client.get(f"/v1/forum/threads/{thread['id']}").status_code == 404


def test_shared_poem_keeps_evaluation_and_public_profile_visibility(tmp_path):
    client = _client(tmp_path)
    headers = _login(client, "Test1", "Test1")
    user = client.get("/v1/profile/me", headers=headers).json()
    poem_id = str(uuid.uuid4())
    evaluation = {"rhyme_book_name": "平水韵", "structure_score": 96, "tonal_score": 91, "rhyme_score": 88, "result": {}}
    with client.app.state.forum.database.connect() as db:
        db.execute(
            "INSERT INTO poems(id,user_id,title,content,work_type,form_name,created_at,evaluation_json,is_public) VALUES (?,?,?,?,?,?,?,?,1)",
            (poem_id, user["id"], "长歌", "山花春雨\n" * 10, "诗", "五言排律", time.time(), json.dumps(evaluation, ensure_ascii=False)),
        )
    section_id = client.get("/v1/forum/sections").json()["items"][0]["id"]
    thread = client.post(f"/v1/forum/sections/{section_id}/threads", headers=headers, json={"title": "分享诗作", "content": "卷轴下方的文案", "poem_ids": [poem_id]}).json()
    detail = client.get(f"/v1/forum/threads/{thread['id']}").json()
    assert detail["poems"][0]["evaluation"]["rhyme_book_name"] == "平水韵"
    public = client.get(f"/v1/forum/users/{user['id']}").json()
    assert [poem["id"] for poem in public["poems"]] == [poem_id]

    client.patch(f"/v1/profile/poems/{poem_id}", headers=headers, json={"is_public": False})
    assert client.get(f"/v1/forum/users/{user['id']}").json()["poems"] == []
