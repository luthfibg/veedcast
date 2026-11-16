from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.templating import templates

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
def dashboard(request: Request):
    # Data contoh. Nanti diganti query ke database.
    stats = {
        "ig_accounts": 0,
        "tenants": 0,
        "jobs_today": 0,
        "downloaded_mb": 0,
        "uploaded_mb": 0,
    }
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"app_name": settings.app_name, "stats": stats},
    )