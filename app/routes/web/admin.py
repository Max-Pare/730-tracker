# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin pages. Admins manage accounts but can never see or decrypt user data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import User, utcnow
from ...security.auth import Principal
from ...services import admin as admin_svc
from ...web import check_csrf, redirect, render, require_admin, settings_of

router = APIRouter(prefix="/admin")


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


@router.get("")
def admin_home(request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return render(
        request, "admin/index.html", nav="admin", users=admin_svc.list_users(db), invites=admin_svc.list_invites(db),
        mode=admin_svc.registration_mode(db), modes=admin_svc.REGISTRATION_MODES, now=utcnow(), new_invite=None,
    )  # fmt: skip


@router.post("/settings")
def admin_settings(mode: str = Form(...), csrf: str = Form(""), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    if mode not in admin_svc.REGISTRATION_MODES:
        raise HTTPException(400)
    admin_svc.set_setting(db, "registration_mode", mode)
    return redirect("/admin", "Impostazioni salvate.")


@router.post("/invites")
def admin_invite(request: Request, note: str = Form(""), csrf: str = Form(""), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    token, inv = admin_svc.create_invite(db, settings_of(request), p.user, note)
    link = f"{_base_url(request)}/register?invite={token}"
    return render(
        request, "admin/index.html", nav="admin", users=admin_svc.list_users(db), invites=admin_svc.list_invites(db),
        mode=admin_svc.registration_mode(db), modes=admin_svc.REGISTRATION_MODES, now=utcnow(),
        new_invite={"link": link, "token": token, "expires_at": inv.expires_at},
    )  # fmt: skip


@router.post("/invites/{invite_id}/delete")
def admin_invite_delete(invite_id: str, csrf: str = Form(""), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    admin_svc.delete_invite(db, invite_id)
    return redirect("/admin", "Invito revocato.", "info")


def _target(db: Session, p: Principal, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404)
    if u.id == p.user.id:
        raise HTTPException(400, "Usa la pagina Account per modificare il tuo profilo.")
    return u


@router.post("/users/{user_id}/toggle")
def admin_toggle(user_id: str, csrf: str = Form(""), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    u = _target(db, p, user_id)
    u.is_active = not u.is_active
    if not u.is_active:
        for s in list(u.sessions):
            db.delete(s)
    db.commit()
    return redirect("/admin", f"Account {u.username} {'riattivato' if u.is_active else 'disattivato'}.")


@router.post("/users/{user_id}/role")
def admin_role(user_id: str, csrf: str = Form(""), p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    u = _target(db, p, user_id)
    u.role = "user" if u.is_admin else "admin"
    db.commit()
    return redirect("/admin", f"{u.username} ora è {'amministratore' if u.is_admin else 'utente'}.")


@router.post("/users/{user_id}/delete")
def admin_delete(
    request: Request, user_id: str, confirm: str = Form(""), csrf: str = Form(""),
    p: Principal = Depends(require_admin), db: Session = Depends(get_db),
):  # fmt: skip
    check_csrf(p, csrf)
    u = _target(db, p, user_id)
    if confirm.strip().lower() != u.username:
        return redirect("/admin", "Per eliminare un account digita il suo nome utente per conferma.", "error")
    name = u.username
    admin_svc.delete_user(db, settings_of(request), u)
    return redirect("/admin", f"Account {name} e tutti i suoi dati eliminati.", "info")
