import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowLimiter:
    """In-memory attempt counter per key.

    Sufficient for a single uvicorn worker. With several workers or hosts each
    process counts separately, which would need a shared store instead.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > settings.AUTH_RATE_WINDOW_SECONDS:
            hits.popleft()
        return hits

    def ensure_allowed(self, key: str) -> None:
        if len(self._prune(key)) >= settings.AUTH_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Zu viele Versuche, bitte später erneut probieren",
            )

    def record(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self) -> None:
        self._hits.clear()


auth_limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    # Behind a reverse proxy this is only the real client IP if uvicorn runs
    # with --proxy-headers (see deploy/filmabend.service).
    client = request.client.host if request.client else "unknown"
    return f"{request.url.path}:{client}"
