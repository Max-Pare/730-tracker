# SPDX-License-Identifier: AGPL-3.0-or-later
"""The core promise: users are fully isolated, and admins cannot read anyone's data."""

import sqlite3

import numpy as np
from conftest import PASSWORD, csrf_of, make_client
from sqlalchemy import select

from app.models import User
from app.ocr.preprocess import encode_jpeg
from app.security import auth

SECRET_PROVIDER = "Clinica Riservatissima Alfa"
SECRET_CF = "BNCLRA85M41F205C"


def _add_receipt(client, provider=SECRET_PROVIDER):
    csrf = csrf_of(client)
    r = client.post(
        "/receipts/manual",
        data={"csrf": csrf, "date": "2025-06-01", "amount": "321,09", "category": "visite_specialistiche",
              "payment_method": "tracciabile", "provider_name": provider, "patient_tax_code": SECRET_CF},
        follow_redirects=False,
    )  # fmt: skip
    rid = r.headers["location"].rsplit("/", 1)[-1]
    img = encode_jpeg(np.full((300, 300, 3), 200, np.uint8))
    r2 = client.post("/receipts/upload", data={"csrf": csrf}, files=[("files", ("doc.jpg", img, "image/jpeg"))], follow_redirects=False)
    img_rid = r2.headers["location"].rsplit("/", 1)[-1]
    return rid, img_rid


def test_users_cannot_see_each_other(two_users):
    admin, alice, bob = two_users
    rid, img_rid = _add_receipt(alice)
    for c in (bob, admin):
        assert c.get(f"/receipts/{rid}").status_code == 404
        assert c.get(f"/receipts/{img_rid}/file/original").status_code == 404
        assert c.post(f"/receipts/{rid}", data={"csrf": csrf_of(c), "amount": "1"}).status_code == 404
        assert c.post(f"/receipts/{rid}/delete", data={"csrf": csrf_of(c)}).status_code == 404
        assert SECRET_PROVIDER not in c.get("/receipts").text
        assert SECRET_PROVIDER not in c.get("/export.csv").content.decode("utf-8-sig")
        assert SECRET_PROVIDER not in c.get("/dashboard?year=2025").text
    # Alice still has everything.
    assert SECRET_PROVIDER in alice.get(f"/receipts/{rid}").text


def test_admin_page_reveals_no_user_content(two_users):
    admin, alice, _ = two_users
    _add_receipt(alice)
    page = admin.get("/admin").text
    assert "alice" in page  # usernames are visible to manage accounts…
    assert SECRET_PROVIDER not in page and "321,09" not in page  # …content is not


def test_nothing_readable_at_rest(two_users, settings):
    _, alice, _ = two_users
    alice.post("/account/profile", data={"csrf": csrf_of(alice), "full_name": "Alice Segreta", "tax_code": SECRET_CF})
    _add_receipt(alice)
    db_path = settings.database_url.removeprefix("sqlite:///")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA wal_checkpoint(FULL)")
    con.close()
    blobs = b""
    for p in [db_path, db_path + "-wal"]:
        try:
            blobs += open(p, "rb").read()
        except FileNotFoundError:
            pass
    for p in settings.files_dir.rglob("*"):
        if p.is_file():
            blobs += p.read_bytes()
    for needle in (SECRET_PROVIDER, SECRET_CF, "Alice Segreta", "321"):
        assert needle.encode() not in blobs, needle
    assert b"\xff\xd8\xff" not in b"".join(p.read_bytes()[:3] for p in settings.files_dir.rglob("*") if p.is_file())


def test_admin_cannot_hijack_account_by_swapping_keys(two_users, app, settings):
    """Even with direct DB write access, copying the admin's key material onto
    Alice's row does not unlock Alice's data (ciphertexts are bound to user ids)."""
    _, alice, _ = two_users
    _add_receipt(alice)
    with app.state.session_factory() as db:
        admin_u = db.scalar(select(User).where(User.username == "admin"))
        alice_u = db.scalar(select(User).where(User.username == "alice"))
        alice_u.password_salt = admin_u.password_salt
        alice_u.password_wrapped_dek = admin_u.password_wrapped_dek
        alice_u.kdf_params = admin_u.kdf_params
        db.commit()
        try:
            auth.authenticate(db, settings, "alice", PASSWORD)
            raise AssertionError("login should fail")
        except auth.AuthError:
            pass


def test_admin_disable_and_delete(two_users, settings):
    admin, alice, _ = two_users
    _add_receipt(alice)
    with_files = [p for p in settings.files_dir.rglob("*") if p.is_file()]
    assert with_files
    html = admin.get("/admin").text
    import re

    alice_id = re.search(r'/admin/users/([0-9a-f]+)/toggle', html).group(1)
    csrf = csrf_of(admin)
    admin.post(f"/admin/users/{alice_id}/toggle", data={"csrf": csrf})
    assert alice.get("/dashboard", follow_redirects=False).status_code == 303  # session revoked
    r = make_client(admin.app).post("/login", data={"username": "alice", "password": PASSWORD})
    assert "disabilitato" in r.text

    # Deletion needs the username typed in.
    admin.post(f"/admin/users/{alice_id}/delete", data={"csrf": csrf, "confirm": "wrong"})
    assert "alice" in admin.get("/admin").text
    admin.post(f"/admin/users/{alice_id}/delete", data={"csrf": csrf, "confirm": "alice"})
    assert ">alice<" not in admin.get("/admin").text
    assert not [p for p in settings.files_dir.rglob("*") if p.is_file()]


def test_expired_sessions_are_purged_on_new_login(app, settings):
    from datetime import timedelta

    from app.models import AuthSession, utcnow

    c = make_client(app)
    from conftest import register

    register(c, "solo")
    with app.state.session_factory() as db:
        for s in db.scalars(select(AuthSession)).all():
            s.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    make_client(app).post("/login", data={"username": "solo", "password": PASSWORD})
    with app.state.session_factory() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 1  # only the new one
