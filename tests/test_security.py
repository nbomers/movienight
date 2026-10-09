import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import hash_password, verify_password
from app.config import settings
from app.database import SessionLocal
from app.models import User

from .conftest import auth, make_user

VALID_MOVIE = {
    "title": "Inception",
    "tmdb_id": 27205,
    "poster_path": "/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    "trailer_url": "https://www.youtube.com/watch?v=YoHD9XEInc0",
    "genres": "Action, Science Fiction",
}


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("poster_path", '/x.jpg" onerror="alert(1)'),
        ("poster_path", "https://evil.example/x.jpg"),
        ("trailer_url", "javascript:alert(document.cookie)"),
        ("trailer_url", "https://www.youtube.com.evil.example/watch?v=abc"),
        ("trailer_url", 'https://www.youtube.com/watch?v=abc" onmouseover="alert(1)'),
        ("genres", "x" * 256),
    ],
)
def test_movie_rejects_malicious_fields(
    client: TestClient, admin_headers: dict[str, str], active_round: int, field: str, payload: str
) -> None:
    resp = client.post("/movies/", json={**VALID_MOVIE, field: payload}, headers=admin_headers)
    assert resp.status_code == 422


def test_movie_accepts_tmdb_shaped_fields(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    resp = client.post("/movies/", json=VALID_MOVIE, headers=admin_headers)
    assert resp.status_code == 201, resp.text


def test_startup_refuses_missing_admin_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FIRST_ADMIN_PASSWORD", "")
    with pytest.raises(RuntimeError, match="FIRST_ADMIN_PASSWORD"):
        main._ensure_admin_exists()
    with SessionLocal() as db:
        assert db.query(User).count() == 0


def test_existing_admin_needs_no_bootstrap_password(monkeypatch: pytest.MonkeyPatch) -> None:
    make_user("boss", admin=True)
    monkeypatch.setattr(settings, "FIRST_ADMIN_PASSWORD", "")
    main._ensure_admin_exists()


def test_login_is_rate_limited_after_failures(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 3)
    make_user("alice")
    for _ in range(3):
        resp = client.post("/auth/login", json={"username": "alice", "password": "wrong-password"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", json={"username": "alice", "password": "password123"})
    assert resp.status_code == 429


def test_successful_logins_do_not_count(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)
    make_user("alice")
    for _ in range(5):
        resp = client.post("/auth/login", json={"username": "alice", "password": "password123"})
        assert resp.status_code == 200


def test_register_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)
    body = {"invite_token": "guessed", "username": "mallory", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 400
    assert client.post("/auth/register", json=body).status_code == 400
    assert client.post("/auth/register", json=body).status_code == 429


def test_legacy_passlib_hash_still_verifies() -> None:
    # Produced by passlib's bcrypt handler for "password123" before the switch.
    legacy = "$2b$12$41J.CqwNOUiiZr9LpGlFBOEw/nN6nzU.JHFBRZB6mEk0NIxusm1ua"
    assert verify_password("password123", legacy)
    assert not verify_password("password124", legacy)
    assert verify_password("password123", hash_password("password123"))


def test_admin_payload_type_errors_are_422(client: TestClient, admin_headers: dict[str, str]) -> None:
    user_id = make_user("bob")
    resp = client.patch(f"/admin/users/{user_id}/reset-password", json={"password": 12345678}, headers=admin_headers)
    assert resp.status_code == 422


def test_non_admin_cannot_use_admin_endpoints(client: TestClient) -> None:
    make_user("carol", regular=True)
    assert client.get("/admin/users", headers=auth("carol")).status_code == 403
    assert client.post("/admin/invites", json={}, headers=auth("carol")).status_code == 403


def test_stale_admin_copy_is_not_served(client: TestClient) -> None:
    assert client.get("/frontend/admin.htmlv").status_code == 404


def test_no_cors_by_default(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
