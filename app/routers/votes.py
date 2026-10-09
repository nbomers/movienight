from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_round_access
from app.models import Movie, Round, RoundStatus, Vote, VoteType
from app.schemas import VoteRequest, VoteResponse

router = APIRouter(prefix="/movies", tags=["votes"])


def has_used_superlike(db: Session, user_id: int, round_id: int) -> bool:
    """One superlike per user and round. Derived from the votes themselves, so
    it resets with the round and is freed when the movie is removed."""
    return (
        db.query(Vote)
        .filter(
            Vote.user_id == user_id,
            Vote.round_id == round_id,
            Vote.vote_type == VoteType.superlike,
        )
        .first()
        is not None
    )


@router.post(
    "/{movie_id}/vote",
    response_model=VoteResponse,
    responses={204: {"description": "Vote entfernt (gleicher Typ erneut gesendet)"}},
)
def vote(
    movie_id: int,
    payload: VoteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_round_access),
):
    active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()
    if not active_round:
        raise HTTPException(status_code=400, detail="Abstimmung nur während einer aktiven Runde möglich")

    # Only movies of the running round can be voted on. Without this check
    # any active movie id (e.g. one left over from an older round) counted.
    movie = db.query(Movie).filter(
        Movie.id == movie_id,
        Movie.is_active == True,  # noqa
        Movie.round_id == active_round.id,
    ).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Film nicht gefunden")

    if active_round.vote_deadline:
        deadline = active_round.vote_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > deadline:
            raise HTTPException(status_code=400, detail="Abstimmung ist geschlossen — Deadline abgelaufen")

    round_id = active_round.id

    # Vote strikt pro Runde - kein Fallback auf andere Runden
    existing = (
        db.query(Vote)
        .filter(Vote.user_id == current_user.id, Vote.movie_id == movie_id, Vote.round_id == round_id)
        .first()
    )

    # Same type again toggles the vote off.
    if existing and existing.vote_type == payload.vote_type:
        db.delete(existing)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if payload.vote_type == VoteType.superlike and has_used_superlike(db, current_user.id, round_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Du hast deinen Superlike bereits vergeben",
        )

    if existing:
        existing.vote_type = payload.vote_type
        db.commit()
        db.refresh(existing)
        return existing

    new_vote = Vote(
        user_id=current_user.id,
        movie_id=movie_id,
        vote_type=payload.vote_type,
        round_id=round_id,
    )
    db.add(new_vote)
    try:
        db.commit()
    except IntegrityError:
        # A parallel request (double tap) created the vote first.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stimme wurde bereits gezählt") from None
    db.refresh(new_vote)
    return new_vote
