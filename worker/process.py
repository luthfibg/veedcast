"""Tahap proses media: unduh -> FFmpeg -> unggah ke R2.

Satu video diproses per transaksi. Kegagalan satu video tidak menghentikan
video lain. Kunci objek R2 deterministik, jadi pemrosesan ganda aman.
"""
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.crypto import decrypt
from app.db import SessionLocal
from app.models import IGAccount, MediaItem, UsageDaily
from app.services import instagram as ig
from app.services import storage, video

MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_ATTEMPTS = 3
# Jangan mulai video baru bila sisa waktu kurang dari ini (detik).
MIN_SECONDS_PER_ITEM = 90
META_TOKEN_INVALID = 190
META_OBJECT_MISSING = 100


class Skip(Exception):
    """Video sengaja dilewati (bukan kegagalan)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _download(url: str, dest: Path) -> int:
    """Unduh ke file dengan batas ukuran. URL tidak pernah dicatat."""
    total = 0
    try:
        with httpx.stream(
            "GET", url, timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=True
        ) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"unduh gagal: HTTP {r.status_code}")
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(256 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise Skip("too_large")
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"unduh gagal: {type(exc).__name__}") from None
    return total


def _add_usage(db: Session, tenant_id: int, down: int, up: int) -> None:
    today = datetime.now(timezone.utc).date()
    row = db.scalar(
        select(UsageDaily).where(UsageDaily.tenant_id == tenant_id, UsageDaily.day == today)
    )
    if row is None:
        row = UsageDaily(tenant_id=tenant_id, day=today, jobs_count=0,
                         bytes_downloaded=0, bytes_uploaded=0)
        db.add(row)
    row.bytes_downloaded += down
    row.bytes_uploaded += up


def _process_item(db: Session, item: MediaItem, acc: IGAccount) -> None:
    token = decrypt(acc.token_encrypted)
    fresh = ig.get_media(token, item.ig_media_id)
    url = fresh.get("media_url")
    if not url:
        raise Skip("no_download_url")

    rotation = acc.rotation
    with tempfile.TemporaryDirectory(prefix="vc_") as tmp:
        src, dst = Path(tmp) / "src", Path(tmp) / "out.mp4"
        bytes_in = _download(url, src)
        info = video.probe(src)
        if info.duration_s > video.MAX_DURATION_S:
            raise Skip("too_long")
        video.transcode(src, dst, rotation, info.fps)
        out = video.probe(dst)
        key = storage.media_key(item.tenant_id, acc.id, item.ig_media_id)
        storage.upload_video(dst, key)
        bytes_out = dst.stat().st_size

    item.status = "processed"
    item.storage_key = key
    item.bytes_in = bytes_in
    item.bytes_out = bytes_out
    item.width, item.height = out.width, out.height
    item.duration_s = out.duration_s
    item.rotation_applied = rotation
    item.skip_reason = None
    item.error = None
    item.processed_at = datetime.now(timezone.utc)
    _add_usage(db, item.tenant_id, bytes_in, bytes_out)


def _record_error(db: Session, item: MediaItem, exc: Exception) -> str:
    item.error = f"{type(exc).__name__}: {exc}"[:500]
    if item.attempts >= MAX_ATTEMPTS:
        item.status = "failed"
        log_action(db, item.tenant_id, "worker", "media.failed",
                   {"media_id": item.id, "error": item.error})
    db.commit()
    return "failed" if item.status == "failed" else "retry"


def _run_one(db: Session, item: MediaItem) -> str:
    acc = db.get(IGAccount, item.ig_account_id)
    item.attempts += 1
    db.commit()  # simpan percobaan lebih dulu agar tidak hilang saat rollback
    try:
        _process_item(db, item, acc)
        db.commit()
        return "processed"
    except Skip as s:
        db.rollback()
        item.status = "skipped"
        item.skip_reason = s.reason
        item.error = None
        db.commit()
        return "skipped"
    except ig.MetaError as exc:
        db.rollback()
        if exc.code == META_TOKEN_INVALID:
            acc.status = "expired"
            item.attempts = max(0, item.attempts - 1)
            log_action(db, item.tenant_id, "worker", "account.token_invalid",
                       {"account_id": acc.id, "username": acc.username})
            db.commit()
            return "retry"
        if exc.code == META_OBJECT_MISSING:
            item.status = "removed"
            item.error = "video sudah tidak ada di Instagram"
            db.commit()
            return "removed"
        return _record_error(db, item, exc)
    except Exception as exc:  # noqa: BLE001 - kegagalan apa pun masuk logika retry
        db.rollback()
        return _record_error(db, item, exc)


def process_pending(deadline: float) -> dict:
    """Proses video berstatus pending sampai habis atau waktu hampir habis."""
    stats = {"processed": 0, "skipped": 0, "failed": 0, "retry": 0, "removed": 0}
    tried: set[int] = set()
    while time.monotonic() + MIN_SECONDS_PER_ITEM < deadline:
        with SessionLocal() as db:
            conditions = [
                MediaItem.status == "pending",
                MediaItem.attempts < MAX_ATTEMPTS,
                IGAccount.status == "connected",
                IGAccount.token_encrypted.is_not(None),
            ]
            if tried:
                conditions.append(MediaItem.id.not_in(tried))
            item = db.scalar(
                select(MediaItem)
                .join(IGAccount, IGAccount.id == MediaItem.ig_account_id)
                .where(*conditions)
                .order_by(MediaItem.posted_at.desc().nullslast(), MediaItem.id)
                .limit(1)
            )
            if item is None:
                break
            item_id = item.id
            tried.add(item_id)
            outcome = _run_one(db, item)
        stats[outcome] += 1
        print(f"  media #{item_id}: {outcome}")
    return stats


def requeue_rotation_changes(db: Session) -> int:
    """Video yang sudah diproses dengan rotasi lama diproses ulang bila
    pengaturan rotasi akun berubah."""
    rows = db.scalars(
        select(MediaItem)
        .join(IGAccount, IGAccount.id == MediaItem.ig_account_id)
        .where(
            MediaItem.status == "processed",
            IGAccount.status == "connected",
            or_(
                MediaItem.rotation_applied.is_(None),
                MediaItem.rotation_applied != IGAccount.rotation,
            ),
        )
    ).all()
    for m in rows:
        m.status = "pending"
        m.attempts = 0
    db.commit()
    return len(rows)


def prune_all(db: Session) -> int:
    """Pertahankan hanya `max_active_videos` video terproses terbaru per akun;
    sisanya dihapus dari R2."""
    removed = 0
    for acc in db.scalars(select(IGAccount).where(IGAccount.status == "connected")).all():
        done = db.scalars(
            select(MediaItem)
            .where(MediaItem.ig_account_id == acc.id, MediaItem.status == "processed")
            .order_by(MediaItem.posted_at.desc().nullslast(), MediaItem.id.desc())
        ).all()
        for m in done[acc.max_active_videos:]:
            try:
                if m.storage_key:
                    storage.delete_object(m.storage_key)
            except Exception:  # noqa: BLE001 - coba lagi pada putaran berikutnya
                continue
            m.status = "removed"
            m.storage_key = None
            removed += 1
        db.commit()
    return removed
