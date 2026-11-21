from fastapi import APIRouter, Request

from app.config import settings
from app.templating import templates

from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ConnectSession, Tenant
from app.utils import as_utc

router = APIRouter()


@router.get("/")
def landing(request: Request):
    return templates.TemplateResponse(
        request, "landing.html", {"app_name": settings.app_name}
    )

@router.get("/connect/{state}")
def connect_page(request: Request, state: str, db: Session = Depends(get_db)):
    s = db.scalar(select(ConnectSession).where(ConnectSession.state == state))
    valid = (
        s is not None
        and s.status == "pending"
        and as_utc(s.expires_at) > datetime.now(timezone.utc)
    )
    tenant = db.get(Tenant, s.tenant_id) if valid else None
    return templates.TemplateResponse(
        request,
        "connect.html",
        {
            "app_name": settings.app_name,
            "valid": valid,
            "tenant_name": tenant.name if tenant else None,
            "state": state,
        },
        status_code=200 if valid else 410,
    )

@router.get("/privacy")
def privacy(request: Request):
    return templates.TemplateResponse(
        request, "legal/privacy.html", {"app_name": settings.app_name}
    )


@router.get("/terms")
def terms(request: Request):
    return templates.TemplateResponse(
        request, "legal/terms.html", {"app_name": settings.app_name}
    )


@router.get("/data-deletion")
def data_deletion(request: Request):
    return templates.TemplateResponse(
        request, "legal/data_deletion.html", {"app_name": settings.app_name}
    )