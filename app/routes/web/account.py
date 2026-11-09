# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AuthSession
from ...security import auth
from ...security.auth import Principal
from ...services import admin as admin_svc
from ...services.profile import FamilyMember, load_profile, save_profile
from ...web import check_csrf, clear_session_cookie, redirect, render, require_user, settings_of

router = APIRouter(prefix="/account")


def _sessions(p: Principal) -> list[dict]:
    rows = sorted(p.user.sessions, key=lambda s: s.last_seen_at, reverse=True)
    return [
        {"id": s.id, "kind": s.kind, "label": auth.session_label(p.dek, s) or ("App" if s.kind == "api" else "Browser"),
         "created_at": s.created_at, "last_seen_at": s.last_seen_at, "current": s.id == p.session.id}
        for s in rows
    ]  # fmt: skip


def _page(request: Request, p: Principal, status_code: int = 200, **extra):
    return render(request, "account/index.html", status_code=status_code, nav="account", profile=load_profile(p), sessions=_sessions(p), **extra)


@router.get("")
def account(request: Request, p: Principal = Depends(require_user)):
    return _page(request, p)


@router.post("/profile")
def update_profile(
    request: Request,
    full_name: str = Form(""),
    tax_code: str = Form(""),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    profile = load_profile(p)
    try:
        updated = profile.model_validate({**profile.model_dump(), "full_name": full_name, "tax_code": tax_code})
    except ValidationError:
        return _page(request, p, 400, error="Codice fiscale non valido.")
    save_profile(db, p, updated)
    return redirect("/account", "Profilo aggiornato.")


@router.post("/family")
def add_family(
    request: Request,
    name: str = Form(""),
    tax_code: str = Form(""),
    relation: str = Form("altro"),
    dependent: str = Form(""),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    profile = load_profile(p)
    try:
        member = FamilyMember(name=name, tax_code=tax_code, relation=relation, dependent=dependent == "on")
    except ValidationError as exc:
        msg = "Nome obbligatorio." if any(e["loc"] == ("name",) for e in exc.errors()) else "Codice fiscale non valido."
        return _page(request, p, 400, error=msg)
    if len(profile.family) >= 20:
        return _page(request, p, 400, error="Troppi familiari.")
    profile.family.append(member)
    save_profile(db, p, profile)
    return redirect("/account", f"{member.name} aggiunto/a ai familiari.")


@router.post("/family/{member_id}/delete")
def delete_family(member_id: str, csrf: str = Form(""), p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    profile = load_profile(p)
    profile.family = [m for m in profile.family if m.id != member_id]
    save_profile(db, p, profile)
    return redirect("/account", "Familiare rimosso.", "info")


@router.post("/family/{member_id}/toggle")
def toggle_family(member_id: str, csrf: str = Form(""), p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    profile = load_profile(p)
    m = profile.member(member_id)
    if m:
        m.dependent = not m.dependent
        save_profile(db, p, profile)
    return redirect("/account", "Familiare aggiornato.")


@router.post("/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password2: str = Form(""),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    if new_password != new_password2:
        return _page(request, p, 400, error="Le nuove password non coincidono.")
    try:
        auth.change_password(db, settings_of(request), p.user, current_password, new_password)
    except auth.AuthError as exc:
        return _page(request, p, 400, error=exc.message)
    # Sign out every other device.
    for s in list(p.user.sessions):
        if s.id != p.session.id:
            db.delete(s)
    db.commit()
    return redirect("/account", "Password aggiornata. Gli altri dispositivi sono stati disconnessi.")


@router.post("/recovery")
def new_recovery_code(
    request: Request,
    current_password: str = Form(""),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    if auth.verify_password(p.user, current_password) is None:
        return _page(request, p, 400, error="Password non corretta.")
    code = auth.regenerate_recovery_code(db, p.user, p.dek)
    return render(request, "auth/recovery_code.html", recovery_code=code, regenerated=True)


@router.post("/sessions/{sid}/revoke")
def revoke(sid: str, csrf: str = Form(""), p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    sess = db.get(AuthSession, sid)
    if sess is None or sess.user_id != p.user.id:
        raise HTTPException(404)
    auth.revoke_session(db, sess)
    if sid == p.session.id:
        resp = redirect("/login", "Sessione chiusa.", "info")
        clear_session_cookie(resp)
        return resp
    return redirect("/account", "Dispositivo disconnesso.", "info")


@router.post("/delete")
def delete_account(
    request: Request,
    current_password: str = Form(""),
    confirm: str = Form(""),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    if confirm.strip().lower() != p.user.username or auth.verify_password(p.user, current_password) is None:
        return _page(request, p, 400, error="Per eliminare l'account inserisci la password e il tuo nome utente.")
    if p.user.is_admin and admin_svc.active_admin_count(db) <= 1 and len(admin_svc.list_users(db)) > 1:
        return _page(request, p, 400, error="Sei l'unico amministratore: nomina prima un altro amministratore.")
    admin_svc.delete_user(db, settings_of(request), p.user)
    resp = redirect("/login", "Account e dati eliminati definitivamente.", "info")
    clear_session_cookie(resp)
    return resp
