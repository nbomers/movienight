from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import Round, RoundGuest, User
from app.schemas import RoundGuestAdd, RoundGuestResponse

router = APIRouter(prefix="/rounds", tags=["round-guests"])


@router.get("/{round_id}/guests", response_model=list[RoundGuestResponse])
def list_guests(round_id: int, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    guests = db.query(RoundGuest).filter(RoundGuest.round_id == round_id).all()
    result = []
    for g in guests:
        r = RoundGuestResponse.model_validate(g)
        r.username = g.user.username if g.user else "?"
        result.append(r)
    return result


@router.post("/{round_id}/guests", response_model=RoundGuestResponse, status_code=status.HTTP_201_CREATED)
def add_guest(round_id: int, payload: RoundGuestAdd, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    round_ = db.query(Round).filter(Round.id == round_id).first()
    if not round_:
        raise HTTPException(status_code=404, detail="Runde nicht gefunden")
    user = db.query(User).filter(User.id == payload.user_id, User.is_active == True).first()  # noqa
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    existing = db.query(RoundGuest).filter(
        RoundGuest.round_id == round_id, RoundGuest.user_id == payload.user_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User bereits eingeladen")
    guest = RoundGuest(round_id=round_id, user_id=payload.user_id)
    db.add(guest)
    db.commit()
    db.refresh(guest)
    r = RoundGuestResponse.model_validate(guest)
    r.username = user.username
    return r


@router.delete("/{round_id}/guests/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_guest(round_id: int, user_id: int, db: Session = Depends(get_db), _=Depends(get_current_admin)):
    guest = db.query(RoundGuest).filter(
        RoundGuest.round_id == round_id, RoundGuest.user_id == user_id
    ).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Gast nicht gefunden")
    db.delete(guest)
    db.commit()
