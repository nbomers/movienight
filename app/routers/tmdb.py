import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


# ── Response-Schemas ──────────────────────────────────────────────────────────

class TMDBMovieResult(BaseModel):
    tmdb_id: int
    title: str
    overview: str | None
    release_year: int | None
    poster_url: str | None   # Fertige URL, nicht nur der Pfad
    genres: str | None       # Komma-separiert, z.B. "Action, Drama"
    vote_average: float | None


class TMDBMovieDetail(TMDBMovieResult):
    trailer_url: str | None  # YouTube-Link falls vorhanden
    runtime: int | None      # Minuten


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _get_client() -> httpx.AsyncClient:
    """Gibt einen konfigurierten TMDB-Client zurück."""
    return httpx.AsyncClient(
        base_url=TMDB_BASE,
        headers={"accept": "application/json"},
        params={"api_key": settings.TMDB_API_KEY},
        timeout=10.0,
    )


def _parse_year(release_date: str | None) -> int | None:
    """'2010-07-16' → 2010"""
    if release_date and len(release_date) >= 4:
        try:
            return int(release_date[:4])
        except ValueError:
            return None
    return None


def _poster_url(path: str | None) -> str | None:
    if path:
        return f"{TMDB_IMAGE_BASE}{path}"
    return None


def _genres_str(genre_list: list[dict]) -> str | None:
    """[{"id": 28, "name": "Action"}, ...] → 'Action, Drama'"""
    names = [g["name"] for g in genre_list if "name" in g]
    return ", ".join(names) if names else None


async def _get_trailer_url(client: httpx.AsyncClient, tmdb_id: int) -> str | None:
    """Sucht den offiziellen YouTube-Trailer zu einem Film."""
    try:
        resp = await client.get(f"/movie/{tmdb_id}/videos", params={"language": "de-DE", "api_key": settings.TMDB_API_KEY})
        if resp.status_code != 200:
            # Fallback auf Englisch
            resp = await client.get(f"/movie/{tmdb_id}/videos", params={"language": "en-US", "api_key": settings.TMDB_API_KEY})
        data = resp.json()
        videos = data.get("results", [])

        # Priorität: offizieller Trailer auf YouTube
        for video in videos:
            if (
                video.get("site") == "YouTube"
                and video.get("type") == "Trailer"
                and video.get("official", False)
            ):
                return f"https://www.youtube.com/watch?v={video['key']}"

        # Fallback: irgendein YouTube-Trailer
        for video in videos:
            if video.get("site") == "YouTube" and video.get("type") == "Trailer":
                return f"https://www.youtube.com/watch?v={video['key']}"

    except Exception:
        pass
    return None


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@router.get("/search", response_model=list[TMDBMovieResult])
async def search_movies(
    q: str = Query(min_length=1, description="Suchbegriff"),
    _=Depends(get_current_user),
):
    """
    Sucht Filme auf TMDB.
    Gibt die Top-10 Ergebnisse zurück, gefiltert und aufbereitet.
    """
    if not settings.TMDB_API_KEY or settings.TMDB_API_KEY == "dummy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDB API-Key nicht konfiguriert",
        )

    async with _get_client() as client:
        try:
            resp = await client.get(
                "/search/movie",
                params={"query": q, "language": "de-DE", "include_adult": False, "api_key": settings.TMDB_API_KEY},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"TMDB-Fehler: {e.response.status_code}",
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="TMDB nicht erreichbar",
            )

        results = resp.json().get("results", [])[:10]

        return [
            TMDBMovieResult(
                tmdb_id=m["id"],
                title=m.get("title") or m.get("original_title", ""),
                overview=m.get("overview") or None,
                release_year=_parse_year(m.get("release_date")),
                poster_url=_poster_url(m.get("poster_path")),
                genres=None,  # Suche gibt keine Genre-Objekte zurück, nur IDs
                vote_average=m.get("vote_average"),
            )
            for m in results
        ]


@router.get("/movie/{tmdb_id}", response_model=TMDBMovieDetail)
async def get_movie_detail(
    tmdb_id: int,
    _=Depends(get_current_user),
):
    """
    Holt vollständige Details zu einem Film von TMDB inkl. Trailer-URL.
    Wird aufgerufen wenn der User einen Film aus der Suche auswählt.
    """
    if not settings.TMDB_API_KEY or settings.TMDB_API_KEY == "dummy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDB API-Key nicht konfiguriert",
        )

    async with _get_client() as client:
        try:
            resp = await client.get(
                f"/movie/{tmdb_id}",
                params={"language": "de-DE", "api_key": settings.TMDB_API_KEY},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Film nicht gefunden")
            raise HTTPException(status_code=502, detail="TMDB-Fehler")
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="TMDB nicht erreichbar")

        m = resp.json()
        trailer_url = await _get_trailer_url(client, tmdb_id)

        return TMDBMovieDetail(
            tmdb_id=m["id"],
            title=m.get("title") or m.get("original_title", ""),
            overview=m.get("overview") or None,
            release_year=_parse_year(m.get("release_date")),
            poster_url=_poster_url(m.get("poster_path")),
            genres=_genres_str(m.get("genres", [])),
            vote_average=m.get("vote_average"),
            trailer_url=trailer_url,
            runtime=m.get("runtime") or None,
        )


@router.get("/now-playing", response_model=list[TMDBMovieResult])
async def now_playing(_=Depends(get_current_user)):
    """Aktuelle Kinofilme."""
    if not settings.TMDB_API_KEY or settings.TMDB_API_KEY == "dummy":
        raise HTTPException(status_code=503, detail="TMDB API-Key nicht konfiguriert")

    async with _get_client() as client:
        try:
            resp = await client.get(
                "/movie/now_playing",
                params={"language": "de-DE", "region": "DE", "api_key": settings.TMDB_API_KEY},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"TMDB-Fehler: {e.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="TMDB nicht erreichbar")

        results = resp.json().get("results", [])[:20]
        return [
            TMDBMovieResult(
                tmdb_id=m["id"],
                title=m.get("title") or m.get("original_title", ""),
                overview=m.get("overview") or None,
                release_year=_parse_year(m.get("release_date")),
                poster_url=_poster_url(m.get("poster_path")),
                genres=None,
                vote_average=m.get("vote_average"),
            )
            for m in results
        ]


@router.get("/popular", response_model=list[TMDBMovieResult])
async def popular(_=Depends(get_current_user)):
    """Beliebte Filme von TMDB."""
    if not settings.TMDB_API_KEY or settings.TMDB_API_KEY == "dummy":
        raise HTTPException(status_code=503, detail="TMDB API-Key nicht konfiguriert")

    async with _get_client() as client:
        try:
            resp = await client.get(
                "/movie/popular",
                params={"language": "de-DE", "region": "DE", "api_key": settings.TMDB_API_KEY},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"TMDB-Fehler: {e.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="TMDB nicht erreichbar")

        results = resp.json().get("results", [])[:20]
        return [
            TMDBMovieResult(
                tmdb_id=m["id"],
                title=m.get("title") or m.get("original_title", ""),
                overview=m.get("overview") or None,
                release_year=_parse_year(m.get("release_date")),
                poster_url=_poster_url(m.get("poster_path")),
                genres=None,
                vote_average=m.get("vote_average"),
            )
            for m in results
        ]
