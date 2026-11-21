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
        "override_default_response_type": "true",
        "config_id": settings.meta_config_id,
        "state": state,
    }
    return f"{DIALOG}?{urlencode(query)}"


def _get(path: str, params: dict) -> dict:
    try:
        r = httpx.get(f"{GRAPH}{path}", params=params, timeout=20)
    except httpx.HTTPError as exc:
        raise MetaError(f"network: {type(exc).__name__}") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        msg = err.get("message", "") if isinstance(err, dict) else ""
        raise MetaError(f"HTTP {r.status_code}: {msg}"[:300])
    return body if isinstance(body, dict) else {}


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
    data = _get("/me/assigned_instagram_accounts", {"access_token": token})
    accounts = []
    for item in data.get("data", []):
        if "id" not in item:
            continue
        info = _get(f"/{item['id']}", {"fields": "id,username", "access_token": token})
        if "id" in info:
            accounts.append({"id": info["id"], "username": info.get("username", "")})
    return accounts