from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import decode_access_token
from app.database import get_db
from app.models import Round, RoundGuest, RoundStatus, User

# auto_error=False: a missing header is answered with 401 below instead of
# FastAPI's default 403, so the frontend can treat both cases the same.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """The logged-in user. Every request re-reads the user, so deactivation and
    password changes take effect immediately."""
    if credentials is None:
        raise _unauthorized("Nicht angemeldet")

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise _unauthorized("Token ungültig oder abgelaufen")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise _unauthorized("Token ungültig oder abgelaufen")

    user = db.get(User, int(subject))
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise _unauthorized("Sitzung abgelaufen, bitte neu anmelden")

    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Adminrechte")
    return current_user


def get_active_round(db: Session) -> Round | None:
    return db.query(Round).filter(Round.status == RoundStatus.active).first()


def has_round_access(db: Session, user: User) -> bool:
    """Admins and regulars always; guests only when invited to the active round."""
    if user.is_admin or user.is_regular:
        return True
    active_round = get_active_round(db)
    if not active_round:
        return False
    guest_entry = db.query(RoundGuest).filter(
        RoundGuest.round_id == active_round.id,
        RoundGuest.user_id == user.id,
    ).first()
    return guest_entry is not None


def get_round_access(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    if not has_round_access(db, current_user):
        raise HTTPException(status_code=403, detail="GUEST_NO_ACCESS")
    return current_user
