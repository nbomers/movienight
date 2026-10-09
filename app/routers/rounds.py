from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_active_round, get_current_admin, get_current_user, has_round_access
from app.models import Movie, Round, RoundStatus, Vote
from app.schemas import DeadlineUpdate, RoundCreate, RoundRename, RoundResponse

router = APIRouter(prefix="/rounds", tags=["rounds"])

LOCAL_TZ = ZoneInfo("Europe/Berlin")


def parse_deadline(value: str | None) -> datetime | None:
    """Parse an ISO deadline. Naive values are local time in Europe/Berlin,
    because that is what the admin picks in the UI.

    The result is converted to UTC because SQLite drops the offset on storage
    and every reader treats stored datetimes as UTC.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(timezone.utc)


@router.get("/", response_model=list[RoundResponse])
def list_rounds(db: Session = Depends(get_db), _=Depends(get_current_admin)):
    return db.query(Round).order_by(Round.starts_at.desc()).all()


@router.get("/active", response_model=RoundResponse | None)
def get_active_round_endpoint(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """The running round, or null. Guests only see it when invited."""
    round_ = get_active_round(db)
    if not round_ or not has_round_access(db, current_user):
        return None
    return round_


@router.post("/", response_model=RoundResponse, status_code=status.HTTP_201_CREATED)
def create_round(payload: RoundCreate, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    if get_active_round(db):
        raise HTTPException(status_code=409, detail="Es gibt bereits eine aktive Runde")

    vote_deadline = parse_deadline(payload.vote_deadline)

    round_ = Round(
        name=payload.name,
        starts_at=payload.starts_at,
        vote_deadline=vote_deadline,
    )
    db.add(round_)

    db.flush()  # round_.id verfügbar machen

    last_completed = db.query(Round).filter(Round.status == RoundStatus.completed).order_by(Round.ends_at.desc()).first()
    if last_completed:
        # Nur Filme aus der LETZTEN abgeschlossenen Runde übernehmen,
        # die nicht als geschaut markiert wurden
        carried = db.query(Movie).filter(
            Movie.round_id == last_completed.id,
            Movie.is_active == True,  # noqa
            Movie.id != last_completed.watched_movie_id
        ).all()
        max_rounds = payload.max_rounds_before_removal
        for movie in carried:
            movie.rounds_survived += 1
            if movie.rounds_survived >= max_rounds:
                movie.is_active = False
            else:
                # In neue Runde übernehmen + alle Votes des Films löschen
                movie.round_id = round_.id
                db.query(Vote).filter(Vote.movie_id == movie.id).delete()

    db.commit()
    db.refresh(round_)
    return round_


@router.post("/{round_id}/complete", response_model=RoundResponse)
def complete_round(round_id: int, watched_movie_id: int | None = None, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(status_code=404, detail="Runde nicht gefunden")
    if round_.status != RoundStatus.active:
        raise HTTPException(status_code=400, detail="Runde ist nicht aktiv")

    if watched_movie_id is not None:
        movie = db.query(Movie).filter(
            Movie.id == watched_movie_id,
            Movie.round_id == round_.id,
            Movie.is_active == True,  # noqa
        ).first()
        if not movie:
            raise HTTPException(status_code=400, detail="Film gehört nicht zu dieser Runde")
        round_.watched_movie_id = movie.id
        movie.is_active = False

    round_.status = RoundStatus.completed
    round_.ends_at = datetime.now(timezone.utc)

    # Alle Votes zurücksetzen nach jeder Runde
    db.query(Vote).filter(Vote.round_id == round_id).delete()
    db.commit()
    db.refresh(round_)
    return round_


@router.patch("/{round_id}/set-watched", response_model=RoundResponse)
def set_watched_movie(
    round_id: int,
    watched_movie_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Film nachträglich als gesehen markieren auf abgeschlossener Runde."""
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(status_code=404, detail="Runde nicht gefunden")
    if round_.status != RoundStatus.completed:
        raise HTTPException(status_code=400, detail="Nur abgeschlossene Runden")
    if round_.watched_movie_id is not None:
        raise HTTPException(status_code=409, detail="Für diese Runde ist bereits ein Film markiert")
    movie = db.query(Movie).filter(Movie.id == watched_movie_id, Movie.is_active == True).first()  # noqa
    if not movie:
        raise HTTPException(status_code=404, detail="Film nicht gefunden")
    round_.watched_movie_id = watched_movie_id
    movie.is_active = False
    db.commit()
    db.refresh(round_)
    return round_


@router.patch("/{round_id}/rename", response_model=RoundResponse)
def rename_round(round_id: int, payload: RoundRename, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(status_code=404, detail="Runde nicht gefunden")
    round_.name = payload.name
    db.commit()
    db.refresh(round_)
    return round_


@router.patch("/{round_id}/deadline", response_model=RoundResponse)
def update_deadline(
    round_id: int,
    payload: DeadlineUpdate,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Deadline einer laufenden Runde ändern."""
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(status_code=404, detail="Runde nicht gefunden")
    if round_.status != RoundStatus.active:
        raise HTTPException(status_code=400, detail="Runde ist nicht aktiv")
    round_.vote_deadline = parse_deadline(payload.vote_deadline)
    db.commit()
    db.refresh(round_)
    return round_
