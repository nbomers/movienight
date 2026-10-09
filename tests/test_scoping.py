from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Movie

from .conftest import auth, invite_guest, make_user


def _movie(client: TestClient, headers: dict[str, str], title: str) -> int:
    resp = client.post("/movies/", json={"title": title}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _next_round(client: TestClient, admin_headers: dict[str, str], round_id: int) -> int:
    client.post(f"/rounds/{round_id}/complete", headers=admin_headers)
    body = {"name": "Neu", "starts_at": datetime.now(timezone.utc).isoformat()}
    return client.post("/rounds/", json=body, headers=admin_headers).json()["id"]


def test_cannot_vote_on_movie_outside_active_round(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    movie_id = _movie(client, admin_headers, "Alt")
    _next_round(client, admin_headers, active_round)
    # Simulate a movie that stayed active but was not carried over.
    with SessionLocal() as db:
        movie = db.get(Movie, movie_id)
        movie.round_id = active_round
        db.commit()
    resp = client.post(f"/movies/{movie_id}/vote", json={"vote_type": "up"}, headers=admin_headers)
    assert resp.status_code == 404


def test_guest_cannot_read_comments_of_other_rounds(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    old_movie = _movie(client, admin_headers, "Alt")
    client.post(f"/movies/{old_movie}/comments", json={"text": "intern"}, headers=admin_headers)
    second = _next_round(client, admin_headers, active_round)
    with SessionLocal() as db:
        db.get(Movie, old_movie).round_id = active_round
        db.commit()

    guest_id = make_user("gast")
    invite_guest(guest_id, second)
    assert client.get(f"/movies/{old_movie}/comments", headers=auth("gast")).status_code == 404
    assert client.get(f"/movies/{old_movie}/comments", headers=admin_headers).status_code == 200


def test_complete_rejects_movie_from_other_round(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    resp = client.post(f"/rounds/{active_round}/complete?watched_movie_id=9999", headers=admin_headers)
    assert resp.status_code == 400
    # The round stays active after the rejected request.
    assert client.get("/rounds/active", headers=admin_headers).json()["id"] == active_round


def test_set_watched_only_once_and_only_on_completed_rounds(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    a = _movie(client, admin_headers, "A")
    b = _movie(client, admin_headers, "B")
    assert client.patch(f"/rounds/{active_round}/set-watched?watched_movie_id={a}", headers=admin_headers).status_code == 400
    client.post(f"/rounds/{active_round}/complete", headers=admin_headers)
    assert client.patch(f"/rounds/{active_round}/set-watched?watched_movie_id={a}", headers=admin_headers).status_code == 200
    assert client.patch(f"/rounds/{active_round}/set-watched?watched_movie_id={b}", headers=admin_headers).status_code == 409


def test_deadline_only_on_active_round(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    client.post(f"/rounds/{active_round}/complete", headers=admin_headers)
    resp = client.patch(f"/rounds/{active_round}/deadline", json={"vote_deadline": None}, headers=admin_headers)
    assert resp.status_code == 400


def test_regular_cannot_remove_own_movie_from_finished_round(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    make_user("alice", regular=True)
    movie_id = _movie(client, auth("alice"), "Alices Film")
    client.post(f"/rounds/{active_round}/complete", headers=admin_headers)
    assert client.delete(f"/movies/{movie_id}", headers=auth("alice")).status_code == 400
    assert client.delete(f"/movies/{movie_id}", headers=admin_headers).status_code == 204
