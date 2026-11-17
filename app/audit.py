from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.utils import client_ip


def log_action(
    db: Session,
    tenant_id: int | None,
    actor: str,
    action: str,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(AuditLog(
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        detail=detail,
        ip=client_ip(request) if request else None,
    ))