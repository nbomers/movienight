from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_round_access, has_round_access
from app.models import Movie, Round, RoundStatus, VoteType
from app.routers.votes import has_used_superlike
from app.schemas import MovieCreate, MovieResponse

router = APIRouter(prefix="/movies", tags=["movies"])


def _build_movie_response(movie: Movie, current_user_id: int, superlike_available: bool, read_only: bool = False) -> MovieResponse:
    upvotes = sum(1 for v in movie.votes if v.vote_type == VoteType.up)
    downvotes = sum(1 for v in movie.votes if v.vote_type == VoteType.down)
    superlikes = sum(1 for v in movie.votes if v.vote_type == VoteType.superlike)
    user_vote = next((v.vote_type for v in movie.votes if v.user_id == current_user_id), None)
    # Who superliked
    superlike_usernames = [
        v.user.username for v in movie.votes
        if v.vote_type == VoteType.superlike and v.user
    ]
    data = MovieResponse.model_validate(movie)
    data.upvotes = upvotes
    data.downvotes = downvotes
    data.superlikes = superlikes
    data.user_vote = user_vote
    data.superlike_available = superlike_available
    data.submitted_by_username = movie.submitted_by_user.username if movie.submitted_by_user else "?"
    data.comment_count = len(movie.comments)
    data.superlike_usernames = superlike_usernames
    data.read_only = read_only
    return data


@router.get("/", response_model=list[MovieResponse])
def list_movies(db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()

    if active_round:
        movies = db.query(Movie).filter(
            Movie.is_active == True,  # noqa
            Movie.round_id == active_round.id
        ).all()
        available = not has_used_superlike(db, current_user.id, active_round.id)
        return [_build_movie_response(m, current_user.id, available, read_only=False) for m in movies]

    # Keine aktive Runde: Gäste sehen nichts (get_round_access hätte sie sonst
    # schon mit GUEST_NO_ACCESS abgewiesen, aber sicherheitshalber nochmal prüfen)
    if not current_user.is_admin and not current_user.is_regular:
        return []

    # Stammgäste/Admins sehen die Filme der letzten abgeschlossenen Runde, read-only
    last_completed = db.query(Round).filter(
        Round.status == RoundStatus.completed
    ).order_by(Round.ends_at.desc()).first()
    if not last_completed:
        return []

    movies = db.query(Movie).filter(
        Movie.is_active == True,  # noqa
        Movie.round_id == last_completed.id
    ).all()
    return [_build_movie_response(m, current_user.id, False, read_only=True) for m in movies]


@router.get("/watched", response_model=list[dict])
def list_watched(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Alle geschauten Filme mit Datum des Filmabends."""
    # Guests without access get an empty list rather than an error, matching
    # what they see on the other tabs.
    if not has_round_access(db, current_user):
        return []
    from app.models import Round as R
    rounds = db.query(R).filter(
        R.status == RoundStatus.completed,
        R.watched_movie_id != None  # noqa
    ).order_by(R.ends_at.desc()).all()

    result = []
    for r in rounds:
        if r.watched_movie and r.watched_movie.title:
            ends_at = r.ends_at
            if ends_at and ends_at.tzinfo is None:
                from datetime import timezone as _tz
                ends_at = ends_at.replace(tzinfo=_tz.utc)
            result.append({
                "round_id": r.id,
                "round_name": r.name,
                "watched_at": ends_at.isoformat() if ends_at else None,
                "movie_id": r.watched_movie.id,
                "movie_title": r.watched_movie.title,
                "movie_poster_path": r.watched_movie.poster_path,
                "movie_release_year": r.watched_movie.release_year,
                "movie_genres": r.watched_movie.genres,
            })
    return result


@router.post("/", response_model=MovieResponse, status_code=status.HTTP_201_CREATED)
def add_movie(payload: MovieCreate, db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    # Vorschlagen nur bei aktiver Runde
    active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()
    if not active_round:
        raise HTTPException(status_code=400, detail="Kein aktiver Filmabend — Vorschläge nicht möglich")

    # Nach Ablauf der Abstimmungs-Deadline auch keine neuen Vorschläge mehr
    if active_round.vote_deadline:
        from datetime import timezone as _tz
        deadline = active_round.vote_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=_tz.utc)
        if datetime.now(_tz.utc) > deadline:
            raise HTTPException(status_code=400, detail="Abstimmung ist geschlossen — keine neuen Vorschläge möglich")

    # Duplicate check - nur innerhalb der aktuellen Runde
    if payload.tmdb_id:
        existing = db.query(Movie).filter(
            Movie.tmdb_id == payload.tmdb_id, Movie.is_active == True,  # noqa
            Movie.round_id == active_round.id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f'"{existing.title}" ist bereits vorgeschlagen')
    else:
        existing = db.query(Movie).filter(
            Movie.title == payload.title, Movie.is_active == True,  # noqa
            Movie.round_id == active_round.id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f'"{existing.title}" ist bereits vorgeschlagen')

    # Per-user limit check
    max_movies = 3

    if not current_user.is_admin:
        user_count = db.query(Movie).filter(
            Movie.submitted_by == current_user.id,
            Movie.is_active == True,  # noqa
            Movie.round_id == active_round.id
        ).count()
        if user_count >= max_movies:
            raise HTTPException(
                status_code=400,
                detail=f"Du hast bereits {max_movies} Vorschläge für diese Runde"
            )

    movie = Movie(**payload.model_dump(), submitted_by=current_user.id,
                  round_id=active_round.id)
    db.add(movie)
    db.commit()
    db.refresh(movie)
    available = not has_used_superlike(db, current_user.id, active_round.id)
    return _build_movie_response(movie, current_user.id, available)


@router.delete("/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_movie(movie_id: int, db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    movie = db.query(Movie).filter(Movie.id == movie_id, Movie.is_active == True).first()  # noqa
    if not movie:
        raise HTTPException(status_code=404, detail="Film nicht gefunden")
    if movie.submitted_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Du kannst nur eigene Filme entfernen")
    # Outside the running round the view is read-only; only admins clean up.
    active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()
    if not current_user.is_admin and (not active_round or movie.round_id != active_round.id):
        raise HTTPException(status_code=400, detail="Nur Filme der laufenden Runde können entfernt werden")
    from app.models import Vote as _V, Comment as _C
    db.query(_V).filter(_V.movie_id == movie.id).delete()
    db.query(_C).filter(_C.movie_id == movie.id).delete()
    movie.is_active = False
    db.commit()
