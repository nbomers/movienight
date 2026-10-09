import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_round_access

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# The same shapes the movie schema accepts; TMDB data that does not match is
# dropped here instead of failing later when the movie is proposed.
_POSTER_PATH = re.compile(r"^/[A-Za-z0-9_.-]+$")
_YOUTUBE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Lists that change at most daily are cached to save TMDB requests.
_LIST_TTL_SECONDS = 3600
_list_cache: dict[str, tuple[float, list["TMDBMovieResult"]]] = {}


class TMDBMovieResult(BaseModel):
    tmdb_id: int
    title: str
    overview: str | None
    release_year: int | None
    poster_path: str | None  # as stored with a movie, e.g. "/abc.jpg"
    poster_url: str | None  # ready-to-use URL
    genres: str | None  # comma separated, e.g. "Action, Drama"
    vote_average: float | None


class TMDBMovieDetail(TMDBMovieResult):
    trailer_url: str | None
    runtime: int | None  # minutes


def _require_key() -> None:
    if not settings.TMDB_API_KEY or settings.TMDB_API_KEY == "dummy":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TMDB API-Key nicht konfiguriert")


async def _fetch(path: str, **params: Any) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=TMDB_BASE,
        headers={"accept": "application/json"},
        params={"api_key": settings.TMDB_API_KEY, "language": "de-DE"},
        timeout=10.0,
    ) as client:
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Film nicht gefunden") from None
            raise HTTPException(status_code=502, detail=f"TMDB-Fehler: {e.response.status_code}") from None
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="TMDB nicht erreichbar") from None
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _parse_year(release_date: str | None) -> int | None:
    """'2010-07-16' → 2010"""
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _result(m: dict[str, Any]) -> dict[str, Any]:
    poster_path = m.get("poster_path")
    if not isinstance(poster_path, str) or not _POSTER_PATH.match(poster_path):
        poster_path = None
    genres = [g["name"] for g in m.get("genres") or [] if isinstance(g, dict) and g.get("name")]
    return {
        "tmdb_id": m["id"],
        "title": (m.get("title") or m.get("original_title") or "")[:255],
        "overview": (m.get("overview") or None),
        "release_year": _parse_year(m.get("release_date")),
        "poster_path": poster_path,
        "poster_url": f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
        "genres": ", ".join(genres)[:255] or None,
        "vote_average": m.get("vote_average"),
    }


def _trailer_url(videos: list[dict[str, Any]]) -> str | None:
    """Prefer an official German trailer, then any German one, then English."""
    candidates = [
        v for v in videos
        if v.get("site") == "YouTube" and v.get("type") == "Trailer" and _YOUTUBE_KEY.match(str(v.get("key", "")))
    ]
    candidates.sort(key=lambda v: (v.get("iso_639_1") != "de", not v.get("official", False)))
    return f"https://www.youtube.com/watch?v={candidates[0]['key']}" if candidates else None


async def _cached_list(path: str, limit: int, **params: Any) -> list[TMDBMovieResult]:
    now = time.monotonic()
    cached = _list_cache.get(path)
    if cached and now - cached[0] < _LIST_TTL_SECONDS:
        return cached[1]
    data = await _fetch(path, **params)
    results = [TMDBMovieResult(**_result(m)) for m in (data.get("results") or [])[:limit] if "id" in m]
    _list_cache[path] = (now, results)
    return results


# Proposing needs round access, so TMDB is only reachable for the same users.
# Without it, an uninvited guest account could use the server's API key.


@router.get("/search", response_model=list[TMDBMovieResult])
async def search_movies(
    q: str = Query(min_length=1, max_length=100, description="Suchbegriff"),
    _=Depends(get_round_access),
):
    _require_key()
    data = await _fetch("/search/movie", query=q, include_adult=False)
    return [TMDBMovieResult(**_result(m)) for m in (data.get("results") or [])[:10] if "id" in m]


@router.get("/movie/{tmdb_id}", response_model=TMDBMovieDetail)
async def get_movie_detail(tmdb_id: int = Path(ge=1, le=10**9), _=Depends(get_round_access)):
    """Full details including the trailer, fetched in one request."""
    _require_key()
    m = await _fetch(
        f"/movie/{tmdb_id}",
        append_to_response="videos",
        include_video_language="de,en,null",
    )
    if "id" not in m:
        raise HTTPException(status_code=502, detail="TMDB-Fehler")
    videos = (m.get("videos") or {}).get("results") or []
    return TMDBMovieDetail(**_result(m), trailer_url=_trailer_url(videos), runtime=m.get("runtime") or None)


@router.get("/now-playing", response_model=list[TMDBMovieResult])
async def now_playing(_=Depends(get_round_access)):
    _require_key()
    return await _cached_list("/movie/now_playing", 20, region="DE")


@router.get("/popular", response_model=list[TMDBMovieResult])
async def popular(_=Depends(get_round_access)):
    _require_key()
    return await _cached_list("/movie/popular", 20, region="DE")
