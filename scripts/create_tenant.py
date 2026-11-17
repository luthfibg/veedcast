import hashlib
import secrets
import sys

from app.db import SessionLocal
from app.models import AuditLog, Tenant


def main(name: str) -> None:
    raw_key = "vc_" + secrets.token_urlsafe(32)
    with SessionLocal() as db:
        tenant = Tenant(
            name=name,
            api_key_prefix=raw_key[:11],
            api_key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        )
        db.add(tenant)
        db.flush()
        db.add(AuditLog(
            tenant_id=tenant.id, actor="cli",
            action="tenant.created", detail={"name": name},
        ))
        db.commit()
        tenant_id = tenant.id

    print(f"Tenant #{tenant_id} '{name}' dibuat.")
    print(f"API key (simpan sekarang, tidak akan ditampilkan lagi):\n{raw_key}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Pemakaian: python -m scripts.create_tenant "Nama CMS"')
    main(sys.argv[1])