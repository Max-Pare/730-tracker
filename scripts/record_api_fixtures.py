# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record real API responses as JSON fixtures for the Android unit tests.

The Android tests decode these files, so any change in the server's JSON that
breaks the app fails the Android build. Run from the repository root:

    python scripts/record_api_fixtures.py
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fastapi.testclient import TestClient  # noqa: E402

import receipt_samples as S  # noqa: E402
import synth  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

OUT = ROOT / "android/app/src/test/resources/fixtures"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    s = Settings(data_dir=tmp)
    s.database_url = f"sqlite:///{tmp / 't.db'}"
    s.kdf_memory_kib, s.kdf_time_cost = 1024, 1
    c = TestClient(create_app(s))

    def save(name, resp):
        (OUT / f"{name}.json").write_text(json.dumps(resp.json(), ensure_ascii=False, indent=1))

    save("server_info", c.get("/api/v1/server-info"))
    save("meta", c.get("/api/v1/meta"))
    r = c.post("/api/v1/auth/register", json={"username": "mario", "password": "password-lunga-1", "device_name": "Pixel"})
    token = r.json()["token"]
    d = r.json()
    d["token"], d["recovery_code"] = "SID.SECRET", "ABCD-EFGH-JKMN-PQRS-TVWX-YZ23"
    (OUT / "token.json").write_text(json.dumps(d, indent=1))
    h = {"Authorization": f"Bearer {token}"}
    c.put("/api/v1/me/profile", headers=h, json={"full_name": "Mario Rossi", "tax_code": "RSSMRA80A01H501U"})
    c.post("/api/v1/me/family", headers=h, json={"name": "Luca", "tax_code": "RSSLCU12T10H501I", "relation": "figlio"})
    save("me", c.get("/api/v1/me", headers=h))
    jpg = synth.photo_of(synth.render_receipt(S.PHARMACY_ELECTRONIC))
    files = [("files", ("s.jpg", jpg, "image/jpeg")), ("files", ("x.jpg", b"bad", "image/jpeg"))]
    save("upload", c.post("/api/v1/receipts/upload", headers=h, files=files))
    c.post("/api/v1/receipts", headers=h, json={
        "date": "2025-05-21", "amount_cents": 15200, "category": "visite_specialistiche",
        "payment_method": "tracciabile", "provider_name": "Dott. Verdi", "status": "verificato",
    })  # fmt: skip
    save("receipts", c.get("/api/v1/receipts?year=2025", headers=h))
    save("dashboard", c.get("/api/v1/dashboard?year=2025", headers=h))
    save("sessions", c.get("/api/v1/me/sessions", headers=h))
    save("error_login", c.post("/api/v1/auth/login", json={"username": "mario", "password": "wrong"}))
    save("error_validation", c.post("/api/v1/receipts", headers=h, json={"category": "boh"}))
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main()
