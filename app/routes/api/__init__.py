# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON API (``/api/v1``) used by the Android app. Authentication: ``Authorization: Bearer <token>``."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ... import __version__
from ...db import get_db
from ...models import AuthSession, utcnow
from ...security import auth
from ...security.auth import Principal
from ...services import admin as admin_svc
from ...services import export, ingest, receipts, storage
from ...services.domain import CATEGORIES, PAYMENT_METHODS, RELATIONS, STATUSES, ReceiptData, ReceiptFields
from ...services.profile import FamilyMember, Profile, load_profile, save_profile
from ...services.tax import evaluate, summarize

router = APIRouter(prefix="/api/v1", tags=["api"])


# --------------------------------------------------------------------------- auth plumbing


def api_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    p = auth.resolve_token(db, request.app.state.settings, token.strip(), "api") if scheme.lower() == "bearer" else None
    if p is None:
        raise HTTPException(401, "Non autenticato.", headers={"WWW-Authenticate": "Bearer"})
    return p


def _auth_error(exc: auth.AuthError, status: int = 400) -> HTTPException:
    return HTTPException(status, {"code": exc.code, "message": exc.message})


# --------------------------------------------------------------------------- schemas


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    token: str
    user: UserOut
    recovery_code: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str
    device_name: str | None = Field(default=None, max_length=80)


class RegisterIn(LoginIn):
    invite: str | None = None


class RecoverIn(BaseModel):
    username: str
    recovery_code: str
    new_password: str
    device_name: str | None = Field(default=None, max_length=80)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class PasswordOnlyIn(BaseModel):
    current_password: str


class ProfileIn(BaseModel):
    full_name: str | None = None
    tax_code: str | None = None


class FamilyIn(BaseModel):
    name: str
    tax_code: str | None = None
    relation: str = "altro"
    dependent: bool = True


class EvaluationOut(BaseModel):
    status: str
    label: str
    group: str | None
    eligible_cents: int
    reasons: list[str]
    warnings: list[str]


