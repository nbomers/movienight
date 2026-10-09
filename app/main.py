from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from app.auth import hash_password
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routers import admin, auth, comments, movies, round_guests, rounds, tmdb, votes

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_admin_exists()
    yield


def _ensure_admin_exists():
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.is_admin == True).first()  # noqa
        if not admin_user:
            if len(settings.FIRST_ADMIN_PASSWORD) < 12:
                raise RuntimeError(
                    "No admin exists yet: set FIRST_ADMIN_PASSWORD (at least 12 characters) "
                    "in .env to create the initial admin account."
                )
            user = User(
                username=settings.FIRST_ADMIN_USERNAME,
                hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(user)
            db.commit()
            print(f"[INIT] Admin-User '{settings.FIRST_ADMIN_USERNAME}' angelegt.")
    finally:
        db.close()


app = FastAPI(title="Filmabend API", version="0.2.0", lifespan=lifespan)

if settings.CORS_ORIGINS:
    # Auth uses a bearer header, not cookies, so credentials are not needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(movies.router)
app.include_router(votes.router)
app.include_router(comments.router)
app.include_router(rounds.router)
app.include_router(round_guests.router)
app.include_router(tmdb.router)

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

    @app.get("/")
    def root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/frontend/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
