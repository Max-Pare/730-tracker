# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web UI flows: registration policy, auth, CSRF, receipts CRUD, exports."""

import io
import shutil
import zipfile

import pytest
from conftest import PASSWORD, create_invite, csrf_of, make_client, register

import receipt_samples as S
import synth

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def test_first_user_is_admin_and_registration_defaults_to_invite(app):
    admin = make_client(app)
    r, code = register(admin, "admin")
    assert r.status_code == 200 and code
    assert admin.get("/admin").status_code == 200

    other = make_client(app)
    r, _ = register(other, "intruso")
    assert r.status_code == 403
    assert other.get("/dashboard", follow_redirects=False).status_code == 303


def test_invite_is_single_use(app):
    admin = make_client(app)
    register(admin, "admin")
    token = create_invite(admin)
    c1 = make_client(app)
    assert register(c1, "primo", invite=token)[0].status_code == 200
    c2 = make_client(app)
    assert register(c2, "secondo", invite=token)[0].status_code == 403


def test_open_registration(app):
    admin = make_client(app)
    register(admin, "admin")
    admin.post("/admin/settings", data={"csrf": csrf_of(admin), "mode": "open"})
    c = make_client(app)
    assert register(c, "libero")[0].status_code == 200
    assert c.get("/admin").status_code == 403  # not admin


