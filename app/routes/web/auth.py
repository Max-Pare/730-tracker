# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import utcnow
from ...security import auth
from ...services import admin as admin_svc
from ...web import clear_session_cookie, current_principal, redirect, render, safe_next, set_session_cookie, settings_of

router = APIRouter()


def _device_label(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")):
        if key in ua:
            return f"Browser – {name}"
    return "Browser"


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    if current_principal(request, db):
        return redirect("/dashboard")
    if not admin_svc.has_users(db):
        return redirect("/register")
    return redirect("/login")


@router.get("/login")
def login_form(request: Request, next: str | None = None, db: Session = Depends(get_db)):
    if current_principal(request, db):
        return redirect(safe_next(next))
    if not admin_svc.has_users(db):
        return redirect("/register")
    return render(request, "auth/login.html", next=safe_next(next), registration=admin_svc.registration_mode(db))


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    s = settings_of(request)
    try:
        user, dek = auth.authenticate(db, s, username, password)
    except auth.AuthError as exc:
        return render(
            request, "auth/login.html", status_code=400, error=exc.message, username=username,
            next=safe_next(next), registration=admin_svc.registration_mode(db),
        )  # fmt: skip
    token, _ = auth.create_session(db, s, user, dek, "web", _device_label(request))
    resp = redirect(safe_next(next))
    set_session_cookie(request, resp, token)
    return resp


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    p = current_principal(request, db)
    if p:
        auth.revoke_session(db, p.session)
    resp = redirect("/login", "Sei uscito dal tuo account.", "info")
    clear_session_cookie(resp)
    return resp


def _registration_state(db: Session, invite: str | None) -> tuple[bool, bool, str | None]:
    """(allowed, first_user, error)"""
    if not admin_svc.has_users(db):
        return True, True, None
    mode = admin_svc.registration_mode(db)
    if mode == "open":
        return True, False, None
    if invite and admin_svc.find_valid_invite(db, invite):
        return True, False, None
    if invite:
        return False, False, "L'invito non è valido o è scaduto."
    if mode == "invite":
        return False, False, "La registrazione è possibile solo tramite un invito dell'amministratore."
    return False, False, "Le registrazioni sono chiuse."


@router.get("/register")
def register_form(request: Request, invite: str | None = None, db: Session = Depends(get_db)):
    allowed, first, error = _registration_state(db, invite)
    return render(request, "auth/register.html", allowed=allowed, first_user=first, error=error, invite=invite or "")


@router.post("/register")
def register(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    invite: str = Form(""),
    db: Session = Depends(get_db),
):
    s = settings_of(request)
    allowed, first, error = _registration_state(db, invite or None)
    ctx = dict(allowed=allowed, first_user=first, invite=invite, username=username)
    if not allowed:
        return render(request, "auth/register.html", status_code=403, error=error, **ctx)
    if password != password2:
        return render(request, "auth/register.html", status_code=400, error="Le password non coincidono.", **ctx)
    inv = admin_svc.find_valid_invite(db, invite) if invite else None
    try:
        acct = auth.create_user(db, s, username, password, role="admin" if first else "user")
    except auth.AuthError as exc:
        return render(request, "auth/register.html", status_code=400, error=exc.message, **ctx)
    if inv:
        inv.used_at = utcnow()
        db.commit()
    token, _ = auth.create_session(db, s, acct.user, acct.dek, "web", _device_label(request))
    request.state.principal = auth.resolve_token(db, s, token, "web")
    resp = render(request, "auth/recovery_code.html", recovery_code=acct.recovery_code, first_user=first)
    set_session_cookie(request, resp, token)
    return resp


@router.get("/recover")
def recover_form(request: Request):
    return render(request, "auth/recover.html")


@router.post("/recover")
def recover(
    request: Request,
    username: str = Form(""),
    recovery_code: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    db: Session = Depends(get_db),
):
    s = settings_of(request)
    if password != password2:
        return render(request, "auth/recover.html", status_code=400, error="Le password non coincidono.", username=username)
    try:
        user, dek, new_code = auth.recover_account(db, s, username, recovery_code, password)
    except auth.AuthError as exc:
        return render(request, "auth/recover.html", status_code=400, error=exc.message, username=username)
    token, _ = auth.create_session(db, s, user, dek, "web", _device_label(request))
    request.state.principal = auth.resolve_token(db, s, token, "web")
    resp = render(request, "auth/recovery_code.html", recovery_code=new_code, recovered=True)
    set_session_cookie(request, resp, token)
    return resp
