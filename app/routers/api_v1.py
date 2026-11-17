import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_tenant
from app.config import settings
from app.db import get_db
from app.models import ConnectSession, IGAccount, Tenant
from app.schemas import (
    AccountOut, AccountUpdate, ConnectSessionIn,
    ConnectSessionOut, ConnectSessionStatus,
)
from app.utils import as_utc, origin_of

router = APIRouter(prefix="/v1", tags=["v1"])

SESSION_TTL = timedelta(minutes=15)


def _actor(tenant: Tenant) -> str:
    return f"tenant:{tenant.id}"


def _get_account(db: Session, tenant: Tenant, account_id: int) -> IGAccount:
    # Selalu filter tenant_id: satu CMS tidak boleh melihat akun CMS lain.
    acc = db.scalar(
        select(IGAccount).where(
            IGAccount.id == account_id, IGAccount.tenant_id == tenant.id
        )
    )
    if acc is None:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return acc


@router.post("/connect-sessions", response_model=ConnectSessionOut, status_code=201)
def create_connect_session(
    body: ConnectSessionIn,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return_url = str(body.return_url)
    allowed = [o.lower() for o in (tenant.allowed_origins or [])]
    if origin_of(return_url) not in allowed:
        raise HTTPException(
            status_code=400,
            detail="return_url tidak termasuk origin yang diizinkan untuk tenant ini",
        )

    session = ConnectSession(
        tenant_id=tenant.id,
        state=secrets.token_urlsafe(32),
        external_ref=body.external_ref,
        return_url=return_url,
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
    )
    db.add(session)
    log_action(db, tenant.id, _actor(tenant), "connect_session.created",
               {"external_ref": body.external_ref}, request)
    db.commit()

    return ConnectSessionOut(
        session_id=session.state,
        connect_url=f"{settings.base_url.rstrip('/')}/connect/{session.state}",
        expires_at=session.expires_at,
    )


@router.get("/connect-sessions/{session_id}", response_model=ConnectSessionStatus)
def get_connect_session(
    session_id: str,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    s = db.scalar(
        select(ConnectSession).where(
            ConnectSession.state == session_id,
            ConnectSession.tenant_id == tenant.id,
        )
    )
    if s is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    status = s.status
    if status == "pending" and as_utc(s.expires_at) < datetime.now(timezone.utc):
        status = "expired"
    account = db.get(IGAccount, s.ig_account_id) if s.ig_account_id else None
    return {"session_id": s.state, "status": status, "account": account}


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    external_ref: str | None = None,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    q = select(IGAccount).where(IGAccount.tenant_id == tenant.id).order_by(IGAccount.id)
    if external_ref:
        q = q.where(IGAccount.external_ref == external_ref)
    return db.scalars(q).all()


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(
    account_id: int,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return _get_account(db, tenant, account_id)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    body: AccountUpdate,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    acc = _get_account(db, tenant, account_id)
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(acc, key, value)
    if changes:
        log_action(db, tenant.id, _actor(tenant), "account.updated",
                   {"account_id": acc.id, **changes}, request)
    db.commit()
    return acc


@router.delete("/accounts/{account_id}", status_code=204)
def disconnect_account(
    account_id: int,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    acc = _get_account(db, tenant, account_id)
    acc.status = "revoked"
    acc.token_encrypted = None
    acc.token_expires_at = None
    log_action(db, tenant.id, _actor(tenant), "account.disconnected",
               {"account_id": acc.id, "username": acc.username}, request)
    db.commit()
    return Response(status_code=204)