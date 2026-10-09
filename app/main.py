from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from app.auth import hash_password
from app.config import settings
from app import migrations
from app.database import Base, SessionLocal, engine
from app.models import User
from app.routers import admin, auth, comments, movies, round_guests, rounds, tmdb, votes

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrations.upgrade(engine)
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
            print(f"[INIT] Created admin user '{settings.FIRST_ADMIN_USERNAME}'.")
    finally:
        db.close()


app = FastAPI(title="movienight API", version="1.0.0", lifespan=lifespan)

if settings.CORS_ORIGINS:
    # Auth uses a bearer header, not cookies, so credentials are not needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

# Scripts only from our own files: no inline scripts or event handlers exist
# in the frontend, so an injected <script> or onerror= would not run. Inline
# style attributes are allowed; they cannot execute code.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://image.tmdb.org",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/frontend/"):
            # Revalidate on every load (cheap with ETag), so pages and
            # scripts from different versions are never mixed after an update.
            headers.setdefault("Cache-Control", "no-cache")
        else:
            # API answers contain personal data; keep them out of caches.
            headers.setdefault("Cache-Control", "no-store")
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

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/frontend/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
