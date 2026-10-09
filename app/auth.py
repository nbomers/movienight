from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt only looks at the first 72 bytes. Truncating explicitly keeps hashes
# created by the previous passlib-based implementation verifiable.
_BCRYPT_MAX_BYTES = 72


def _encode_password(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_encode_password(plain_password), hashed_password.encode("ascii"))
    except ValueError:
        return False


# Checked when a login names an unknown user, so that the response takes as
# long as for a wrong password and does not reveal which usernames exist.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode("ascii")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT. Use `token_for_user` for login tokens."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def token_for_user(user: Any) -> str:
    """Login token bound to the user's id and current token version.

    The id (not the username) is the subject, so a token can never pass for a
    different account that later registers with the same name.
    """
    return create_access_token({"sub": str(user.id), "ver": user.token_version})


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns None for invalid or expired tokens."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None
