from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    """Satu aplikasi CMS yang memakai Veedcast."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    api_key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ig_accounts: Mapped[list["IGAccount"]] = relationship(back_populates="tenant")


class IGAccount(Base):
    """Akun Instagram klien yang sudah memberi izin."""
    __tablename__ = "ig_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "ig_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_ref: Mapped[str | None] = mapped_column(String(120))  # ID klien di sisi CMS
    ig_user_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(64))
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|connected|expired|revoked
    rotation: Mapped[int] = mapped_column(Integer, default=0)           # 0|90|180|270
    max_active_videos: Mapped[int] = mapped_column(Integer, default=10)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=True)   # False = perlu approve
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="ig_accounts")


class MediaItem(Base):
    """Satu video dari Instagram dan status pemrosesannya."""
    __tablename__ = "media_items"
    __table_args__ = (UniqueConstraint("ig_account_id", "ig_media_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    ig_account_id: Mapped[int] = mapped_column(ForeignKey("ig_accounts.id"), index=True)
    ig_media_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processed|failed|removed
    storage_key: Mapped[str | None] = mapped_column(String(255))        # path di R2
    bytes_in: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_out: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Antrian pekerjaan untuk worker."""
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_at", "status", "run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    ig_account_id: Mapped[int | None] = mapped_column(ForeignKey("ig_accounts.id"))
    kind: Mapped[str] = mapped_column(String(30))                       # sync|refresh_token|process_media
    status: Mapped[str] = mapped_column(String(20), default="queued")   # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Siapa melakukan apa, kapan, dari mana."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UsageDaily(Base):
    """Rekap pemakaian harian per tenant. Dasar penagihan nanti."""
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("tenant_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    jobs_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_uploaded: Mapped[int] = mapped_column(BigInteger, default=0)