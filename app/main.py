from fastapi import FastAPI

from app.config import settings
from app.routers import admin, api_v1, public

app = FastAPI(title=settings.app_name)

app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api_v1.router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}