from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_active_round, get_current_user, get_round_access, has_round_access
from app.models import Comment, Movie, Round, RoundStatus, Vote, VoteType
from app.routers.votes import has_used_superlike
from app.schemas import AppConfig, MovieCreate, MovieResponse, WatchedEntry

router = APIRouter(prefix="/movies", tags=["movies"])


def _build_movie_response(
    movie: Movie, current_user_id: int, superlike_available: bool, read_only: bool = False
) -> MovieResponse:
    data = MovieResponse.model_validate(movie)
    data.upvotes = sum(1 for v in movie.votes if v.vote_type == VoteType.up)
    data.downvotes = sum(1 for v in movie.votes if v.vote_type == VoteType.down)
    data.superlikes = sum(1 for v in movie.votes if v.vote_type == VoteType.superlike)
    data.user_vote = next((v.vote_type for v in movie.votes if v.user_id == current_user_id), None)
    data.superlike_usernames = [
        v.user.username for v in movie.votes if v.vote_type == VoteType.superlike and v.user
    ]
    data.superlike_available = superlike_available
    data.submitted_by_username = movie.submitted_by_user.username if movie.submitted_by_user else "?"
    data.comment_count = len(movie.comments)
    data.read_only = read_only
    return data


def _round_movies(db: Session, round_id: int) -> list[Movie]:
    # Loads votes, voters, comments and submitters in a few queries instead of
    # several per movie.
    return (
        db.query(Movie)
        .options(
            selectinload(Movie.votes).joinedload(Vote.user),
            selectinload(Movie.comments).load_only(Comment.id),
            joinedload(Movie.submitted_by_user),
        )
        .filter(Movie.is_active == True, Movie.round_id == round_id)  # noqa
        .order_by(Movie.created_at)
        .all()
    )


@router.get("/config", response_model=AppConfig)
def app_config(_=Depends(get_current_user)):
    """Settings the frontend needs to render limits and the proposal form."""
    return AppConfig(
        max_movies_per_user=settings.MAX_MOVIES_PER_USER,
        tmdb_enabled=bool(settings.TMDB_API_KEY) and settings.TMDB_API_KEY != "dummy",
    )


@router.get("/", response_model=list[MovieResponse])
def list_movies(db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    active_round = get_active_round(db)
    if active_round:
        available = not has_used_superlike(db, current_user.id, active_round.id)
        return [_build_movie_response(m, current_user.id, available) for m in _round_movies(db, active_round.id)]

    # get_round_access already turns away guests without an active round.
    if not current_user.is_admin and not current_user.is_regular:
        return []

    # Without an active round, regulars and admins see the last round read-only.
    last_completed = (
        db.query(Round).filter(Round.status == RoundStatus.completed).order_by(Round.ends_at.desc()).first()
    )
    if not last_completed:
        return []
    return [
        _build_movie_response(m, current_user.id, False, read_only=True)
        for m in _round_movies(db, last_completed.id)
    ]


@router.get("/watched", response_model=list[WatchedEntry])
def list_watched(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """All watched movies with the date of the movie night."""
    # Guests without access get an empty list rather than an error, matching
    # what they see on the other tabs.
    if not has_round_access(db, current_user):
        return []
    rounds = (
        db.query(Round)
        .options(joinedload(Round.watched_movie).joinedload(Movie.submitted_by_user))
        .filter(Round.status == RoundStatus.completed, Round.watched_movie_id.isnot(None))
        .order_by(Round.ends_at.desc())
        .all()
    )
    return [
        WatchedEntry(
            round_id=r.id,
            round_name=r.name,
            watched_at=r.ends_at,
            movie_id=r.watched_movie.id,
            movie_tmdb_id=r.watched_movie.tmdb_id,
            movie_title=r.watched_movie.title,
            movie_poster_path=r.watched_movie.poster_path,
            movie_release_year=r.watched_movie.release_year,
            movie_genres=r.watched_movie.genres,
            submitted_by_username=(
                r.watched_movie.submitted_by_user.username if r.watched_movie.submitted_by_user else "?"
            ),
        )
        for r in rounds
        if r.watched_movie
    ]


@router.post("/", response_model=MovieResponse, status_code=status.HTTP_201_CREATED)
def add_movie(payload: MovieCreate, db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    active_round = get_active_round(db)
    if not active_round:
        raise HTTPException(status_code=400, detail="Kein aktiver Filmabend — Vorschläge nicht möglich")
    if active_round.voting_closed:
        raise HTTPException(status_code=400, detail="Abstimmung ist geschlossen — keine neuen Vorschläge möglich")

    # Duplicates only count within the current round.
    duplicate = db.query(Movie).filter(Movie.is_active == True, Movie.round_id == active_round.id)  # noqa
    if payload.tmdb_id:
        duplicate = duplicate.filter(Movie.tmdb_id == payload.tmdb_id)
    else:
        duplicate = duplicate.filter(Movie.title == payload.title)
    existing = duplicate.first()
    if existing:
        raise HTTPException(status_code=409, detail=f'"{existing.title}" ist bereits vorgeschlagen')

    if not current_user.is_admin:
        user_count = db.query(Movie).filter(
            Movie.submitted_by == current_user.id,
            Movie.is_active == True,  # noqa
            Movie.round_id == active_round.id,
        ).count()
        if user_count >= settings.MAX_MOVIES_PER_USER:
            raise HTTPException(
                status_code=400,
                detail=f"Du hast bereits {settings.MAX_MOVIES_PER_USER} Vorschläge für diese Runde",
            )

    movie = Movie(**payload.model_dump(), submitted_by=current_user.id, round_id=active_round.id)
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
    active_round = get_active_round(db)
    if not current_user.is_admin and (not active_round or movie.round_id != active_round.id):
        raise HTTPException(status_code=400, detail="Nur Filme der laufenden Runde können entfernt werden")
    db.query(Vote).filter(Vote.movie_id == movie.id).delete()
    db.query(Comment).filter(Comment.movie_id == movie.id).delete()
    movie.is_active = False
    db.commit()
