from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import burn_password_check, hash_password, token_for_user, verify_password
from app.database import get_db
from app.dependencies import get_active_round, get_current_user
from app.models import InviteToken, InviteType, RoundGuest, User
from app.rate_limit import auth_limiter, client_key
from app.schemas import LoginRequest, PasswordChange, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_INVITE = "Einladungslink ungültig oder bereits verwendet"
_NAME_TAKEN = "Benutzername bereits vergeben"


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Create an account through an invite link."""
    # Every attempt counts here, so invite tokens cannot be guessed in bulk.
    key = client_key(request)
    auth_limiter.ensure_allowed(key)
    auth_limiter.record(key)

    invite = db.query(InviteToken).filter(InviteToken.token == payload.invite_token).first()
    if invite is None or not invite.is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_INVITE)

    # Case-insensitive, so nobody can register "Alex" next to "alex".
    taken = db.query(User).filter(func.lower(User.username) == payload.username.lower()).first()
    if taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NAME_TAKEN)

    # Consume one use atomically: two parallel registrations must not both
    # pass the check above for a single-use link.
    consumed = db.execute(
        update(InviteToken)
        .where(
            InviteToken.id == invite.id,
            or_(InviteToken.max_uses == 0, InviteToken.use_count < InviteToken.max_uses),
        )
        .values(use_count=InviteToken.use_count + 1)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_INVITE)

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        is_regular=(invite.invite_type == InviteType.regular),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NAME_TAKEN) from None

    invite.used_by = user.id  # last user
    invite.used_at = datetime.now(timezone.utc)

    # Guests are invited to the round that is running right now.
    if not user.is_regular:
        active_round = get_active_round(db)
        if active_round:
            db.add(RoundGuest(round_id=active_round.id, user_id=user.id))

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Only failed attempts count, so a group logging in from one home network
    # is not locked out by its own successful logins.
    key = client_key(request)
    auth_limiter.ensure_allowed(key)

    user = db.query(User).filter(User.username == payload.username).first()
    if user is None:
        burn_password_check(payload.password)

    # Same error for both cases: no username enumeration.
    if user is None or not verify_password(payload.password, user.hashed_password):
        auth_limiter.record(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültige Anmeldedaten")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deaktiviert")

    return TokenResponse(access_token=token_for_user(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the own password. All other sessions are logged out; the caller
    gets a fresh token so the current session continues."""
    key = client_key(request)
    auth_limiter.ensure_allowed(key)
    if not verify_password(payload.current_password, current_user.hashed_password):
        auth_limiter.record(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aktuelles Passwort ist falsch")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.token_version += 1
    db.commit()
    db.refresh(current_user)
    return TokenResponse(access_token=token_for_user(current_user))
