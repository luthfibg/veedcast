"""Runner worker Veedcast.

Pemakaian:
    python -m worker.run [--max-seconds 360] [--skip-media]

Sekali jalan:
  1. pulihkan job macet, jadwalkan sync akun yang sudah waktunya, bersihkan job lama
  2. kerjakan antrian sync
  3. proses video baru (unduh -> FFmpeg -> R2), lalu rapikan video lama
Aman dijalankan dari cron GitHub Actions atau VPS.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.audit import log_action
from app.db import SessionLocal, engine
from app.models import IGAccount, Job, UsageDaily
from app.services import instagram as ig
from app.services import storage
from app.utils import as_utc
from worker.process import prune_all, process_pending, requeue_rotation_changes
from worker.sync import sync_account

SYNC_INTERVAL = timedelta(hours=3)
STALE_LOCK = timedelta(minutes=15)
JOB_RETENTION = timedelta(days=14)
MAX_ATTEMPTS = 3
# Kode error Meta untuk token tidak valid/dicabut.
TOKEN_INVALID_CODES = {190}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def release_stale(db) -> int:
    """Job 'running' yang terkunci terlalu lama (worker mati) dikembalikan ke antrian."""
    cutoff = utcnow() - STALE_LOCK
    jobs = db.scalars(select(Job).where(Job.status == "running", Job.locked_at < cutoff)).all()
    for j in jobs:
        j.status = "queued"
        j.locked_at = None
    db.commit()
    return len(jobs)


def cleanup_jobs(db) -> int:
    """Hapus job selesai/gagal yang lebih tua dari JOB_RETENTION."""
    result = db.execute(
        delete(Job).where(
            Job.status.in_(("done", "failed")),
            Job.created_at < utcnow() - JOB_RETENTION,
        )
    )
    db.commit()
    return result.rowcount or 0


def enqueue_due_syncs(db) -> int:
    """Buat job sync untuk akun connected yang sudah waktunya dan belum punya job aktif."""
    now = utcnow()
    created = 0
    for acc in db.scalars(select(IGAccount).where(IGAccount.status == "connected")).all():
        if acc.last_synced_at is not None and now - as_utc(acc.last_synced_at) < SYNC_INTERVAL:
            continue
        active = db.scalar(
            select(Job.id).where(
                Job.ig_account_id == acc.id,
                Job.kind == "sync",
                Job.status.in_(("queued", "running")),
            ).limit(1)
        )
        if active:
            continue
        db.add(Job(tenant_id=acc.tenant_id, ig_account_id=acc.id, kind="sync"))
        created += 1
    db.commit()
    return created


def claim_job_id() -> int | None:
    """Ambil satu job queued secara atomik (SKIP LOCKED di Postgres)."""
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .where(Job.status == "queued", Job.run_at <= utcnow())
            .order_by(Job.run_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "running"
        job.locked_at = utcnow()
        job.attempts += 1
        db.commit()
        return job.id


def bump_usage(db, tenant_id: int) -> None:
    today = utcnow().date()
    row = db.scalar(
        select(UsageDaily).where(UsageDaily.tenant_id == tenant_id, UsageDaily.day == today)
    )
    if row is None:
        row = UsageDaily(tenant_id=tenant_id, day=today, jobs_count=0,
                         bytes_downloaded=0, bytes_uploaded=0)
        db.add(row)
    row.jobs_count += 1


def fail_job(job_id: int, exc: Exception) -> None:
    """Catat kegagalan: coba lagi dengan jeda, atau tandai gagal permanen."""
    message = f"{type(exc).__name__}: {exc}"[:500]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        acc = db.get(IGAccount, job.ig_account_id) if job.ig_account_id else None
        job.last_error = message
        job.locked_at = None

        token_dead = isinstance(exc, ig.MetaError) and exc.code in TOKEN_INVALID_CODES
        if token_dead and acc is not None:
            acc.status = "expired"
            job.status = "failed"
            log_action(db, job.tenant_id, "worker", "account.token_invalid",
                       {"account_id": acc.id, "username": acc.username})
        elif job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
            log_action(db, job.tenant_id, "worker", "job.failed",
                       {"job_id": job.id, "kind": job.kind, "error": message})
        else:
            job.status = "queued"
            job.run_at = utcnow() + timedelta(minutes=5 * job.attempts ** 2)
        db.commit()


def process_job(job_id: int) -> str:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        acc = db.get(IGAccount, job.ig_account_id) if job.ig_account_id else None

        if job.kind != "sync" or acc is None or acc.status != "connected" or not acc.token_encrypted:
            reason = (
                "akun tidak ada" if acc is None
                else f"status akun={acc.status}, token={'ada' if acc.token_encrypted else 'kosong'}"
            )
            job.status = "done"
            job.locked_at = None
            job.last_error = f"dilewati: {reason}"
            db.commit()
            return f"skipped ({reason})"

        try:
            stats = sync_account(db, acc)
            job.status = "done"
            job.locked_at = None
            job.last_error = None
            bump_usage(db, acc.tenant_id)
            log_action(db, acc.tenant_id, "worker", "account.synced",
                       {"account_id": acc.id, **stats})
            db.commit()
            return f"sync @{acc.username}: {stats}"
        except Exception as exc:  # noqa: BLE001 - semua kegagalan masuk logika retry
            db.rollback()
            fail_job(job_id, exc)
            return f"gagal ({type(exc).__name__})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=int, default=360)
    parser.add_argument("--skip-media", action="store_true",
                        help="hanya sinkronisasi, lewati unduh/proses video")
    args = parser.parse_args()
    deadline = time.monotonic() + args.max_seconds

    print(f"database={engine.url.get_backend_name()} host={engine.url.host or 'file lokal'}")
    with SessionLocal() as db:
        released = release_stale(db)
        enqueued = enqueue_due_syncs(db)
        cleaned = cleanup_jobs(db)
    print(f"dipulihkan={released} dijadwalkan={enqueued} job_lama_dihapus={cleaned}")

    done = 0
    while time.monotonic() < deadline:
        job_id = claim_job_id()
        if job_id is None:
            break
        print(f"job #{job_id}: {process_job(job_id)}")
        done += 1
    print(f"sync selesai, {done} job diproses")

    if args.skip_media:
        return
    if not storage.is_configured():
        print("R2 belum dikonfigurasi: tahap unduh/proses video dilewati")
        return

    with SessionLocal() as db:
        requeued = requeue_rotation_changes(db)
    print(f"media: diproses ulang karena rotasi berubah={requeued}")
    stats = process_pending(deadline)
    with SessionLocal() as db:
        pruned = prune_all(db)
    print(f"media: {stats} dihapus_dari_r2={pruned}")


if __name__ == "__main__":
    main()
