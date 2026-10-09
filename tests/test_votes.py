from fastapi.testclient import TestClient

from .conftest import auth, make_user


def _movie(client: TestClient, headers: dict[str, str], title: str) -> int:
    resp = client.post("/movies/", json={"title": title}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _vote(client: TestClient, headers: dict[str, str], movie_id: int, vote_type: str):
    return client.post(f"/movies/{movie_id}/vote", json={"vote_type": vote_type}, headers=headers)


def _superlike_available(client: TestClient, headers: dict[str, str]) -> bool:
    return client.get("/movies/", headers=headers).json()[0]["superlike_available"]


def test_same_vote_twice_toggles_off(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    movie_id = _movie(client, admin_headers, "A")
    assert _vote(client, admin_headers, movie_id, "up").status_code == 200
    assert _vote(client, admin_headers, movie_id, "up").status_code == 204
    assert client.get("/movies/", headers=admin_headers).json()[0]["upvotes"] == 0


def test_one_superlike_per_round(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    make_user("alice", regular=True)
    h = auth("alice")
    a = _movie(client, admin_headers, "A")
    b = _movie(client, admin_headers, "B")

    assert _vote(client, h, a, "superlike").status_code == 200
    assert not _superlike_available(client, h)
    assert _vote(client, h, b, "superlike").status_code == 400

    # Switching the superlike to a normal vote frees it again.
    assert _vote(client, h, a, "up").status_code == 200
    assert _superlike_available(client, h)
    assert _vote(client, h, b, "superlike").status_code == 200


def test_superlike_is_freed_when_movie_is_removed(
    client: TestClient, admin_headers: dict[str, str], active_round: int
) -> None:
    make_user("alice", regular=True)
    h = auth("alice")
    a = _movie(client, admin_headers, "A")
    b = _movie(client, admin_headers, "B")
    _vote(client, h, a, "superlike")
    assert client.delete(f"/movies/{a}", headers=admin_headers).status_code == 204
    assert _vote(client, h, b, "superlike").status_code == 200


def test_superlike_resets_with_new_round(client: TestClient, admin_headers: dict[str, str], active_round: int) -> None:
    from datetime import datetime, timezone

    a = _movie(client, admin_headers, "A")
    _vote(client, admin_headers, a, "superlike")
    client.post(f"/rounds/{active_round}/complete", headers=admin_headers)
    client.post(
        "/rounds/", json={"name": "R2", "starts_at": datetime.now(timezone.utc).isoformat()}, headers=admin_headers
    )
    assert _superlike_available(client, admin_headers)
    assert _vote(client, admin_headers, a, "superlike").status_code == 200
