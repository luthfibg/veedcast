from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import Request


def as_utc(dt: datetime) -> datetime:
    """SQLite mengembalikan datetime tanpa zona waktu; samakan ke UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None