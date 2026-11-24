"""Sinkronisasi daftar video satu akun Instagram ke tabel media_items.

Hanya mendeteksi dan mencatat. URL video (media_url) sengaja TIDAK disimpan
karena bertanda tangan dan berumur pendek; tahap proses meminta URL segar.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt
from app.models import IGAccount, MediaItem
from app.services import instagram as ig

SKIP_NO_URL = "no_download_url"


def parse_ts(value: str | None) -> datetime | None:
    """Format Meta: 2026-11-20T10:00:00+0000."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def sync_account(db: Session, acc: IGAccount) -> dict:
    """Catat video terbaru akun. Hanya `acc.max_active_videos` video terbaru
    yang dipertimbangkan. Tidak melakukan commit."""
    token = decrypt(acc.token_encrypted)
    items = ig.list_media(token, acc.ig_user_id, limit=25)
    videos = [i for i in items if i.get("media_type") == "VIDEO" and i.get("id")]
    videos = videos[: acc.max_active_videos]

    ids = [v["id"] for v in videos]
    existing: dict[str, MediaItem] = {}
    if ids:
        rows = db.scalars(
            select(MediaItem).where(
                MediaItem.ig_account_id == acc.id,
                MediaItem.ig_media_id.in_(ids),
            )
        )
        existing = {m.ig_media_id: m for m in rows}

    stats = {"seen": len(videos), "new": 0, "skipped": 0, "recovered": 0}
    for v in videos:
        has_url = bool(v.get("media_url"))
        m = existing.get(v["id"])
        if m is None:
            db.add(MediaItem(
                tenant_id=acc.tenant_id,
                ig_account_id=acc.id,
                ig_media_id=v["id"],
                media_type="VIDEO",
                permalink=v.get("permalink"),
                posted_at=parse_ts(v.get("timestamp")),
                status="pending" if has_url else "skipped",
                skip_reason=None if has_url else SKIP_NO_URL,
            ))
            stats["new"] += 1
            if not has_url:
                stats["skipped"] += 1
        elif m.status == "skipped" and m.skip_reason == SKIP_NO_URL and has_url:
            # Klien mengubah pengaturan unduhan atau audio: coba lagi.
            m.status = "pending"
            m.skip_reason = None
            m.attempts = 0
            stats["recovered"] += 1
        elif m.status == "removed" and has_url:
            # Dihapus saat akun diputus lalu disambungkan lagi: proses ulang.
            m.status = "pending"
            m.skip_reason = None
            m.attempts = 0
            stats["recovered"] += 1

    acc.last_synced_at = datetime.now(timezone.utc)
    return stats
