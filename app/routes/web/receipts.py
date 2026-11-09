# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...db import get_db
from ...ocr.parser import parse_amount_input
from ...security.auth import Principal
from ...services import export, ingest, receipts, storage
from ...services.domain import ReceiptData, ReceiptFields
from ...services.profile import load_profile
from ...services.tax import evaluate, summarize
from ...web import check_csrf, redirect, render, require_user, settings_of

router = APIRouter()

PAGE_SIZE = 25


def _int_or_none(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


@router.get("/dashboard")
def dashboard(request: Request, year: str | None = None, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    profile = load_profile(p)
    records = receipts.list_all(db, p)
    years = receipts.available_years(records)
    current = date.today().year
    y = _int_or_none(year) or (years[0] if years else current)
    if y not in years:
        years = sorted(set(years) | {y}, reverse=True)
    summary = summarize(records, profile, y)
    drafts_all = sum(1 for r in records if r.data.status == "bozza")
    return render(
        request, "dashboard.html", nav="dashboard", summary=summary, years=years, year=y,
        drafts_all=drafts_all, has_records=bool(records), profile=profile,
    )  # fmt: skip


@router.get("/receipts")
def list_receipts(
    request: Request,
    year: str | None = None,
    category: str | None = None,
    status: str | None = None,
    beneficiary: str | None = None,
    esito: str | None = None,
    q: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    profile = load_profile(p)
    records = receipts.list_all(db, p)
    filtered = receipts.filter_records(
        records, profile, year=_int_or_none(year), category=category or None, status=status or None,
        beneficiary=beneficiary or None, q=q, evaluation=esito or None, sort=sort,
    )  # fmt: skip
    pages = max(1, math.ceil(len(filtered) / PAGE_SIZE))
    page = min(max(1, page), pages)
    items = [(r, evaluate(r.data, profile)) for r in filtered[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]]
    total = sum(r.data.amount_cents or 0 for r in filtered)
    filters = dict(year=year or "", category=category or "", status=status or "", beneficiary=beneficiary or "", esito=esito or "", q=q or "", sort=sort)
    return render(
        request, "receipts/list.html", nav="receipts", items=items, count=len(filtered), total=total,
        page=page, pages=pages, filters=filters, years=receipts.available_years(records), profile=profile,
    )  # fmt: skip


@router.get("/receipts/new")
def new_receipt(request: Request, p: Principal = Depends(require_user)):
    s = settings_of(request)
    return render(request, "receipts/new.html", nav="new", max_mb=s.max_upload_mb, max_files=s.max_files_per_upload)


@router.post("/receipts/upload")
def upload(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    csrf: str = Form(""),
    p: Principal = Depends(require_user),
    db: Session = Depends(get_db),
):
    check_csrf(p, csrf)
    s = settings_of(request)
    files = [f for f in files if f.filename]
    if not files:
        return redirect("/receipts/new", "Seleziona almeno una foto o un PDF.", "error")
    if len(files) > s.max_files_per_upload:
        return redirect("/receipts/new", f"Puoi caricare al massimo {s.max_files_per_upload} file per volta.", "error")
    profile = load_profile(p)
    created, errors = [], []
    for f in files:
        data = f.file.read(s.max_upload_bytes + 1)
        try:
            created.append(ingest.ingest(db, s, p, profile, data, f.filename))
        except ingest.UploadError as exc:
            errors.append(f"{f.filename}: {exc}")
    if len(created) == 1 and not errors:
        return redirect(f"/receipts/{created[0].id}", "Documento elaborato: controlla i dati estratti e conferma.")
    msg = f"{len(created)} documenti elaborati."
    if errors:
        msg += " Errori: " + "; ".join(errors)
    if not created:
        return redirect("/receipts/new", msg, "error")
    return redirect("/receipts?status=bozza&sort=created_desc", msg, "error" if errors else "ok")


def _fields_from_form(form) -> tuple[ReceiptFields | None, list[str]]:
    errors: list[str] = []
    raw = {k: (form.get(k) or "").strip() for k in (
        "date", "provider_name", "provider_vat", "provider_tax_code", "document_number", "category",
        "payment_method", "beneficiary", "patient_tax_code", "description", "notes", "tags",
    )}  # fmt: skip
    data: dict = {k: (v or None) for k, v in raw.items()}
    data["tags"] = raw["tags"]
    data["ssn_provider"] = form.get("ssn_provider") == "on"
    action = form.get("action") or "verify"
    data["status"] = "da_verificare" if action == "later" else "verificato"
    data["payment_method"] = raw["payment_method"] or "sconosciuto"
    data["beneficiary"] = raw["beneficiary"] or "self"
    for key in ("amount", "deductible"):
        try:
            data[f"{key}_cents"] = parse_amount_input(form.get(key))
        except ValueError as exc:
            errors.append(str(exc))
    if data.get("deductible_cents") is not None and data.get("deductible_cents") == data.get("amount_cents"):
        data["deductible_cents"] = None
    if errors:
        return None, errors
    try:
        return ReceiptFields.model_validate(data), []
    except ValidationError as exc:
        names = {"date": "data", "amount_cents": "importo", "deductible_cents": "importo detraibile", "category": "categoria"}
        return None, [f"Campo «{names.get(str(e['loc'][0]), e['loc'][0])}» non valido." for e in exc.errors()]


@router.get("/receipts/manual")
def manual_form(request: Request, p: Principal = Depends(require_user)):
    profile = load_profile(p)
    blank = receipts.ReceiptRecord("", None, None, ReceiptData(status="verificato", date=date.today()))
    return render(request, "receipts/edit.html", nav="new", rec=blank, ev=None, profile=profile, duplicates=[], is_new=True)


@router.post("/receipts/manual")
async def manual_create(request: Request, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(p, form.get("csrf"))
    profile = load_profile(p)
    fields, errors = _fields_from_form(form)
    if errors:
        blank = receipts.ReceiptRecord("", None, None, ReceiptData(status="verificato"))
        return render(request, "receipts/edit.html", status_code=400, nav="new", rec=blank, ev=None, profile=profile,
                      duplicates=[], is_new=True, errors=errors, form=form)  # fmt: skip
    rec = receipts.insert(db, p, ReceiptData(source="manuale").apply(fields))
    return redirect(f"/receipts/{rec.id}", "Spesa aggiunta.")


def _get_or_404(db: Session, p: Principal, rid: str) -> receipts.ReceiptRecord:
    rec = receipts.get(db, p, rid)
    if rec is None:
        raise HTTPException(404)
    return rec


@router.get("/receipts/{rid}")
def receipt_detail(rid: str, request: Request, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    rec = _get_or_404(db, p, rid)
    profile = load_profile(p)
    dups = receipts.find_duplicates(receipts.list_all(db, p), rec)
    return render(request, "receipts/edit.html", nav="receipts", rec=rec, ev=evaluate(rec.data, profile), profile=profile, duplicates=dups, is_new=False)


@router.post("/receipts/{rid}")
async def receipt_save(rid: str, request: Request, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(p, form.get("csrf"))
    rec = _get_or_404(db, p, rid)
    profile = load_profile(p)
    fields, errors = _fields_from_form(form)
    if errors:
        return render(request, "receipts/edit.html", status_code=400, nav="receipts", rec=rec, ev=evaluate(rec.data, profile),
                      profile=profile, duplicates=[], is_new=False, errors=errors, form=form)  # fmt: skip
    rec.data = rec.data.apply(fields)
    receipts.save(db, p, rec)
    if form.get("action") == "verify_next":
        drafts = [r for r in receipts.list_all(db, p) if r.data.status == "bozza" and r.id != rid]
        if drafts:
            return redirect(f"/receipts/{drafts[0].id}", "Salvato. Ecco la prossima bozza.")
    return redirect(f"/receipts/{rid}", "Modifiche salvate.")


@router.post("/receipts/{rid}/delete")
def receipt_delete(rid: str, request: Request, csrf: str = Form(""), p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    if not receipts.delete(db, settings_of(request), p, rid):
        raise HTTPException(404)
    return redirect("/receipts", "Documento eliminato.", "info")


@router.post("/receipts/{rid}/reprocess")
def receipt_reprocess(rid: str, request: Request, csrf: str = Form(""), p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(p, csrf)
    rec = _get_or_404(db, p, rid)
    try:
        ingest.reprocess(db, settings_of(request), p, load_profile(p), rec)
    except ingest.UploadError as exc:
        return redirect(f"/receipts/{rid}", str(exc), "error")
    return redirect(f"/receipts/{rid}", "OCR eseguito di nuovo: controlla i dati.")


@router.get("/receipts/{rid}/file/{kind}")
def receipt_file(rid: str, kind: str, request: Request, download: int = 0, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    rec = _get_or_404(db, p, rid)
    fid = rec.data.files.get(kind)
    got = storage.get_file(db, settings_of(request), p, fid) if fid else None
    if not got:
        raise HTTPException(404)
    content, ctype = got
    ext = {"image/jpeg": "jpg", "application/pdf": "pdf", "image/png": "png"}.get(ctype, "bin")
    disp = "attachment" if download else "inline"
    return Response(
        content,
        media_type=ctype,
        headers={
            "Content-Disposition": f'{disp}; filename="documento-{rid[:8]}-{kind}.{ext}"',
            "Cache-Control": "private, no-store",
            # Chrome refuses to render PDFs in a sandboxed document, so only images get `sandbox`.
            "Content-Security-Policy": "frame-ancestors 'none'" if ctype == "application/pdf"
            else "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.get("/export.csv")
def export_csv(year: str | None = None, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    profile = load_profile(p)
    y = _int_or_none(year)
    recs = receipts.filter_records(receipts.list_all(db, p), profile, year=y, sort="date_asc")
    name = f"spese-sanitarie-{y or 'tutte'}.csv"
    return Response(export.to_csv(recs, profile), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip


@router.get("/export.zip")
def export_zip(request: Request, year: str | None = None, p: Principal = Depends(require_user), db: Session = Depends(get_db)):
    profile = load_profile(p)
    y = _int_or_none(year)
    recs = receipts.filter_records(receipts.list_all(db, p), profile, year=y, sort="date_asc")
    data = export.to_zip(db, settings_of(request), p, recs, profile, y)
    name = f"archivio-730-{y or 'tutte'}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})
