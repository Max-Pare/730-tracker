# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encrypted file storage on disk.

Files are named by a random id (no user, receipt or content hints) and
encrypted with the owner's DEK. The DB row only records ownership so that
access checks and account deletion work without any key.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import StoredFile
from ..security import crypto
from ..security.auth import Principal

_MAGIC = b"T730"


def _path(settings: Settings, file_id: str) -> Path:
    if not file_id.isalnum():
        raise ValueError("bad file id")
    return settings.files_dir / file_id[:2] / file_id


def _aad(file_id: str, user_id: str) -> str:
    return f"file:{file_id}:{user_id}"


def put_file(db: Session, settings: Settings, p: Principal, receipt_id: str, content: bytes, content_type: str) -> str:
    """Encrypt and write ``content``; adds (not commits) the StoredFile row."""
    file_id = crypto.new_id()
    ct = content_type.encode("ascii")[:100]
    plaintext = _MAGIC + bytes([len(ct)]) + ct + content
    blob = crypto.encrypt(p.dek, plaintext, _aad(file_id, p.user.id))
    path = _path(settings, file_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    db.add(StoredFile(id=file_id, user_id=p.user.id, receipt_id=receipt_id))
    return file_id


def get_file(db: Session, settings: Settings, p: Principal, file_id: str) -> tuple[bytes, str] | None:
    row = db.get(StoredFile, file_id)
    if row is None or row.user_id != p.user.id:
        return None
    path = _path(settings, file_id)
    if not path.exists():
        return None
    try:
        plaintext = crypto.decrypt(p.dek, path.read_bytes(), _aad(file_id, p.user.id))
    except crypto.DecryptionError:
        return None
    if plaintext[:4] != _MAGIC:
        return None
    n = plaintext[4]
    return plaintext[5 + n :], plaintext[5 : 5 + n].decode("ascii")


def _unlink(settings: Settings, file_id: str) -> None:
    try:
        _path(settings, file_id).unlink()
    except FileNotFoundError:
        pass


def delete_files(db: Session, settings: Settings, rows: list[StoredFile]) -> None:
    for row in rows:
        _unlink(settings, row.id)
        db.delete(row)


def delete_receipt_files(db: Session, settings: Settings, user_id: str, receipt_id: str, keep: set[str] | None = None) -> None:
    rows = db.scalars(select(StoredFile).where(StoredFile.user_id == user_id, StoredFile.receipt_id == receipt_id)).all()
    delete_files(db, settings, [r for r in rows if not keep or r.id not in keep])


def delete_user_files(db: Session, settings: Settings, user_id: str) -> None:
    rows = db.scalars(select(StoredFile).where(StoredFile.user_id == user_id)).all()
    delete_files(db, settings, list(rows))
