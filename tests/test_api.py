# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON API used by the Android app."""

import shutil

import numpy as np
import pytest
from conftest import PASSWORD, create_invite, make_client, register

import receipt_samples as S
import synth
from app.ocr.preprocess import encode_jpeg


def api_login(client, username, password=PASSWORD):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password, "device_name": "Pixel test"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_server_info_and_meta(client):
    info = client.get("/api/v1/server-info").json()
    assert info["needs_setup"] is True and info["api"] == 1
    meta = client.get("/api/v1/meta").json()
    assert any(c["code"] == "farmaci" for c in meta["categories"])


def test_register_via_api_first_user_admin(client):
    r = client.post("/api/v1/auth/register", json={"username": "root", "password": PASSWORD})
    body = r.json()
    assert r.status_code == 200 and body["user"]["role"] == "admin" and body["recovery_code"]
    r = client.post("/api/v1/auth/register", json={"username": "altro", "password": PASSWORD})
    assert r.status_code == 403


def test_auth_required(client):
    assert client.get("/api/v1/receipts").status_code == 401
    assert client.get("/api/v1/receipts", headers={"Authorization": "Bearer abc.def"}).status_code == 401


def test_web_cookie_does_not_work_for_api_and_vice_versa(client):
    register(client, "admin")
    assert client.get("/api/v1/me").status_code == 401  # cookie alone is not an API token
    h = api_login(client, "admin")
    c2 = make_client(client.app)
    token = h["Authorization"].split()[1]
    c2.cookies.set("t730_session", token)
    assert c2.get("/dashboard", follow_redirects=False).status_code == 303


def test_receipt_crud_via_api(client):
    register(client, "admin")
    h = api_login(client, "admin")
    r = client.post("/api/v1/receipts", headers=h, json={
        "date": "2025-02-10", "amount_cents": 4500, "category": "esami_analisi",
        "payment_method": "tracciabile", "provider_name": "Lab API", "status": "verificato",
    })  # fmt: skip
    assert r.status_code == 201
    rec = r.json()
    assert rec["evaluation"]["status"] == "detraibile" and rec["data"]["source"] == "manuale"
    rid = rec["id"]

    r = client.put(f"/api/v1/receipts/{rid}", headers=h, json={**rec["data"], "payment_method": "contanti"})
    assert r.json()["evaluation"]["status"] == "non_detraibile"
    r = client.put(f"/api/v1/receipts/{rid}", headers=h, json={**rec["data"], "category": "boh"})
    assert r.status_code == 422

    page = client.get("/api/v1/receipts?year=2025&q=lab", headers=h).json()
    assert page["total"] == 1 and page["items"][0]["id"] == rid

    dash = client.get("/api/v1/dashboard?year=2025", headers=h).json()
    assert dash["summary"]["receipts_count"] == 1 and 2025 in dash["years"]

    assert client.get("/api/v1/export.csv?year=2025", headers=h).status_code == 200
    assert client.delete(f"/api/v1/receipts/{rid}", headers=h).status_code == 204
    assert client.get(f"/api/v1/receipts/{rid}", headers=h).status_code == 404


def test_api_isolation(app):
    admin = make_client(app)
    register(admin, "admin")
    alice = make_client(app)
    register(alice, "alice", invite=create_invite(admin))
    ha = api_login(alice, "alice")
    hb = api_login(admin, "admin")
    img = encode_jpeg(np.full((200, 200, 3), 230, np.uint8))
    r = alice.post("/api/v1/receipts/upload", headers=ha, files=[("files", ("a.jpg", img, "image/jpeg"))])
    rid = r.json()["created"][0]["id"]
    assert alice.get(f"/api/v1/receipts/{rid}/files/original", headers=ha).status_code == 200
    for path in (f"/api/v1/receipts/{rid}", f"/api/v1/receipts/{rid}/files/original"):
        assert admin.get(path, headers=hb).status_code == 404
    assert admin.delete(f"/api/v1/receipts/{rid}", headers=hb).status_code == 404
    assert admin.get("/api/v1/receipts", headers=hb).json()["total"] == 0


def test_sessions_and_logout(client):
    register(client, "admin")
    h = api_login(client, "admin")
    sessions = client.get("/api/v1/me/sessions", headers=h).json()
    assert any(s["label"] == "Pixel test" and s["current"] for s in sessions)
    web = next(s for s in sessions if s["kind"] == "web")
    assert client.delete(f"/api/v1/me/sessions/{web['id']}", headers=h).status_code == 204
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/api/v1/me", headers=h).status_code == 401


def test_profile_family_via_api(client):
    register(client, "admin")
    h = api_login(client, "admin")
    r = client.put("/api/v1/me/profile", headers=h, json={"full_name": "Mario", "tax_code": "RSSMRA80A01H501U"})
    assert r.status_code == 200
    assert client.put("/api/v1/me/profile", headers=h, json={"tax_code": "XYZ"}).status_code == 422
    prof = client.post("/api/v1/me/family", headers=h, json={"name": "Luca", "relation": "figlio"}).json()
    mid = prof["family"][0]["id"]
    prof = client.put(f"/api/v1/me/family/{mid}", headers=h, json={"name": "Luca R.", "dependent": False}).json()
    assert prof["family"][0]["name"] == "Luca R." and prof["family"][0]["dependent"] is False
    assert client.delete(f"/api/v1/me/family/{mid}", headers=h).json()["family"] == []


def test_recover_and_password_via_api(client):
    r = client.post("/api/v1/auth/register", json={"username": "root", "password": PASSWORD})
    code = r.json()["recovery_code"]
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post("/api/v1/me/password", headers=h, json={"current_password": "wrong", "new_password": "x" * 12}).status_code == 400
    assert client.post("/api/v1/me/password", headers=h, json={"current_password": PASSWORD, "new_password": "nuova-pass-123"}).status_code == 204
    r = client.post("/api/v1/auth/recover", json={"username": "root", "recovery_code": code, "new_password": "ancora-nuova-1"})
    assert r.status_code == 200 and r.json()["recovery_code"] != code
    assert client.get("/api/v1/me", headers=h).status_code == 401  # recovery logs out all devices


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_upload_ocr_via_api(client):
    register(client, "admin")
    h = api_login(client, "admin")
    client.put("/api/v1/me/profile", headers=h, json={"tax_code": "RSSMRA80A01H501U"})
    jpg = synth.photo_of(synth.render_receipt(S.PHARMACY_ELECTRONIC), angle_deg=-4)
    r = client.post("/api/v1/receipts/upload", headers=h, files=[("files", ("s.jpg", jpg, "image/jpeg")), ("files", ("x.jpg", b"bad", "image/jpeg"))])
    body = r.json()
    assert len(body["created"]) == 1 and body["errors"][0]["filename"] == "x.jpg"
    rec = body["created"][0]
    assert rec["data"]["status"] == "bozza"
    assert rec["data"]["amount_cents"] == 2340
    assert rec["data"]["beneficiary"] == "self"
    assert rec["has_scan"] and rec["data"]["ocr"]["field_confidence"]["amount_cents"] > 0.5
    scan = client.get(f"/api/v1/receipts/{rec['id']}/files/scan", headers=h)
    assert scan.headers["content-type"] == "image/jpeg"
    r = client.post(f"/api/v1/receipts/{rec['id']}/reprocess", headers=h)
    assert r.status_code == 200 and r.json()["data"]["amount_cents"] == 2340
