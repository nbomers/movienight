from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import hash_password, token_for_user, verify_password
from app.database import get_db
from app.dependencies import get_current_user
from app.models import InviteToken, User
from app.rate_limit import auth_limiter, client_key
from app.schemas import LoginRequest, PasswordChange, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """
    Registrierung via Einladungslink.
    1. Token validieren
    2. Username-Duplikat prüfen
    3. User anlegen, Token als verbraucht markieren
    """
    # Every attempt counts here, so invite tokens cannot be guessed in bulk.
    key = client_key(request)
    auth_limiter.ensure_allowed(key)
    auth_limiter.record(key)

    # Token suchen
    invite = db.query(InviteToken).filter(InviteToken.token == payload.invite_token).first()
    if invite is None or not invite.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Einladungslink ungültig oder bereits verwendet",
        )

    # Username-Duplikat
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Benutzername bereits vergeben",
        )

    # User anlegen - Stammgast wenn invite_type == regular
    from app.models import InviteType
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        is_regular=(invite.invite_type == InviteType.regular),
    )
    db.add(user)
    db.flush()  # ID generieren ohne Commit

    # Token verbrauchen
    invite.use_count += 1
    invite.used_by = user.id  # letzter Nutzer
    invite.used_at = datetime.now(timezone.utc)

    # Gast automatisch zur aktiven Runde einladen wenn eine läuft
    if not user.is_regular and not user.is_admin:
        from app.models import Round, RoundStatus, RoundGuest
        active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()
        if active_round:
            db.add(RoundGuest(round_id=active_round.id, user_id=user.id))

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """
    Login mit Username + Passwort.
    Gibt JWT zurück bei Erfolg.
    """
    # Only failed attempts count, so a group logging in from one home network
    # is not locked out by its own successful logins.
    key = client_key(request)
    auth_limiter.ensure_allowed(key)

    user = db.query(User).filter(User.username == payload.username).first()

    # Beide Checks bewusst mit demselben Fehler — kein Username-Enumeration
    if user is None or not verify_password(payload.password, user.hashed_password):
        auth_limiter.record(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Anmeldedaten",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deaktiviert",
        )

    return TokenResponse(access_token=token_for_user(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Gibt den aktuell eingeloggten User zurück."""
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
