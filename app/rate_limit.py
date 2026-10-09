import time
from collections import deque

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowLimiter:
    """In-memory attempt counter per key.

    Sufficient for a single uvicorn worker. With several workers or hosts each
    process counts separately, which would need a shared store instead.
    """

    # Upper bound for tracked keys. Keys without hits in the window are
    # dropped first, so this only matters under a flood of distinct IPs.
    MAX_KEYS = 10_000

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and now - hits[0] > settings.AUTH_RATE_WINDOW_SECONDS:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def _sweep(self, now: float) -> None:
        for key in list(self._hits):
            self._prune(key, now)
        # Still full: forget the keys whose last attempt is oldest.
        overflow = len(self._hits) - self.MAX_KEYS + 1
        if overflow > 0:
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[:overflow]:
                del self._hits[key]

    def ensure_allowed(self, key: str) -> None:
        if len(self._prune(key, time.monotonic())) >= settings.AUTH_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Zu viele Versuche, bitte später erneut probieren",
            )

    def record(self, key: str) -> None:
        now = time.monotonic()
        hits = self._prune(key, now)
        if key not in self._hits:
            if len(self._hits) >= self.MAX_KEYS:
                self._sweep(now)
            self._hits[key] = hits
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


auth_limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    # Behind a reverse proxy this is only the real client IP if uvicorn runs
    # with --proxy-headers (see deploy/movienight.service).
    client = request.client.host if request.client else "unknown"
    return f"{request.url.path}:{client}"
