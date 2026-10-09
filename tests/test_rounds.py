from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Movie, Round

from .conftest import auth, invite_guest, make_user


def add_movie(client: TestClient, headers: dict[str, str], title: str, tmdb_id: int | None = None):
    return client.post("/movies/", json={"title": title, "tmdb_id": tmdb_id}, headers=headers)


def new_round(client: TestClient, headers: dict[str, str], **extra) -> int:
    body = {"name": "Runde", "starts_at": datetime.now(timezone.utc).isoformat(), **extra}
    resp = client.post("/rounds/", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_quota_three_movies_per_round(client: TestClient, active_round: int) -> None:
    make_user("alice", regular=True)
    h = auth("alice")
    for i in range(3):
        assert add_movie(client, h, f"Film {i}").status_code == 201
    resp = add_movie(client, h, "Film 4")
    assert resp.status_code == 400


def test_quota_resets_with_new_round(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    make_user("alice", regular=True)
    h = auth("alice")
    for i in range(3):
        add_movie(client, h, f"Film {i}")
    client.post(f"/rounds/{active_round}/complete", headers=admin_headers)
    # Carried-over movies keep their submitter, so alice is still at her limit.
    new_round(client, admin_headers)
    assert add_movie(client, h, "Film 4").status_code == 400


def test_duplicate_check_by_tmdb_id_and_title(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    assert add_movie(client, admin_headers, "Inception", tmdb_id=27205).status_code == 201
    assert add_movie(client, admin_headers, "Inception (DE)", tmdb_id=27205).status_code == 409
    assert add_movie(client, admin_headers, "Ohne TMDB").status_code == 201
    assert add_movie(client, admin_headers, "Ohne TMDB").status_code == 409


def test_carry_over_moves_unwatched_and_clears_votes(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    watched = add_movie(client, admin_headers, "Gesehen").json()["id"]
    kept = add_movie(client, admin_headers, "Bleibt").json()["id"]
    client.post(f"/movies/{kept}/vote", json={"vote_type": "up"}, headers=admin_headers)

    resp = client.post(f"/rounds/{active_round}/complete?watched_movie_id={watched}", headers=admin_headers)
    assert resp.status_code == 200
    second = new_round(client, admin_headers)

    with SessionLocal() as db:
        kept_movie = db.get(Movie, kept)
        watched_movie = db.get(Movie, watched)
        assert kept_movie is not None and watched_movie is not None
        assert kept_movie.round_id == second
        assert kept_movie.rounds_survived == 1
        assert kept_movie.votes == []
        assert watched_movie.is_active is False


def test_movie_drops_out_after_max_rounds(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    movie_id = add_movie(client, admin_headers, "Ladenhüter").json()["id"]
    round_id = active_round
    for _ in range(2):
        client.post(f"/rounds/{round_id}/complete", headers=admin_headers)
        round_id = new_round(client, admin_headers, max_rounds_before_removal=2)
    with SessionLocal() as db:
        movie = db.get(Movie, movie_id)
        assert movie is not None
        assert movie.is_active is False


def test_only_one_active_round(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    resp = client.post(
        "/rounds/", json={"name": "Zweite", "starts_at": datetime.now(timezone.utc).isoformat()}, headers=admin_headers
    )
    assert resp.status_code == 409


def test_invalid_deadline_is_rejected_on_create(client: TestClient, admin_headers: dict[str, str]) -> None:
    body = {"name": "R", "starts_at": datetime.now(timezone.utc).isoformat(), "vote_deadline": "morgen"}
    assert client.post("/rounds/", json=body, headers=admin_headers).status_code == 400
    with SessionLocal() as db:
        assert db.query(Round).count() == 0


def test_naive_deadline_is_berlin_time(client: TestClient, admin_headers: dict[str, str]) -> None:
    new_round(client, admin_headers, vote_deadline="2030-01-15T20:00:00")
    active = client.get("/rounds/active", headers=admin_headers).json()
    # 20:00 CET is 19:00 UTC, and the offset must survive the SQLite round trip.
    assert datetime.fromisoformat(active["vote_deadline"]) == datetime(2030, 1, 15, 19, 0, tzinfo=timezone.utc)


def test_deadline_is_enforced_in_berlin_time(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    movie_id = add_movie(client, admin_headers, "Knapp").json()["id"]
    # A naive deadline 30 minutes ago in Berlin time must already be closed,
    # even though it would still be open if misread as UTC.
    berlin_now = datetime.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
    past = (berlin_now - timedelta(minutes=30)).isoformat(timespec="minutes")
    client.patch(f"/rounds/{active_round}/deadline", json={"vote_deadline": past}, headers=admin_headers)
    assert client.post(f"/movies/{movie_id}/vote", json={"vote_type": "up"}, headers=admin_headers).status_code == 400


def test_no_votes_or_proposals_after_deadline(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    movie_id = add_movie(client, admin_headers, "Spät").json()["id"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert client.patch(f"/rounds/{active_round}/deadline", json={"vote_deadline": past}, headers=admin_headers).status_code == 200

    assert client.post(f"/movies/{movie_id}/vote", json={"vote_type": "up"}, headers=admin_headers).status_code == 400
    assert add_movie(client, admin_headers, "Noch später").status_code == 400


def test_guest_needs_invitation_for_round(client: TestClient, active_round: int) -> None:
    guest_id = make_user("gast")
    h = auth("gast")
    assert client.get("/movies/", headers=h).status_code == 403
    assert client.get("/rounds/active", headers=h).json() is None
    assert client.get("/movies/watched", headers=h).json() == []

    invite_guest(guest_id, active_round)
    assert client.get("/movies/", headers=h).status_code == 200
    assert client.get("/rounds/active", headers=h).json()["id"] == active_round


def test_guest_cannot_manage_rounds(client: TestClient, active_round: int) -> None:
    guest_id = make_user("gast")
    invite_guest(guest_id, active_round)
    h = auth("gast")
    assert client.post(f"/rounds/{active_round}/complete", headers=h).status_code == 403
    assert client.get("/rounds/", headers=h).status_code == 403


def test_users_can_only_remove_own_movies(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    make_user("alice", regular=True)
    make_user("bob", regular=True)
    movie_id = add_movie(client, auth("alice"), "Alices Film").json()["id"]
    assert client.delete(f"/movies/{movie_id}", headers=auth("bob")).status_code == 403
    assert client.delete(f"/movies/{movie_id}", headers=auth("alice")).status_code == 204


def test_watched_history_has_offsets_and_tmdb_ids(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    movie_id = add_movie(client, admin_headers, "Inception", tmdb_id=27205).json()["id"]
    client.post(f"/rounds/{active_round}/complete?watched_movie_id={movie_id}", headers=admin_headers)
    entry = client.get("/movies/watched", headers=admin_headers).json()[0]
    assert entry["movie_tmdb_id"] == 27205
    assert entry["submitted_by_username"] == "admin"
    assert datetime.fromisoformat(entry["watched_at"]).tzinfo is not None


def test_invite_expiry_is_sent_with_offset(client: TestClient, admin_headers: dict[str, str]) -> None:
    client.post("/admin/invites", json={}, headers=admin_headers)
    invite = client.get("/admin/invites", headers=admin_headers).json()[0]
    assert datetime.fromisoformat(invite["expires_at"]).tzinfo is not None


def test_config_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/movies/config", headers=admin_headers).json() == {
        "max_movies_per_user": 3,
        "tmdb_enabled": False,
    }


def test_title_whitespace_does_not_bypass_duplicate_check(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    assert add_movie(client, admin_headers, "Heat").status_code == 201
    assert add_movie(client, admin_headers, "  Heat ").status_code == 409
