from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.config import settings
from app.crypto import encrypt
from app.db import get_db
from app.models import ConnectSession, IGAccount, Job
from app.services import instagram as ig
from app.templating import templates
from app.utils import as_utc
from fastapi import HTTPException

router = APIRouter()


def _load_pending(db: Session, state: str | None) -> ConnectSession | None:
    if not state:
        return None
    s = db.scalar(select(ConnectSession).where(ConnectSession.state == state))
    if (
        s is None
        or s.status != "pending"
        or as_utc(s.expires_at) < datetime.now(timezone.utc)
    ):
        return None
    return s


def _with_query(url: str, **params) -> str:
    p = urlsplit(url)
    query = dict(parse_qsl(p.query))
    query.update(params)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def _invalid_page(request: Request):
    return templates.TemplateResponse(
        request, "connect.html",
        {"app_name": settings.app_name, "valid": False, "state": ""},
        status_code=410,
    )


def _finish(s: ConnectSession, status: str, reason: str | None = None):
    params = {"veedcast_session": s.state, "veedcast_status": status}
    if reason:
        params["veedcast_reason"] = reason
    return RedirectResponse(_with_query(s.return_url, **params), status_code=302)


@router.get("/connect/{state}/start")
def connect_start(request: Request, state: str, db: Session = Depends(get_db)):
    s = _load_pending(db, state)
    if s is None:
        return _invalid_page(request)

    if not (settings.meta_app_id and settings.meta_app_secret and settings.meta_config_id):
        raise HTTPException(503, "Konfigurasi Meta belum lengkap")
    try:
        encrypt("selftest")
    except Exception:
        raise HTTPException(503, "TOKEN_ENCRYPTION_KEY tidak valid")

    resp = RedirectResponse(ig.build_login_url(state), status_code=302)
    resp.set_cookie(
        "vc_state", state, max_age=900, httponly=True, samesite="lax",
        secure=(settings.environment == "production"), path="/oauth",
    )
    return resp


@router.get("/oauth/callback")
def oauth_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    s = _load_pending(db, state)
    if s is None:
        return _invalid_page(request)

    if request.cookies.get("vc_state") != state:
        return _invalid_page(request)

    if error or not code:
        s.status = "failed"
        log_action(db, s.tenant_id, "user:ig", "connect.cancelled",
                   {"external_ref": s.external_ref}, request)
        db.commit()
        return _finish(s, "cancelled")

    try:
        token = ig.exchange_code(code)
        accounts = ig.list_instagram_accounts(token)
    except ig.MetaError as exc:
        s.status = "failed"
        log_action(db, s.tenant_id, "user:ig", "connect.error",
                   {"error": str(exc)}, request)
        db.commit()
        return _finish(s, "failed", "meta_error")

    if len(accounts) != 1:
        s.status = "failed"
        log_action(db, s.tenant_id, "user:ig", "connect.error",
                   {"error": f"akun dibagikan: {len(accounts)}"}, request)
        db.commit()
        return _finish(s, "failed", "choose_exactly_one_account")

    info = accounts[0]
    acc = db.scalar(
        select(IGAccount).where(
            IGAccount.tenant_id == s.tenant_id,
            IGAccount.ig_user_id == info["id"],
        )
    )
    if acc is None:
        acc = IGAccount(tenant_id=s.tenant_id, ig_user_id=info["id"], username=info["username"])
        db.add(acc)
    acc.username = info["username"]
    acc.external_ref = s.external_ref
    acc.token_encrypted = encrypt(token)
    acc.token_expires_at = None  # token system-user tidak kedaluwarsa
    acc.status = "connected"
    db.flush()

    s.status = "completed"
    s.ig_account_id = acc.id
    db.add(Job(tenant_id=s.tenant_id, ig_account_id=acc.id, kind="sync"))
    log_action(db, s.tenant_id, "user:ig", "account.connected",
               {"account_id": acc.id, "username": acc.username}, request)
    db.commit()
    return _finish(s, "success")