from fastapi import APIRouter, Request

from app.config import settings
from app.templating import templates

router = APIRouter()


@router.get("/")
def landing(request: Request):
    return templates.TemplateResponse(
        request, "landing.html", {"app_name": settings.app_name}
    )