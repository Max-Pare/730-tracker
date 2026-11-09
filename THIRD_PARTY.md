# Third-party components

730 Tracker is licensed under **AGPL-3.0-or-later**. Every dependency below has a permissive
license that can be combined with the AGPL-3.0 (Apache-2.0 code may be combined with GPLv3/AGPLv3,
but not with GPLv2-only). No proprietary component is required: the Android app does not use
Google Play Services or ML Kit.

## Server (Python)

| Component | License |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| Jinja2 | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| SQLAlchemy | MIT |
| OpenCV (`opencv-python-headless`) | Apache-2.0 (the wheel bundles FFmpeg under LGPL-2.1+) |
| NumPy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| pytesseract | Apache-2.0 |
| Tesseract OCR + `ita`/`eng`/`osd` data (system package) | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| argon2-cffi | MIT |
| pypdf | BSD-3-Clause |
| pypdfium2 (PDFium) | Apache-2.0 OR BSD-3-Clause (PDFium: BSD-3-Clause) |

Development only: pytest (MIT), httpx (BSD-3-Clause).

## Android app

| Component | License |
|---|---|
| Kotlin, kotlinx.coroutines, kotlinx.serialization | Apache-2.0 |
| AndroidX (Core, Activity, Lifecycle, Navigation, DataStore, Compose, Material 3, Material Icons) | Apache-2.0 |
| Retrofit, OkHttp, MockWebServer (tests) | Apache-2.0 |
| Coil | Apache-2.0 |
| JUnit 4 (tests) | EPL-1.0 (test only, not distributed) |
| Robolectric (tests) | MIT (test only, not distributed) |
