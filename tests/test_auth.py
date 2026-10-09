from fastapi.testclient import TestClient

from app.auth import create_access_token
from app.database import SessionLocal
from app.models import User

from .conftest import auth, make_user


def test_missing_token_is_401(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_username_token_from_old_versions_is_rejected(client: TestClient) -> None:
    make_user("alice")
    legacy = create_access_token({"sub": "alice"})
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401


def test_token_does_not_carry_over_to_new_account_with_same_name(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    old_id = make_user("alice")
    old_headers = auth("alice")
    assert client.delete(f"/admin/users/{old_id}", headers=admin_headers).status_code == 204
    make_user("alice")
    assert client.get("/auth/me", headers=old_headers).status_code == 401


def test_password_reset_logs_user_out(client: TestClient, admin_headers: dict[str, str]) -> None:
    user_id = make_user("alice")
    headers = auth("alice")
    resp = client.patch(f"/admin/users/{user_id}/reset-password", json={"password": "new-password-1"}, headers=admin_headers)
    assert resp.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_change_password(client: TestClient) -> None:
    make_user("alice")
    old_headers = auth("alice")
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "another-password"},
        headers=old_headers,
    )
    assert resp.status_code == 400

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "password123", "new_password": "another-password"},
        headers=old_headers,
    )
    assert resp.status_code == 200
    new_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert client.get("/auth/me", headers=old_headers).status_code == 401
    assert client.get("/auth/me", headers=new_headers).status_code == 200
    login = client.post("/auth/login", json={"username": "alice", "password": "another-password"})
    assert login.status_code == 200


def test_deactivated_user_is_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    user_id = make_user("alice")
    headers = auth("alice")
    client.patch(f"/admin/users/{user_id}/deactivate", headers=admin_headers)
    assert client.get("/auth/me", headers=headers).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, user_id).is_active is False


def _invite(client: TestClient, admin_headers: dict[str, str], **body) -> str:
    resp = client.post("/admin/invites", json=body, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def test_username_is_unique_ignoring_case(client: TestClient, admin_headers: dict[str, str]) -> None:
    make_user("alice")
    token = _invite(client, admin_headers)
    resp = client.post("/auth/register", json={"invite_token": token, "username": "Alice", "password": "password123"})
    assert resp.status_code == 409


def test_single_use_invite_works_once(client: TestClient, admin_headers: dict[str, str]) -> None:
    token = _invite(client, admin_headers, max_uses=1)
    first = client.post("/auth/register", json={"invite_token": token, "username": "bob", "password": "password123"})
    assert first.status_code == 201
    second = client.post("/auth/register", json={"invite_token": token, "username": "carl", "password": "password123"})
    assert second.status_code == 400


def test_guest_invite_joins_active_round(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    token = _invite(client, admin_headers, invite_type="guest")
    resp = client.post("/auth/register", json={"invite_token": token, "username": "gast", "password": "password123"})
    assert resp.status_code == 201
    assert resp.json()["is_regular"] is False
    assert client.get("/movies/", headers=auth("gast")).status_code == 200
