import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import InviteToken, User
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
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User nicht gefunden")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eigenen Account nicht deaktivierbar",
        )
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
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User nicht gefunden")
    user.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/make-admin", response_model=UserResponse)
def make_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Gibt einem User Admin-Rechte."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User nicht gefunden")
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/toggle-regular", response_model=UserResponse)
def toggle_regular(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenen Status nicht änderbar")
    user.is_regular = not user.is_regular
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    from app.models import Vote, Comment, Movie, RoundGuest, InviteToken
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht löschbar")
    # Alle abhängigen Daten löschen
    db.query(Vote).filter(Vote.user_id == user_id).delete()
    db.query(Comment).filter(Comment.user_id == user_id).delete()
    db.query(RoundGuest).filter(RoundGuest.user_id == user_id).delete()
    # Filme des Users: Votes/Kommentare auf diese Filme auch weg
    user_movies = db.query(Movie).filter(Movie.submitted_by == user_id).all()
    for m in user_movies:
        db.query(Vote).filter(Vote.movie_id == m.id).delete()
        db.query(Comment).filter(Comment.movie_id == m.id).delete()
        db.delete(m)
    # Einladungslinks die der User erstellt hat: created_by kann nicht null sein,
    # aber da nur Admins Links erstellen und Admins sich nicht selbst löschen, ok
    db.query(InviteToken).filter(InviteToken.used_by == user_id).update({"used_by": None})
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
