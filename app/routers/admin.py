from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.templating import templates
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import IGAccount, Tenant, UsageDaily

security = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(security)):
    user_ok = compare_digest(creds.username.encode(), b"admin")
    pass_ok = compare_digest(creds.password.encode(), settings.admin_password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    jobs, dl, ul = db.execute(
        select(
            func.coalesce(func.sum(UsageDaily.jobs_count), 0),
            func.coalesce(func.sum(UsageDaily.bytes_downloaded), 0),
            func.coalesce(func.sum(UsageDaily.bytes_uploaded), 0),
        ).where(UsageDaily.day == today)
    ).one()

    stats = {
        "ig_accounts": db.scalar(
            select(func.count(IGAccount.id)).where(IGAccount.status == "connected")
        ),
        "tenants": db.scalar(select(func.count(Tenant.id))),
        "jobs_today": jobs,
        "downloaded_mb": round(dl / 1_048_576, 1),
        "uploaded_mb": round(ul / 1_048_576, 1),
    }
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"app_name": settings.app_name, "stats": stats},
    )