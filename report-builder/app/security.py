"""Security helpers: API-key check, rate limiting, safe filenames, security headers."""
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(provided: str | None = Depends(_api_key_header)) -> None:
    """Reject any request without the correct X-API-Key header."""
    # compare_digest avoids timing attacks
    if not provided or not secrets.compare_digest(provided.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")


class RateLimiter:
    """Tiny in-memory limiter: max N calls per window per client IP.
    (For several servers, move this to Redis.)"""

    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window = window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    async def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self.hits[ip]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
        q.append(now)


def safe_display_name(filename: str | None) -> str:
    """Filename is only used for display, never to build a path on disk."""
    name = Path(filename or "upload").name
    name = re.sub(r"[^\w .\-()]", "_", name).strip() or "upload"
    return name[:100]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
CSP = (
    "default-src 'self'; img-src 'self' blob: data:; "
    "style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"
)
