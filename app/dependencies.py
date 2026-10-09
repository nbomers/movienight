from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import decode_access_token
from app.database import get_db
from app.models import User

# HTTPBearer extrahiert den Token aus dem Authorization: Bearer <token> Header
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency: Gibt den aktuell eingeloggten User zurück.
    Wirft 401 bei ungültigem/fehlendem Token.
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ungültig oder abgelaufen",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str | None = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token enthält keinen Benutzer",
        )

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden oder deaktiviert",
        )

    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency: Wie get_current_user, aber nur für Admins.
    Wirft 403 wenn der User kein Admin ist.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Adminrechte",
        )
    return current_user


def has_round_access(db: Session, user: User) -> bool:
    """Admins and regulars always; guests only when invited to the active round."""
    from app.models import Round, RoundGuest, RoundStatus

    if user.is_admin or user.is_regular:
        return True
    active_round = db.query(Round).filter(Round.status == RoundStatus.active).first()
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
