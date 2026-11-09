# 730 Tracker

Self-hosted archive of the Italian **730** deductible expenses (*spese sanitarie*, and veterinary ones).
Take a photo of a medical receipt, the server reads it with **OpenCV + Tesseract OCR**, you check
the extracted fields, and the document is archived **encrypted**. A dashboard shows the totals
and the estimated 19% tax deduction for each year.

- **Web app**: mobile-first, works on iPhone/iPad (Safari → *Aggiungi alla schermata Home*) and desktop.
- **Android app**: native Kotlin/Jetpack Compose app in [`android/`](android/).
- **Per-user encryption**: every account's data is encrypted with a key that only that user can
  unlock. The administrator manages accounts but **cannot read anyone's documents**.
- Italian UI, free software under **AGPL-3.0-or-later**.

## Features

- **Receipt capture**: camera, gallery, drag and drop, PDF invoices, or sharing from other Android apps.
  Upload several documents at once.
- **OCR pipeline** ([`app/ocr/`](app/ocr/)):
  - finds the receipt in the photo (edges/contours, with a brightness-based fallback),
  - corrects perspective, removes shadows (illumination normalisation), denoises, deskews,
    and detects 90°/180° rotation (Tesseract OSD),
  - runs Tesseract (`ita+eng`) on two image variants and keeps the better one.
  - PDFs use their text layer when they have one, otherwise they are rendered and OCR'd.
- **Field extraction** for Italian receipts ([`app/ocr/parser.py`](app/ocr/parser.py)): date,
  total (*TOTALE COMPLESSIVO*, *IMPORTO PAGATO*…), provider name, P.IVA (checksum-validated),
  codice fiscale (checksum-validated; OCR mix-ups such as `O/0` and `l/1` are repaired), document
  number, payment method (*contante 0,00 / elettronico 14,50* is read correctly), category, and
  line items. Non-deductible items such as *parafarmaci*, cosmetics and supplements reduce the
  deductible amount.
  Each field has a confidence score, and uncertain fields are highlighted for review.
- **730 rules** ([`app/services/tax.py`](app/services/tax.py)):
  - 19% on medical expenses above the € 129,11 *franchigia*;
  - veterinary expenses capped at € 550;
  - traceable payment required since 2020, except for medicines, medical devices and
    public/SSN-accredited providers;
  - expenses of family members who are not *a carico* are excluded;
  - a hint appears when expenses exceed the € 15.493,71 threshold for paying in instalments.
- **Archive**: full-text search (including OCR text), filters by year, category, person, status
  and outcome; duplicate detection; re-run OCR on a stored document.
- **Dashboard**: estimated deduction, totals, franchigia progress, monthly/category/person charts,
  and a list of issues to check (cash payments, missing codice fiscale, drafts…).
- **Export** for your CAF/commercialista: CSV (Excel-friendly, `;` separator, formula-injection safe)
  or a ZIP with the CSV, a text summary and every document.
- **Family**: add family members with their codice fiscale; receipts are attributed automatically
  when their codice fiscale is printed on them (*scontrino parlante*).

> The figures are **estimates** to help you prepare the return. Always check them against the
> *730 precompilato* and with your CAF or accountant.

## Security model

| What | How |
|---|---|
| Data key | Each user has a random 256-bit **DEK**. All receipts, images, OCR text and profile data are encrypted with it (AES-256-GCM; associated data binds every ciphertext to its record and owner). |
| Password | The DEK is wrapped with a key derived from the password (**Argon2id**, 64 MiB). Logging in *is* unwrapping the DEK, so no password hash exists that someone could swap to get in. |
| Recovery | At sign-up the user gets a one-time **recovery code** (120 bits) that wraps a second copy of the DEK. Lost password **and** lost code means the data is gone, by design. |
| Sessions | Browser cookie or app token = `id.secret`. The DB stores only `sha256(secret)` and a copy of the DEK wrapped with a key derived from the secret, which only the client holds. |
| Admin | Can invite, disable, promote or delete accounts. Cannot impersonate users, reset their passwords or view their data. The admin pages show no content and no counts. |
| At rest | Only ids, ownership and timestamps are in clear. Files are named by random ids. Photos are re-encoded, which strips EXIF/GPS metadata. |
| Web | Strict CSP (no inline scripts, no CDNs), CSRF tokens plus an Origin check, `SameSite` and `HttpOnly` cookies, `no-store` caching, login throttling and lockout. |

**Threat model.** This protects against other users, the admin account, and anyone holding the
database, the disk or the backups. It cannot protect against an operator who **modifies the server
code** to capture passwords at login. No server-side OCR design can, because the server must see the
image to read it. Run it on a machine you trust.

