from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import ApiSettings


class EchoAgent:
    def respond_stream(self, message, session_id=None, **kwargs):
        reply = f"答：{message}"
        yield {"event_type": "assistant.delta", "payload": {"text": reply}}
        yield {"event_type": "turn.completed", "payload": {"reply": reply, "jobs": [], "session_id": session_id}}


def _client(tmp_path: Path):
    settings = ApiSettings(database_path=tmp_path / "tree.db", agent_token="a", worker_token="w")
    client = TestClient(create_app(settings, agent_service=EchoAgent()))
    login = client.post("/v1/auth/login", json={"username": "Test1", "password": "Test1"}).json()
    return client, {"Authorization": f"Bearer {login['token']}"}


def _send(client, headers, conversation_id, message, parent_message_id=None):
    with client.stream(
        "POST",
        "/v1/agent/chat/stream",
        headers=headers,
        json={"conversation_id": conversation_id, "message": message, "parent_message_id": parent_message_id},
    ) as response:
        assert response.status_code == 200
        list(response.iter_lines())


def test_edit_preserves_old_path_and_creates_branch(tmp_path):
    client, headers = _client(tmp_path)
    conversation = client.post("/v1/conversations", headers=headers, json={"title": "树"}).json()
    _send(client, headers, conversation["id"], "原始")
    first = client.get(f"/v1/conversations/{conversation['id']}", headers=headers).json()
    original_user_id = first["messages"][0]["id"]

    _send(client, headers, conversation["id"], "编辑后", original_user_id)
    active = client.get(f"/v1/conversations/{conversation['id']}", headers=headers).json()
    tree = client.get(f"/v1/conversations/{conversation['id']}/tree", headers=headers).json()

    assert [item["content"] for item in active["messages"] if item["role"] == "user"] == ["编辑后"]
    assert {item["content"] for item in tree["messages"] if item["role"] == "user"} == {"原始", "编辑后"}
    assert len(tree["branches"]) == 2

    old_branch = next(item for item in tree["branches"] if not item["is_active"])
    switched = client.post(f"/v1/conversations/{conversation['id']}/branches/{old_branch['id']}/activate", headers=headers)
    assert switched.status_code == 200
    restored = client.get(f"/v1/conversations/{conversation['id']}", headers=headers).json()
    assert restored["messages"][0]["content"] == "原始"


def test_old_branch_keeps_all_descendants_after_edit(tmp_path):
    client, headers = _client(tmp_path)
    conversation = client.post("/v1/conversations", headers=headers, json={"title": "完整树"}).json()
    conversation_id = conversation["id"]
    _send(client, headers, conversation_id, "A")
    first = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()
    first_user_id = first["messages"][0]["id"]
    _send(client, headers, conversation_id, "B")
    _send(client, headers, conversation_id, "C")
    original = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()

    _send(client, headers, conversation_id, "A2", first_user_id)
    _send(client, headers, conversation_id, "B2")
    _send(client, headers, conversation_id, "C2")
    tree = client.get(f"/v1/conversations/{conversation_id}/tree", headers=headers).json()
    old_branch = next(item for item in tree["branches"] if not item["is_active"])
    assert client.post(f"/v1/conversations/{conversation_id}/branches/{old_branch['id']}/activate", headers=headers).status_code == 200
    restored = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()

    assert [item["content"] for item in restored["messages"]] == [item["content"] for item in original["messages"]]


def test_tree_roots_are_not_relinked_on_app_restart(tmp_path):
    client, headers = _client(tmp_path)
    conversation = client.post("/v1/conversations", headers=headers, json={"title": "重启"}).json()
    conversation_id = conversation["id"]
    _send(client, headers, conversation_id, "原始")
    first = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()
    _send(client, headers, conversation_id, "编辑", first["messages"][0]["id"])
    before = client.get(f"/v1/conversations/{conversation_id}/tree", headers=headers).json()
    client.close()

    settings = ApiSettings(database_path=tmp_path / "tree.db", agent_token="a", worker_token="w")
    with TestClient(create_app(settings, agent_service=EchoAgent())) as restarted:
        login = restarted.post("/v1/auth/login", json={"username": "Test1", "password": "Test1"}).json()
        auth = {"Authorization": f"Bearer {login['token']}"}
        after = restarted.get(f"/v1/conversations/{conversation_id}/tree", headers=auth).json()
    assert sorted(item["content"] for item in after["messages"] if item["role"] == "user") == sorted(item["content"] for item in before["messages"] if item["role"] == "user")
    assert len(after["branches"]) == len(before["branches"])


def test_sibling_messages_point_to_their_own_branches(tmp_path):
    client, headers = _client(tmp_path)
    conversation_id = client.post("/v1/conversations", headers=headers, json={"title": "多版本"}).json()["id"]
    _send(client, headers, conversation_id, "原始")
    original_id = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()["messages"][0]["id"]
    _send(client, headers, conversation_id, "第二版", original_id)
    _send(client, headers, conversation_id, "第三版", original_id)

    tree = client.get(f"/v1/conversations/{conversation_id}/tree", headers=headers).json()
    branch_ids = {branch["id"] for branch in tree["branches"]}
    users = [message for message in tree["messages"] if message["role"] == "user"]
    assert len(users) == 3
    assert {message["branch_id"] for message in users} == branch_ids
    for message in users:
        assert {sibling["branch_id"] for sibling in message["siblings"]} == branch_ids


def test_empty_conversation_has_empty_active_path(tmp_path):
    client, headers = _client(tmp_path)
    conversation_id = client.post("/v1/conversations", headers=headers, json={"title": "空对话"}).json()["id"]
    response = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()
    assert response["messages"] == []


def test_normal_turns_do_not_share_edit_version_group(tmp_path):
    client, headers = _client(tmp_path)
    conversation_id = client.post("/v1/conversations", headers=headers, json={"title": "版本组"}).json()["id"]
    _send(client, headers, conversation_id, "第一条")
    _send(client, headers, conversation_id, "第二条")

    messages = client.get(f"/v1/conversations/{conversation_id}", headers=headers).json()["messages"]
    users = [message for message in messages if message["role"] == "user"]
    assert [len(message["versions"]) for message in users] == [1, 1]
