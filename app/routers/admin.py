import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import Comment, InviteToken, Movie, Round, RoundGuest, User, Vote
from app.auth import hash_password
from app.schemas import (
    InviteLabelUpdate,
    InviteTokenCreate,
    InviteTokenResponse,
    PasswordReset,
    UserResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/invites", response_model=InviteTokenResponse, status_code=status.HTTP_201_CREATED)
def create_invite(
    payload: InviteTokenCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Erstellt einen neuen Einladungslink."""
    token_value = secrets.token_urlsafe(32)  # 32 Bytes → 43 Zeichen URL-safe Base64

    invite = InviteToken(
        token=token_value,
        created_by=admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours),
        max_uses=payload.max_uses,
        invite_type=payload.invite_type,
        label=payload.label,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return InviteTokenResponse.from_model(invite)


@router.get("/invites", response_model=list[InviteTokenResponse])
def list_invites(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Listet alle Einladungslinks auf."""
    invites = db.query(InviteToken).order_by(InviteToken.created_at.desc()).all()
    return [InviteTokenResponse.from_model(i) for i in invites]


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User nicht gefunden")
    return user


def _not_self(user: User, admin: User, detail: str) -> None:
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Listet alle User auf."""
    return db.query(User).order_by(User.created_at).all()


@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Deaktiviert einen User (kein Hard-Delete)."""
    user = _get_user(db, user_id)
    _not_self(user, admin, "Eigenen Account nicht deaktivierbar")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/reset-password", response_model=UserResponse)
def reset_user_password(
    user_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Admin setzt Passwort eines Users zurück."""
    user = _get_user(db, user_id)
    user.hashed_password = hash_password(payload.password)
    user.token_version += 1  # log the user out everywhere
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = _get_user(db, user_id)
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/make-admin", response_model=UserResponse)
def make_admin(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = _get_user(db, user_id)
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/revoke-admin", response_model=UserResponse)
def revoke_admin(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = _get_user(db, user_id)
    # Also guarantees that at least one admin (the caller) is left.
    _not_self(user, admin, "Eigene Adminrechte nicht entziehbar")
    user.is_admin = False
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/toggle-regular", response_model=UserResponse)
def toggle_regular(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = _get_user(db, user_id)
    _not_self(user, admin, "Eigenen Status nicht änderbar")
    user.is_regular = not user.is_regular
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = _get_user(db, user_id)
    _not_self(user, admin, "Eigenen Account nicht löschbar")

    db.query(Vote).filter(Vote.user_id == user_id).delete()
    db.query(Comment).filter(Comment.user_id == user_id).delete()
    db.query(RoundGuest).filter(RoundGuest.user_id == user_id).delete()

    # Movies that were watched stay in the history; they now count as
    # proposed by the deleting admin. All other proposals go.
    watched_ids = {
        movie_id for (movie_id,) in db.query(Round.watched_movie_id).filter(Round.watched_movie_id.isnot(None))
    }
    for movie in db.query(Movie).filter(Movie.submitted_by == user_id).all():
        if movie.id in watched_ids:
            movie.submitted_by_user = admin
            continue
        db.query(Vote).filter(Vote.movie_id == movie.id).delete()
        db.query(Comment).filter(Comment.movie_id == movie.id).delete()
        db.delete(movie)

    # Invite links: created_by must point to an existing user.
    db.query(InviteToken).filter(InviteToken.created_by == user_id).update({"created_by": admin.id})
    db.query(InviteToken).filter(InviteToken.used_by == user_id).update({"used_by": None})
    # Drop the cached relationship lists, so the delete does not try to null
    # out foreign keys of rows that were just reassigned.
    db.flush()
    db.expire(user)
    db.delete(user)
    db.commit()


@router.delete("/invites/{invite_id}", status_code=204)
def delete_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    invite = db.query(InviteToken).filter(InviteToken.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Link nicht gefunden")
    db.delete(invite)
    db.commit()


@router.patch("/invites/{invite_id}/label", response_model=InviteTokenResponse)
def rename_invite(
    invite_id: int,
    payload: InviteLabelUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    invite = db.query(InviteToken).filter(InviteToken.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Link nicht gefunden")
    invite.label = payload.label or None
    db.commit()
    db.refresh(invite)
    return InviteTokenResponse.from_model(invite)