What an operator *can* see: usernames, the number of documents per user, and timestamps.

## Quick start (Docker)

```bash
docker compose up -d --build
```

Open <http://localhost:8000>. The **first account you create becomes the administrator**. By default
new accounts need an **invite**: go to *Amministrazione → Crea invito* and send the link. You can
also open registration to everyone.

To use it from your phone outside your home network, put it behind HTTPS (Caddy, nginx, Traefik,
Tailscale…) and set `FORWARDED_ALLOW_IPS` so the app knows requests arrived over HTTPS.

**Backups**: back up the `tracker-data` volume (`/data`). It holds `tracker.db` and `files/`. Both
are encrypted per user, so backups are safe to store off-site.

## Development

```bash
sudo apt install tesseract-ocr tesseract-ocr-ita   # or: brew install tesseract tesseract-lang
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:create_app --factory --reload
python -m pytest
```

The Python test suite (78 tests) covers the parser on realistic receipts, end-to-end OCR on synthetic phone
photos, the 730 math, the web and API flows, and isolation. Isolation tests check that other users
and admins get 404 everywhere, that nothing is readable in the raw DB or files, and that swapped key
material cannot unlock data.

## Android app

[`android/`](android/) is a Kotlin + Jetpack Compose (Material 3) app with no Google Play Services
dependency.

- First run: enter your server address. `http://` is allowed for home networks, with a warning.
  User-installed CAs are trusted, for servers with a private certificate.
- Login, registration with an invite code, recovery, and the recovery-code screen.
- Dashboard, archive with search and filters, capture (system camera, photo picker, PDFs, *Share to*
  730 Tracker), review and edit with uncertain fields highlighted, account, family, devices, and
  CSV/ZIP export through the share sheet.
- The API token is encrypted with an Android Keystore key. Images are never cached on disk.
  App data is excluded from backups.

Build:

```bash
cd android
./gradlew assembleDebug        # → app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest lintDebug
```

The Android tests decode **real responses recorded from the server**
(`python scripts/record_api_fixtures.py`), so any change to the API contract fails the build.
A Robolectric UI test drives the real app against those recordings: server setup, login,
dashboard, archive, and review of an OCR draft. It saves screenshots to
`app/build/screenshots/`. CI uploads a debug APK for every push.

## JSON API

Interactive docs at `/api/docs`. Authenticate with `POST /api/v1/auth/login`, then send
`Authorization: Bearer <token>`. Main endpoints: `/api/v1/dashboard`, `/api/v1/receipts`
(list, create, read, update, delete), `/api/v1/receipts/upload` (multipart, several files),
`/api/v1/receipts/{id}/files/{scan|original}`, `/api/v1/me` (profile, family, password, sessions),
and `/api/v1/export.{csv,zip}`.

## Configuration

Environment variables (all optional):

| Variable | Default | |
|---|---|---|
| `TRACKER_DATA_DIR` | `./data` | Database and encrypted files |
| `TRACKER_DATABASE_URL` | SQLite in data dir | SQLAlchemy URL |
| `TRACKER_MAX_UPLOAD_MB` | `20` | Per file |
| `TRACKER_MAX_FILES_PER_UPLOAD` | `20` | |
| `TRACKER_WEB_SESSION_IDLE_HOURS` | `12` | Browser sessions (max 30 days) |
| `TRACKER_API_TOKEN_IDLE_DAYS` | `30` | App tokens (max 365 days) |
| `TRACKER_INVITE_VALID_DAYS` | `7` | |
| `TRACKER_KDF_MEMORY_KIB` / `_TIME_COST` | `65536` / `3` | Argon2id cost for new keys |
| `TRACKER_LOGIN_MAX_FAILURES` / `_LOCKOUT_MINUTES` | `5` / `15` | |
| `TRACKER_OCR_LANG` | `ita+eng` | Tesseract languages |
| `TRACKER_TESSERACT_CMD` | (PATH) | Custom tesseract binary |
| `TRACKER_FORCE_SECURE_COOKIES` | `0` | Force `Secure` cookies behind a TLS proxy |

## License

Copyright © the 730 Tracker contributors.

This program is free software: you can redistribute it and/or modify it under the terms of the
**GNU Affero General Public License** as published by the Free Software Foundation, either version 3
of the License, or (at your option) any later version. If you run a modified version as a network
service, you must offer its source code to its users (AGPL §13). See [LICENSE](LICENSE).

Third-party components and their (compatible, permissive) licenses are listed in
[THIRD_PARTY.md](THIRD_PARTY.md).
