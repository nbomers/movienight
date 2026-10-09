import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import tmdb

from .conftest import auth, make_user


def test_trailer_prefers_german_official() -> None:
    videos = [
        {"site": "YouTube", "type": "Trailer", "key": "en1", "iso_639_1": "en", "official": True},
        {"site": "YouTube", "type": "Trailer", "key": "de2", "iso_639_1": "de", "official": False},
        {"site": "YouTube", "type": "Trailer", "key": "de1", "iso_639_1": "de", "official": True},
        {"site": "Vimeo", "type": "Trailer", "key": "x", "iso_639_1": "de", "official": True},
    ]
    assert tmdb._trailer_url(videos) == "https://www.youtube.com/watch?v=de1"


def test_trailer_rejects_odd_keys() -> None:
    videos = [{"site": "YouTube", "type": "Trailer", "key": 'a" onclick="x', "iso_639_1": "de"}]
    assert tmdb._trailer_url(videos) is None


def test_result_drops_unexpected_poster_path() -> None:
    result = tmdb._result({"id": 1, "title": "X", "poster_path": "https://evil.example/x.jpg"})
    assert result["poster_path"] is None and result["poster_url"] is None


def test_uninvited_guest_cannot_use_tmdb(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TMDB_API_KEY", "set")
    make_user("gast")
    assert client.get("/tmdb/search?q=abc", headers=auth("gast")).status_code == 403


def test_search_query_length_is_limited(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/tmdb/search?q=" + "x" * 101, headers=admin_headers).status_code == 422
