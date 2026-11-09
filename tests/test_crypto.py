# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from app.security import crypto


def test_roundtrip_and_aad_binding():
    key = crypto.generate_key()
    blob = crypto.encrypt(key, b"segreto", "receipt:1:u1")
    assert crypto.decrypt(key, blob, "receipt:1:u1") == b"segreto"
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(key, blob, "receipt:2:u1")  # moved to another record
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(crypto.generate_key(), blob, "receipt:1:u1")


def test_nonce_uniqueness():
    key = crypto.generate_key()
    assert crypto.encrypt(key, b"x", "a") != crypto.encrypt(key, b"x", "a")


def test_kdf_deterministic():
    p = crypto.KdfParams(1, 1024, 1)
    salt = crypto.generate_salt()
    assert crypto.derive_key(b"pw", salt, p) == crypto.derive_key(b"pw", salt, p)
    assert crypto.derive_key(b"pw", salt, p) != crypto.derive_key(b"pw2", salt, p)


def test_recovery_code_normalization():
    code = crypto.generate_recovery_code()
    assert len(code.replace("-", "")) == crypto.RECOVERY_CODE_CHARS
    assert crypto.normalize_recovery_code(code.lower().replace("-", " ")) == crypto.normalize_recovery_code(code)
    assert crypto.normalize_recovery_code("0O1IL") == b"00111"


def test_json_helpers():
    key = crypto.generate_key()
    blob = crypto.encrypt_json(key, {"a": "è"}, "x")
    assert crypto.decrypt_json(key, blob, "x") == {"a": "è"}
