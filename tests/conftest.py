import os
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone

# Configure before the app (and its engine) is imported.
_DB_FILE = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update(
    SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
    DATABASE_URL=f"sqlite:///{_DB_FILE}",
    FIRST_ADMIN_USERNAME="admin",
    FIRST_ADMIN_PASSWORD="test-admin-password",
    TMDB_API_KEY="",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, token_for_user  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Round, RoundGuest, User  # noqa: E402
from app.rate_limit import auth_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db() -> Iterator[None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    auth_limiter.reset()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def make_user(username: str, *, admin: bool = False, regular: bool = False) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password("password123"),
            is_admin=admin,
            is_regular=regular,
        )
        db.add(user)
        db.commit()
        return user.id


def auth(username: str) -> dict[str, str]:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        return {"Authorization": f"Bearer {token_for_user(user)}"}


def invite_guest(user_id: int, round_id: int) -> None:
    with SessionLocal() as db:
        db.add(RoundGuest(round_id=round_id, user_id=user_id))
        db.commit()


def get_round(round_id: int) -> Round:
    with SessionLocal() as db:
        round_ = db.get(Round, round_id)
        assert round_ is not None
        return round_


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    # The lifespan hook has created the first admin from the environment.
    return auth("admin")


@pytest.fixture
def active_round(client: TestClient, admin_headers: dict[str, str]) -> int:
    resp = client.post(
        "/rounds/",
        json={"name": "Runde 1", "starts_at": datetime.now(timezone.utc).isoformat()},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
