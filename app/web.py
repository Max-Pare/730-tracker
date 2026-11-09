# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for the server-rendered web UI."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import __version__
from .db import get_db
from .ocr.parser import format_cents
from .security import auth, crypto
from .services.domain import CATEGORIES, PAYMENT_METHODS, RELATIONS, STATUSES

SESSION_COOKIE = "t730_session"
FLASH_COOKIE = "t730_flash"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _eur(cents) -> str:
    return "" if cents is None else format_cents(int(cents))


def _date_it(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.astimezone().strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def _amount_input(cents) -> str:
    return "" if cents is None else f"{int(cents) // 100},{int(cents) % 100:02d}"


templates.env.filters["eur"] = _eur
templates.env.filters["date_it"] = _date_it
templates.env.filters["amount_input"] = _amount_input
templates.env.filters["docs"] = lambda n: f"{n} documento" if n == 1 else f"{n} documenti"
templates.env.globals.update(
    CATEGORIES=CATEGORIES,
    PAYMENT_METHODS=PAYMENT_METHODS,
    STATUSES=STATUSES,
    RELATIONS=RELATIONS,
    APP_VERSION=__version__,
)


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def settings_of(request: Request):
    return request.app.state.settings


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.app.state.settings.force_secure_cookies


def current_principal(request: Request, db: Session) -> auth.Principal | None:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    p = auth.resolve_token(db, settings_of(request), token, "web")
    request.state.principal = p
    return p


def require_user(request: Request, db: Session = Depends(get_db)) -> auth.Principal:
    p = current_principal(request, db)
    if p is None:
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(nxt)
    return p


def require_admin(request: Request, db: Session = Depends(get_db)) -> auth.Principal:
    p = require_user(request, db)
    if not p.user.is_admin:
        raise HTTPException(status_code=403, detail="Riservato agli amministratori.")
    return p


def check_csrf(p: auth.Principal, token: str | None) -> None:
    if not token or not crypto.constant_time_eq(token.encode(), p.csrf_token.encode()):
        raise HTTPException(status_code=403, detail="Token di sicurezza non valido: ricarica la pagina e riprova.")


def safe_next(url: str | None) -> str:
    """Only allow local redirects."""
    if not url:
        return "/dashboard"
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc or not url.startswith("/") or url.startswith("//"):
        return "/dashboard"
    return url


def set_session_cookie(request: Request, response, token: str) -> None:
    s = settings_of(request)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=s.web_session_max_days * 86400,
        httponly=True,
        secure=is_https(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def flash(response, message: str, kind: str = "ok") -> None:
    payload = json.dumps({"m": message[:300], "k": kind if kind in ("ok", "error", "info") else "info"})
    response.set_cookie(FLASH_COOKIE, quote(payload), max_age=60, httponly=True, samesite="lax", path="/")


def _pop_flash(request: Request) -> dict | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    from urllib.parse import unquote

    try:
        data = json.loads(unquote(raw))
        return {"message": str(data["m"])[:300], "kind": data.get("k", "info")}
    except (ValueError, KeyError, TypeError):
        return None


def redirect(url: str, message: str | None = None, kind: str = "ok") -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if message:
        flash(resp, message, kind)
    return resp


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    p = getattr(request.state, "principal", None)
    fl = _pop_flash(request)
    ctx.setdefault("principal", p)
    ctx.setdefault("user", p.user if p else None)
    ctx.setdefault("csrf", p.csrf_token if p else "")
    ctx.setdefault("app_name", settings_of(request).app_name)
    ctx["flash"] = fl
    ctx["request"] = request
    ctx["nav"] = ctx.get("nav", "")
    resp = templates.TemplateResponse(request, template, ctx, status_code=status_code)
    if fl:
        resp.delete_cookie(FLASH_COOKIE, path="/")
    return resp