def test_login_logout_and_bad_password(app):
    c = make_client(app)
    register(c, "admin")
    c.post("/logout")
    assert c.get("/dashboard", follow_redirects=False).status_code == 303
    assert c.post("/login", data={"username": "admin", "password": "sbagliata!!"}).status_code == 400
    r = c.post("/login", data={"username": "ADMIN", "password": PASSWORD, "next": "/receipts"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/receipts"


def test_open_redirect_blocked(app):
    c = make_client(app)
    register(c, "admin")
    c.post("/logout")
    r = c.post("/login", data={"username": "admin", "password": PASSWORD, "next": "//evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


def test_lockout(app, settings):
    c = make_client(app)
    register(c, "admin")
    c.post("/logout")
    for _ in range(settings.login_max_failures):
        c.post("/login", data={"username": "admin", "password": "sbagliata!!"})
    # Even the right password is refused while locked.
    assert c.post("/login", data={"username": "admin", "password": PASSWORD}).status_code == 400


def test_csrf_required(client):
    register(client, "admin")
    r = client.post("/account/profile", data={"full_name": "Mario"})
    assert r.status_code == 403
    r = client.post("/account/profile", data={"full_name": "Mario", "csrf": "nope"})
    assert r.status_code == 403


def test_cross_site_post_rejected(client):
    register(client, "admin")
    r = client.post("/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/dashboard").status_code == 200  # still logged in


def test_security_headers(client):
    r = client.get("/login")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_manual_receipt_crud_and_exports(client):
    register(client, "admin")
    csrf = csrf_of(client)
    r = client.post(
        "/receipts/manual",
        data={"csrf": csrf, "date": "2025-04-02", "amount": "180,00", "category": "cure_dentistiche",
              "payment_method": "tracciabile", "provider_name": "Studio Dentistico Test", "beneficiary": "self",
              "notes": "=SUM(A1:A2)"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    url = r.headers["location"]
    page = client.get(url).text
    assert "Studio Dentistico Test" in page and "180,00" in page

    # Edit: cash payment makes a dental bill non-deductible.
    r = client.post(url, data={"csrf": csrf, "action": "verify", "date": "2025-04-02", "amount": "180,00",
                               "category": "cure_dentistiche", "payment_method": "contanti", "beneficiary": "self",
                               "provider_name": "Studio Dentistico Test", "notes": "=SUM(A1:A2)"},
                      follow_redirects=True)  # fmt: skip
    assert "Non detraibile" in r.text

    # Validation error keeps user input.
    r = client.post(url, data={"csrf": csrf, "action": "verify", "amount": "abc", "provider_name": "Nuovo nome"})
    assert r.status_code == 400 and "Nuovo nome" in r.text

    csv_text = client.get("/export.csv?year=2025").content.decode("utf-8-sig")
    assert "Studio Dentistico Test" in csv_text
    assert "'=SUM(A1:A2)" in csv_text  # formula injection neutralised

    z = zipfile.ZipFile(io.BytesIO(client.get("/export.zip?year=2025").content))
    assert {"spese.csv", "riepilogo.txt"} <= set(z.namelist())

    assert "Studio Dentistico Test" in client.get("/receipts?q=dentistico").text
    assert "Studio Dentistico Test" not in client.get("/receipts?q=farmacia").text

    rid = url.rsplit("/", 1)[-1]
    client.post(f"/receipts/{rid}/delete", data={"csrf": csrf})
    assert client.get(url).status_code == 404


def test_profile_and_family(client):
    register(client, "admin")
    csrf = csrf_of(client)
    assert client.post("/account/profile", data={"csrf": csrf, "full_name": "Mario Rossi", "tax_code": "XXX"}).status_code == 400
    client.post("/account/profile", data={"csrf": csrf, "full_name": "Mario Rossi", "tax_code": "rssmra80a01h501u"})
    client.post("/account/family", data={"csrf": csrf, "name": "Luca", "tax_code": "RSSLCU12T10H501I", "relation": "figlio", "dependent": "on"})
    page = client.get("/account").text
    assert "RSSMRA80A01H501U" in page and "Luca" in page and "a carico" in page


@needs_tesseract
def test_upload_photo_and_review(client):
    register(client, "admin")
    csrf = csrf_of(client)
    client.post("/account/profile", data={"csrf": csrf, "full_name": "Mario Rossi", "tax_code": "RSSMRA80A01H501U"})
    jpg = synth.photo_of(synth.render_receipt(S.PHARMACY_ELECTRONIC))
    r = client.post("/receipts/upload", data={"csrf": csrf}, files=[("files", ("s.jpg", jpg, "image/jpeg"))], follow_redirects=False)
    url = r.headers["location"]
    page = client.get(url).text
    assert "Controlla i dati" in page
    assert 'value="2025-03-09"' in page and 'value="23,40"' in page
    rid = url.rsplit("/", 1)[-1]
    img = client.get(f"/receipts/{rid}/file/scan")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    # Same photo again -> duplicate warning.
    r = client.post("/receipts/upload", data={"csrf": csrf}, files=[("files", ("s.jpg", jpg, "image/jpeg"))], follow_redirects=True)
    assert "Possibile duplicato" in r.text

    # Multi-upload with one bad file.
    r = client.post(
        "/receipts/upload",
        data={"csrf": csrf},
        files=[("files", ("a.jpg", jpg, "image/jpeg")), ("files", ("bad.jpg", b"garbage", "image/jpeg"))],
        follow_redirects=True,
    )
    assert "bad.jpg" in r.text

    dash = client.get("/dashboard?year=2025").text
    assert "bozze" in dash or "da rivedere" in dash


def test_upload_rejects_oversize(client, settings):
    register(client, "admin")
    settings.max_upload_mb = 1
    r = client.post("/receipts/upload", data={"csrf": csrf_of(client)},
                    files=[("files", ("big.jpg", b"\xff" * (2 * 1024 * 1024), "image/jpeg"))], follow_redirects=True)  # fmt: skip
    assert "troppo grande" in r.text


def test_change_password_keeps_data_and_logs_out_others(app):
    c = make_client(app)
    register(c, "admin")
    other = make_client(app)
    other.post("/login", data={"username": "admin", "password": PASSWORD})
    assert other.get("/dashboard").status_code == 200
    csrf = csrf_of(c)
    c.post("/receipts/manual", data={"csrf": csrf, "date": "2025-01-01", "amount": "10", "category": "farmaci", "provider_name": "Farmacia X"})
    r = c.post("/account/password", data={"csrf": csrf, "current_password": PASSWORD, "new_password": "nuova-password-1", "new_password2": "nuova-password-1"})
    assert r.status_code in (200, 303)
    assert other.get("/dashboard", follow_redirects=False).status_code == 303
    c.post("/logout")
    assert c.post("/login", data={"username": "admin", "password": PASSWORD}).status_code == 400
    c.post("/login", data={"username": "admin", "password": "nuova-password-1"})
    assert "Farmacia X" in c.get("/receipts").text


def test_recovery_flow(app):
    c = make_client(app)
    _, code = register(c, "admin")
    csrf = csrf_of(c)
    c.post("/receipts/manual", data={"csrf": csrf, "date": "2025-01-01", "amount": "10", "category": "farmaci", "provider_name": "Farmacia Y"})

    fresh = make_client(app)
    r = fresh.post("/recover", data={"username": "admin", "recovery_code": "0000-0000-0000-0000-0000-0000", "password": "x" * 12, "password2": "x" * 12})
    assert r.status_code == 400
    r = fresh.post("/recover", data={"username": "admin", "recovery_code": code.lower().replace("-", " "), "password": "ripristinata-1", "password2": "ripristinata-1"})
    assert r.status_code == 200
    new_code = r.text.split('id="recovery-code">')[1].split("<")[0].strip()
    assert new_code != code
    assert "Farmacia Y" in fresh.get("/receipts").text
    # Old session revoked, old code no longer valid.
    assert c.get("/dashboard", follow_redirects=False).status_code == 303
    r = make_client(app).post("/recover", data={"username": "admin", "recovery_code": code, "password": "altra-pass-123", "password2": "altra-pass-123"})
    assert r.status_code == 400


def test_delete_own_account_removes_files(app, settings):
    c = make_client(app)
    register(c, "solo")
    csrf = csrf_of(c)
    from app.ocr.preprocess import encode_jpeg
    import numpy as np

    img = encode_jpeg(np.full((200, 200, 3), 255, np.uint8))
    c.post("/receipts/upload", data={"csrf": csrf}, files=[("files", ("x.jpg", img, "image/jpeg"))])
    assert any(settings.files_dir.rglob("*"))
    r = c.post("/account/delete", data={"csrf": csrf, "current_password": PASSWORD, "confirm": "solo"}, follow_redirects=False)
    assert r.status_code == 303
    assert not [p for p in settings.files_dir.rglob("*") if p.is_file()]
    assert c.post("/login", data={"username": "solo", "password": PASSWORD}).status_code == 400
