import logging
from urllib.parse import urlencode

import httpx

from app.config import settings

# httpx mencatat URL lengkap (termasuk access_token) pada level INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

GRAPH = f"https://graph.facebook.com/{settings.meta_graph_version}"
DIALOG = f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth"


class MetaError(Exception):
    pass


def redirect_uri() -> str:
    return f"{settings.base_url.rstrip('/')}/oauth/callback"


def build_login_url(state: str) -> str:
    query = {
        "client_id": settings.meta_app_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "config_id": settings.meta_config_id,
        "state": state,
    }
    return f"{DIALOG}?{urlencode(query)}"


def _get(path: str, params: dict) -> dict:
    r = httpx.get(f"{GRAPH}{path}", params=params, timeout=20)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        raise MetaError(f"HTTP {r.status_code}: {msg}"[:300])
    return r.json()


def exchange_code(code: str) -> str:
    data = _get("/oauth/access_token", {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "redirect_uri": redirect_uri(),
        "code": code,
    })
    token = data.get("access_token")
    if not token:
        raise MetaError("Respons tidak memuat access_token")
    return token


def list_instagram_accounts(token: str) -> list[dict]:
    """Akun Instagram yang dibagikan klien ke app, dengan id dan username."""
    data = _get("/me/assigned_instagram_accounts", {"access_token": token})
    accounts = []
    for item in data.get("data", []):
        info = _get(f"/{item['id']}", {"fields": "id,username", "access_token": token})
        accounts.append({"id": info["id"], "username": info.get("username", "")})
    return accounts