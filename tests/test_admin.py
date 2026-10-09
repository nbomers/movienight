from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import InviteToken, Movie

from .conftest import auth, make_user


def test_deleting_user_keeps_watched_history(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    alice = make_user("alice", regular=True)
    watched = client.post("/movies/", json={"title": "Gesehen"}, headers=auth("alice")).json()["id"]
    other = client.post("/movies/", json={"title": "Weg"}, headers=auth("alice")).json()["id"]
    client.post(f"/rounds/{active_round}/complete?watched_movie_id={watched}", headers=admin_headers)

    assert client.delete(f"/admin/users/{alice}", headers=admin_headers).status_code == 204

    history = client.get("/movies/watched", headers=admin_headers).json()
    assert [entry["movie_title"] for entry in history] == ["Gesehen"]
    with SessionLocal() as db:
        assert db.get(Movie, other) is None


def test_deleting_admin_reassigns_their_invites(client: TestClient, admin_headers: dict[str, str]) -> None:
    other_admin = make_user("boss", admin=True)
    client.post("/admin/invites", json={}, headers=auth("boss"))
    assert client.delete(f"/admin/users/{other_admin}", headers=admin_headers).status_code == 204
    with SessionLocal() as db:
        invite = db.query(InviteToken).one()
        assert invite.created_by != other_admin


def test_reactivate_and_revoke_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    user_id = make_user("alice")
    client.patch(f"/admin/users/{user_id}/deactivate", headers=admin_headers)
    resp = client.patch(f"/admin/users/{user_id}/activate", headers=admin_headers)
    assert resp.json()["is_active"] is True

    assert client.patch(f"/admin/users/{user_id}/make-admin", headers=admin_headers).json()["is_admin"] is True
    assert client.patch(f"/admin/users/{user_id}/revoke-admin", headers=admin_headers).json()["is_admin"] is False

    me = client.get("/auth/me", headers=admin_headers).json()
    assert client.patch(f"/admin/users/{me['id']}/revoke-admin", headers=admin_headers).status_code == 400
