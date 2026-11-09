# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cryptographic primitives for per-user data isolation.

Design
------
* Every user owns a random 256-bit **data-encryption key (DEK)**.
* The DEK is stored only *wrapped* (AES-256-GCM) by:
  - a key derived from the user's password with Argon2id, and
  - a key derived from a one-time **recovery code** shown at sign-up.
* Logging in means unwrapping the DEK: a wrong password simply fails the
  GCM authentication tag, so no separate password hash exists that an
  administrator could overwrite to gain access.
* Each session/API token carries a random secret that never touches the
  database in clear; the DB stores only its SHA-256 and a copy of the DEK
  wrapped with a key derived (HKDF) from that secret.
* All user content is AES-256-GCM encrypted with the DEK, with associated
  data binding each ciphertext to its record and owner.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import unicodedata
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_LEN = 32
NONCE_LEN = 12
FORMAT_V1 = b"\x01"

# Crockford base32 alphabet: no I, L, O, U (avoid confusion when copying by hand).
_RECOVERY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RECOVERY_CODE_CHARS = 24  # 120 bits of entropy


class DecryptionError(Exception):
    """Raised when a ciphertext cannot be authenticated with the given key."""


@dataclass(frozen=True)
class KdfParams:
    time_cost: int
    memory_kib: int
    parallelism: int

    def to_json(self) -> str:
        return json.dumps({"t": self.time_cost, "m": self.memory_kib, "p": self.parallelism})

    @classmethod
    def from_json(cls, raw: str) -> KdfParams:
        d = json.loads(raw)
        return cls(time_cost=int(d["t"]), memory_kib=int(d["m"]), parallelism=int(d["p"]))


def generate_key() -> bytes:
    return os.urandom(KEY_LEN)


def generate_salt() -> bytes:
    return os.urandom(16)


def new_id() -> str:
    """Random, unguessable 128-bit identifier (hex)."""
    return secrets.token_hex(16)


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def normalize_password(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def derive_key(secret: bytes, salt: bytes, params: KdfParams) -> bytes:
    """Argon2id key derivation (password or recovery code -> 256-bit key)."""
    return hash_secret_raw(
        secret=secret,
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def hkdf(secret: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=info).derive(secret)


def encrypt(key: bytes, plaintext: bytes, aad: str) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad.encode("utf-8"))
    return FORMAT_V1 + nonce + ct


def decrypt(key: bytes, blob: bytes, aad: str) -> bytes:
    if not blob or blob[:1] != FORMAT_V1 or len(blob) < 1 + NONCE_LEN + 16:
        raise DecryptionError("unsupported ciphertext format")
    nonce = blob[1 : 1 + NONCE_LEN]
    try:
        return AESGCM(key).decrypt(nonce, blob[1 + NONCE_LEN :], aad.encode("utf-8"))
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc


def encrypt_json(key: bytes, obj: object, aad: str) -> bytes:
    return encrypt(key, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), aad)


def decrypt_json(key: bytes, blob: bytes, aad: str):
    return json.loads(decrypt(key, blob, aad).decode("utf-8"))


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def constant_time_eq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


# --- recovery codes --------------------------------------------------------


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_CHARS))
    return "-".join(raw[i : i + 4] for i in range(0, RECOVERY_CODE_CHARS, 4))


def normalize_recovery_code(code: str) -> bytes:
    """Canonical form: uppercase, separators removed, common look-alikes mapped."""
    out = []
    for ch in code.upper():
        if ch in "- \t\n":
            continue
        ch = {"O": "0", "I": "1", "L": "1", "U": "V"}.get(ch, ch)
        out.append(ch)
    return "".join(out).encode("ascii", errors="ignore")


# --- key wrapping helpers -------------------------------------------------


def wrap_dek(wrapping_key: bytes, dek: bytes, aad: str) -> bytes:
    return encrypt(wrapping_key, dek, aad)


def unwrap_dek(wrapping_key: bytes, wrapped: bytes, aad: str) -> bytes:
    dek = decrypt(wrapping_key, wrapped, aad)
    if len(dek) != KEY_LEN:
        raise DecryptionError("bad key length")
    return dek
