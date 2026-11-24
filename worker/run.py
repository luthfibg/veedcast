"""Runner worker Veedcast.

Pemakaian:
    python -m worker.run [--max-seconds 240]

Sekali jalan: (1) pulihkan job macet, (2) buat job sync untuk akun yang
sudah waktunya, (3) kerjakan antrian sampai habis atau waktu habis.
Aman dijalankan dari cron GitHub Actions atau VPS.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.audit import log_action
from app.db import SessionLocal, engine
from app.models import IGAccount, Job, UsageDaily
from app.services import instagram as ig
from app.utils import as_utc
from worker.sync import sync_account

SYNC_INTERVAL = timedelta(hours=3)
STALE_LOCK = timedelta(minutes=15)
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
    parser.add_argument("--max-seconds", type=int, default=240)
    args = parser.parse_args()
    print(f"database={engine.url.get_backend_name()} host={engine.url.host or 'file lokal'}")
    deadline = time.monotonic() + args.max_seconds

    with SessionLocal() as db:
        released = release_stale(db)
        enqueued = enqueue_due_syncs(db)
    print(f"dipulihkan={released} dijadwalkan={enqueued}")

    done = 0
    while time.monotonic() < deadline:
        job_id = claim_job_id()
        if job_id is None:
            break
        print(f"job #{job_id}: {process_job(job_id)}")
        done += 1
    print(f"selesai, {done} job diproses")


if __name__ == "__main__":
    main()
