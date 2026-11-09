# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .web import LoginRequired, render

log = logging.getLogger(__name__)

CSP = (
    "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
    "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reject cross-site form posts (login CSRF etc.) before any handler runs.
        if request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith("/api/"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin and origin != "null":
                from urllib.parse import urlparse

                o = urlparse(origin)
                allowed = {request.headers.get("host", request.url.netloc), request.headers.get("x-forwarded-host")}
                if o.netloc and o.netloc not in allowed:
                    return PlainTextResponse("Richiesta cross-site rifiutata.", status_code=403)
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(self), geolocation=(), microphone=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.url.path.startswith("/static/"):
            h.setdefault("Cache-Control", "no-store")
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

    app = FastAPI(title="730 Tracker", version=__version__, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.add_middleware(SecurityHeaders)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    from .routes.api import router as api_router
    from .routes.web import router as web_router

    app.include_router(api_router)
    app.include_router(web_router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        from urllib.parse import quote

        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        msg = exc.detail if isinstance(exc.detail, str) else "Errore"
        if exc.status_code == 404:
            msg = "Pagina o documento non trovato."
        return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=msg)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": _clean_errors(exc.errors())}, status_code=422)
        return render(request, "error.html", status_code=422, code=422, message="Dati del modulo non validi.")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        from fastapi.responses import FileResponse

        return FileResponse(static_dir / "manifest.webmanifest", media_type="application/manifest+json")

    return app


def _clean_errors(errors) -> list[dict]:
    out = []
    for e in errors:
        out.append({"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": e.get("type", "")})
    return out