class ReceiptOut(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    data: ReceiptData
    beneficiary_label: str
    evaluation: EvaluationOut
    has_scan: bool
    has_original: bool
    original_type: str | None
    duplicates: list[str] = Field(default_factory=list)


class ReceiptPage(BaseModel):
    items: list[ReceiptOut]
    total: int
    page: int
    pages: int
    total_amount_cents: int


class UploadResult(BaseModel):
    created: list[ReceiptOut]
    errors: list[dict]


def _user_out(u) -> UserOut:
    return UserOut(id=u.id, username=u.username, role=u.role, created_at=u.created_at)


def _receipt_out(rec: receipts.ReceiptRecord, profile: Profile, dups: list[str] | None = None) -> ReceiptOut:
    ev = evaluate(rec.data, profile)
    d = rec.data
    return ReceiptOut(
        id=rec.id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        data=d,
        beneficiary_label=profile.beneficiary_label(d.beneficiary),
        evaluation=EvaluationOut(status=ev.status, label=ev.label, group=ev.group, eligible_cents=ev.eligible_cents, reasons=ev.reasons, warnings=ev.warnings),
        has_scan="scan" in d.files,
        has_original="original" in d.files,
        original_type=d.file_types.get("original"),
        duplicates=dups or [],
    )


def _label(name: str | None, fallback: str) -> str:
    return (name or "").strip()[:80] or fallback


# --------------------------------------------------------------------------- public endpoints


@router.get("/server-info")
def server_info(request: Request, db: Session = Depends(get_db)):
    return {
        "name": request.app.state.settings.app_name,
        "version": __version__,
        "api": 1,
        "registration_mode": admin_svc.registration_mode(db),
        "needs_setup": not admin_svc.has_users(db),
        "max_upload_mb": request.app.state.settings.max_upload_mb,
    }


@router.get("/meta")
def meta():
    return {
        "categories": [
            {"code": c.code, "label": c.label, "group": c.group, "trace_exempt": c.trace_exempt, "hint": c.hint}
            for c in CATEGORIES.values()
        ],
        "payment_methods": [{"code": k, "label": v} for k, v in PAYMENT_METHODS.items()],
        "statuses": [{"code": k, "label": v} for k, v in STATUSES.items()],
        "relations": [{"code": k, "label": v} for k, v in RELATIONS.items()],
    }


@router.post("/auth/login", response_model=TokenOut)
def api_login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    try:
        user, dek = auth.authenticate(db, s, body.username, body.password)
    except auth.AuthError as exc:
        raise _auth_error(exc, 401) from None
    token, _ = auth.create_session(db, s, user, dek, "api", _label(body.device_name, "App Android"))
    return TokenOut(token=token, user=_user_out(user))


@router.post("/auth/register", response_model=TokenOut)
def api_register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    first = not admin_svc.has_users(db)
    inv = None
    if not first:
        mode = admin_svc.registration_mode(db)
        inv = admin_svc.find_valid_invite(db, body.invite) if body.invite else None
        if mode != "open" and inv is None:
            raise HTTPException(403, {"code": "registration_closed", "message": "Registrazione non consentita senza un invito valido."})
    try:
        acct = auth.create_user(db, s, body.username, body.password, role="admin" if first else "user")
    except auth.AuthError as exc:
        raise _auth_error(exc) from None
    if inv:
        inv.used_at = utcnow()
        db.commit()
    token, _ = auth.create_session(db, s, acct.user, acct.dek, "api", _label(body.device_name, "App Android"))
    return TokenOut(token=token, user=_user_out(acct.user), recovery_code=acct.recovery_code)


@router.post("/auth/recover", response_model=TokenOut)
def api_recover(body: RecoverIn, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    try:
        user, dek, code = auth.recover_account(db, s, body.username, body.recovery_code, body.new_password)
    except auth.AuthError as exc:
        raise _auth_error(exc) from None
    token, _ = auth.create_session(db, s, user, dek, "api", _label(body.device_name, "App Android"))
    return TokenOut(token=token, user=_user_out(user), recovery_code=code)


@router.post("/auth/logout", status_code=204)
def api_logout(p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    auth.revoke_session(db, p.session)
    return Response(status_code=204)


# --------------------------------------------------------------------------- account


@router.get("/me")
def me(p: Principal = Depends(api_principal)):
    return {"user": _user_out(p.user), "profile": load_profile(p)}


@router.put("/me/profile")
def update_profile(body: ProfileIn, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    try:
        updated = Profile.model_validate({**profile.model_dump(), **body.model_dump()})
    except ValidationError:
        raise HTTPException(422, {"code": "invalid_tax_code", "message": "Codice fiscale non valido."}) from None
    save_profile(db, p, updated)
    return updated


@router.post("/me/family")
def add_family(body: FamilyIn, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    try:
        m = FamilyMember(**body.model_dump())
    except ValidationError:
        raise HTTPException(422, {"code": "invalid_member", "message": "Dati del familiare non validi."}) from None
    profile.family.append(m)
    save_profile(db, p, profile)
    return profile


@router.put("/me/family/{member_id}")
def update_family(member_id: str, body: FamilyIn, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    idx = next((i for i, m in enumerate(profile.family) if m.id == member_id), None)
    if idx is None:
        raise HTTPException(404, "Familiare non trovato.")
    try:
        profile.family[idx] = FamilyMember(id=member_id, **body.model_dump())
    except ValidationError:
        raise HTTPException(422, {"code": "invalid_member", "message": "Dati del familiare non validi."}) from None
    save_profile(db, p, profile)
    return profile


@router.delete("/me/family/{member_id}")
def delete_family(member_id: str, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    profile.family = [m for m in profile.family if m.id != member_id]
    save_profile(db, p, profile)
    return profile


@router.post("/me/password", status_code=204)
def change_password(body: PasswordIn, request: Request, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    try:
        auth.change_password(db, request.app.state.settings, p.user, body.current_password, body.new_password)
    except auth.AuthError as exc:
        raise _auth_error(exc) from None
    for s in list(p.user.sessions):
        if s.id != p.session.id:
            db.delete(s)
    db.commit()
    return Response(status_code=204)


@router.post("/me/recovery-code")
def new_recovery_code(body: PasswordOnlyIn, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    if auth.verify_password(p.user, body.current_password) is None:
        raise HTTPException(400, {"code": "invalid_credentials", "message": "Password non corretta."})
    return {"recovery_code": auth.regenerate_recovery_code(db, p.user, p.dek)}


@router.get("/me/sessions")
def sessions(p: Principal = Depends(api_principal)):
    return [
        {"id": s.id, "kind": s.kind, "label": auth.session_label(p.dek, s), "created_at": s.created_at,
         "last_seen_at": s.last_seen_at, "current": s.id == p.session.id}
        for s in sorted(p.user.sessions, key=lambda s: s.last_seen_at, reverse=True)
    ]  # fmt: skip


@router.delete("/me/sessions/{sid}", status_code=204)
def revoke_session(sid: str, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    sess = db.get(AuthSession, sid)
    if sess is None or sess.user_id != p.user.id:
        raise HTTPException(404, "Sessione non trovata.")
    auth.revoke_session(db, sess)
    return Response(status_code=204)


@router.post("/me/delete", status_code=204)
def delete_account(body: PasswordOnlyIn, request: Request, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    if auth.verify_password(p.user, body.current_password) is None:
        raise HTTPException(400, {"code": "invalid_credentials", "message": "Password non corretta."})
    if p.user.is_admin and admin_svc.active_admin_count(db) <= 1 and len(admin_svc.list_users(db)) > 1:
        raise HTTPException(400, {"code": "last_admin", "message": "Sei l'unico amministratore."})
    admin_svc.delete_user(db, request.app.state.settings, p.user)
    return Response(status_code=204)


# --------------------------------------------------------------------------- receipts


@router.get("/dashboard")
def dashboard(year: int | None = None, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    records = receipts.list_all(db, p)
    years = receipts.available_years(records)
    y = year or (years[0] if years else date.today().year)
    return {
        "years": sorted(set(years) | {y}, reverse=True),
        "drafts_total": sum(1 for r in records if r.data.status == "bozza"),
        "summary": summarize(records, profile, y).to_dict(),
    }


@router.get("/receipts", response_model=ReceiptPage)
def list_receipts(
    year: int | None = None,
    category: str | None = None,
    status: str | None = None,
    beneficiary: str | None = None,
    evaluation: str | None = None,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    p: Principal = Depends(api_principal),
    db: Session = Depends(get_db),
):
    profile = load_profile(p)
    filtered = receipts.filter_records(
        receipts.list_all(db, p), profile, year=year, category=category, status=status, beneficiary=beneficiary,
        q=q, evaluation=evaluation, sort=sort,
    )  # fmt: skip
    pages = max(1, -(-len(filtered) // page_size))
    chunk = filtered[(page - 1) * page_size : page * page_size]
    return ReceiptPage(
        items=[_receipt_out(r, profile) for r in chunk],
        total=len(filtered),
        page=page,
        pages=pages,
        total_amount_cents=sum(r.data.amount_cents or 0 for r in filtered),
    )


@router.post("/receipts/upload", response_model=UploadResult)
def upload(request: Request, files: list[UploadFile] = File(...), p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    s = request.app.state.settings
    if len(files) > s.max_files_per_upload:
        raise HTTPException(400, f"Massimo {s.max_files_per_upload} file per volta.")
    profile = load_profile(p)
    created, errors = [], []
    for f in files:
        try:
            created.append(ingest.ingest(db, s, p, profile, f.file.read(s.max_upload_bytes + 1), f.filename))
        except ingest.UploadError as exc:
            errors.append({"filename": f.filename, "message": str(exc)})
    all_recs = receipts.list_all(db, p) if created else []
    return UploadResult(
        created=[_receipt_out(r, profile, [d.id for d in receipts.find_duplicates(all_recs, r)]) for r in created],
        errors=errors,
    )


@router.post("/receipts", response_model=ReceiptOut, status_code=201)
def create_receipt(body: ReceiptFields, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    rec = receipts.insert(db, p, ReceiptData(source="manuale").apply(body))
    return _receipt_out(rec, load_profile(p))


def _get(db: Session, p: Principal, rid: str) -> receipts.ReceiptRecord:
    rec = receipts.get(db, p, rid)
    if rec is None:
        raise HTTPException(404, "Documento non trovato.")
    return rec


@router.get("/receipts/{rid}", response_model=ReceiptOut)
def get_receipt(rid: str, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    rec = _get(db, p, rid)
    dups = [d.id for d in receipts.find_duplicates(receipts.list_all(db, p), rec)]
    return _receipt_out(rec, load_profile(p), dups)


@router.put("/receipts/{rid}", response_model=ReceiptOut)
def update_receipt(rid: str, body: ReceiptFields, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    rec = _get(db, p, rid)
    rec.data = rec.data.apply(body)
    receipts.save(db, p, rec)
    return _receipt_out(rec, load_profile(p))


@router.delete("/receipts/{rid}", status_code=204)
def delete_receipt(rid: str, request: Request, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    if not receipts.delete(db, request.app.state.settings, p, rid):
        raise HTTPException(404, "Documento non trovato.")
    return Response(status_code=204)


@router.post("/receipts/{rid}/reprocess", response_model=ReceiptOut)
def reprocess(rid: str, request: Request, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    rec = _get(db, p, rid)
    profile = load_profile(p)
    try:
        rec = ingest.reprocess(db, request.app.state.settings, p, profile, rec)
    except ingest.UploadError as exc:
        raise HTTPException(400, str(exc)) from None
    return _receipt_out(rec, profile)


@router.get("/receipts/{rid}/files/{kind}")
def receipt_file(rid: str, kind: str, request: Request, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    rec = _get(db, p, rid)
    fid = rec.data.files.get(kind)
    got = storage.get_file(db, request.app.state.settings, p, fid) if fid else None
    if not got:
        raise HTTPException(404, "File non trovato.")
    content, ctype = got
    return Response(content, media_type=ctype, headers={"Cache-Control": "private, no-store"})


@router.get("/export.csv")
def export_csv(year: int | None = None, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    recs = receipts.filter_records(receipts.list_all(db, p), profile, year=year, sort="date_asc")
    return Response(export.to_csv(recs, profile), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="spese-sanitarie-{year or "tutte"}.csv"'})  # fmt: skip


@router.get("/export.zip")
def export_zip(request: Request, year: int | None = None, p: Principal = Depends(api_principal), db: Session = Depends(get_db)):
    profile = load_profile(p)
    recs = receipts.filter_records(receipts.list_all(db, p), profile, year=year, sort="date_asc")
    data = export.to_zip(db, request.app.state.settings, p, recs, profile, year)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="archivio-730-{year or "tutte"}.zip"'})  # fmt: skip
