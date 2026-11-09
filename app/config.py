# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runtime configuration, read from environment variables (prefix ``TRACKER_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"TRACKER_{name}", default)


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")).resolve())
    database_url: str = ""
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "730 Tracker"))
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 20))
    max_files_per_upload: int = field(default_factory=lambda: _env_int("MAX_FILES_PER_UPLOAD", 20))
    web_session_idle_hours: int = field(default_factory=lambda: _env_int("WEB_SESSION_IDLE_HOURS", 12))
    web_session_max_days: int = field(default_factory=lambda: _env_int("WEB_SESSION_MAX_DAYS", 30))
    api_token_idle_days: int = field(default_factory=lambda: _env_int("API_TOKEN_IDLE_DAYS", 30))
    api_token_max_days: int = field(default_factory=lambda: _env_int("API_TOKEN_MAX_DAYS", 365))
    invite_valid_days: int = field(default_factory=lambda: _env_int("INVITE_VALID_DAYS", 7))
    # Argon2id parameters used to derive each user's key-encryption key.
    kdf_time_cost: int = field(default_factory=lambda: _env_int("KDF_TIME_COST", 3))
    kdf_memory_kib: int = field(default_factory=lambda: _env_int("KDF_MEMORY_KIB", 64 * 1024))
    kdf_parallelism: int = field(default_factory=lambda: _env_int("KDF_PARALLELISM", 1))
    login_max_failures: int = field(default_factory=lambda: _env_int("LOGIN_MAX_FAILURES", 5))
    login_lockout_minutes: int = field(default_factory=lambda: _env_int("LOGIN_LOCKOUT_MINUTES", 15))
    ocr_lang: str = field(default_factory=lambda: _env("OCR_LANG", "ita+eng"))
    tesseract_cmd: str = field(default_factory=lambda: _env("TESSERACT_CMD", ""))
    # Force the Secure cookie flag even if the request looks like plain http
    # (useful behind a TLS-terminating proxy that does not send X-Forwarded-Proto).
    force_secure_cookies: bool = field(default_factory=lambda: _env_bool("FORCE_SECURE_COOKIES", False))

    def __post_init__(self) -> None:
        if not self.database_url:
            self.database_url = _env("DATABASE_URL", f"sqlite:///{self.data_dir / 'tracker.db'}")

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
