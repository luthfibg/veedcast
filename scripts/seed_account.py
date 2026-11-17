import sys

from app.db import SessionLocal
from app.models import IGAccount

tenant_id, username, ext_ref = int(sys.argv[1]), sys.argv[2], sys.argv[3]
with SessionLocal() as db:
    acc = IGAccount(
        tenant_id=tenant_id, ig_user_id=f"fake-{username}",
        username=username, external_ref=ext_ref, status="connected",
    )
    db.add(acc)
    db.commit()
    print(f"Akun uji #{acc.id} dibuat.")