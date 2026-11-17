import hashlib

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant

bearer = HTTPBearer(auto_error=False)


def get_tenant(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Tenant:
    unauthorized = HTTPException(
        status_code=401,
        detail="API key tidak valid",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    digest = hashlib.sha256(creds.credentials.encode()).hexdigest()
    tenant = db.scalar(select(Tenant).where(Tenant.api_key_hash == digest))
    if tenant is None or tenant.status != "active":
        raise unauthorized
    return tenant