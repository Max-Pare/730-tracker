# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounts, login, sessions/API tokens, password change and recovery."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AuthSession, User, utcnow
from . import crypto

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 256

GENERIC_LOGIN_ERROR = "Nome utente o password non validi (oppure account temporaneamente bloccato)."


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _pw_aad(user_id: str) -> str:
    return f"dek:password:{user_id}"


def _rc_aad(user_id: str) -> str:
    return f"dek:recovery:{user_id}"


def _session_aad(session_id: str, user_id: str) -> str:
    return f"dek:session:{session_id}:{user_id}"


def session_label_aad(session_id: str, user_id: str) -> str:
    return f"session-label:{session_id}:{user_id}"


def kdf_params(settings: Settings) -> crypto.KdfParams:
    return crypto.KdfParams(settings.kdf_time_cost, settings.kdf_memory_kib, settings.kdf_parallelism)


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str:
    u = normalize_username(username)
    if not USERNAME_RE.match(u):
        raise AuthError(
            "Il nome utente deve avere 3-32 caratteri: lettere minuscole, numeri, punto, trattino o underscore.",
            "invalid_username",
        )
    return u


def validate_password(password: str, username: str | None = None) -> None:
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"La password deve avere almeno {MIN_PASSWORD_LEN} caratteri.", "weak_password")
    if len(password) > MAX_PASSWORD_LEN:
        raise AuthError("Password troppo lunga.", "weak_password")
    if username and password.strip().lower() == username.lower():
        raise AuthError("La password non può coincidere con il nome utente.", "weak_password")


# --------------------------------------------------------------------------- users


@dataclass
class NewAccount:
    user: User
    dek: bytes
    recovery_code: str


def create_user(db: Session, settings: Settings, username: str, password: str, role: str = "user") -> NewAccount:
    username = validate_username(username)
    validate_password(password, username)
    if db.scalar(select(User.id).where(User.username == username)):
        raise AuthError("Nome utente già in uso.", "username_taken")

    params = kdf_params(settings)
    user_id = crypto.new_id()
    dek = crypto.generate_key()
    pw_salt = crypto.generate_salt()
    rc_salt = crypto.generate_salt()
    recovery_code = crypto.generate_recovery_code()

    pw_key = crypto.derive_key(crypto.normalize_password(password), pw_salt, params)
    rc_key = crypto.derive_key(crypto.normalize_recovery_code(recovery_code), rc_salt, params)

    user = User(
        id=user_id,
        username=username,
        role=role,
        is_active=True,
        kdf_params=params.to_json(),
        password_salt=pw_salt,
        password_wrapped_dek=crypto.wrap_dek(pw_key, dek, _pw_aad(user_id)),
        recovery_salt=rc_salt,
        recovery_wrapped_dek=crypto.wrap_dek(rc_key, dek, _rc_aad(user_id)),
    )
    db.add(user)
    db.commit()
    return NewAccount(user=user, dek=dek, recovery_code=recovery_code)


def _unwrap_with_password(user: User, password: str) -> bytes | None:
    params = crypto.KdfParams.from_json(user.kdf_params)
    key = crypto.derive_key(crypto.normalize_password(password), user.password_salt, params)
    try:
        return crypto.unwrap_dek(key, user.password_wrapped_dek, _pw_aad(user.id))
    except crypto.DecryptionError:
        return None


def _dummy_kdf(settings: Settings) -> None:
    """Spend the same time as a real login so unknown usernames are not revealed by timing."""
    crypto.derive_key(secrets.token_bytes(16), crypto.generate_salt(), kdf_params(settings))


def _register_failure(db: Session, settings: Settings, user: User) -> None:
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= settings.login_max_failures:
        user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
        user.failed_logins = 0
    db.commit()


def _is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def authenticate(db: Session, settings: Settings, username: str, password: str) -> tuple[User, bytes]:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None or not password or len(password) > MAX_PASSWORD_LEN:
        _dummy_kdf(settings)
        raise AuthError(GENERIC_LOGIN_ERROR, "invalid_credentials")
    if _is_locked(user):
        _dummy_kdf(settings)
        raise AuthError(GENERIC_LOGIN_ERROR, "invalid_credentials")
    dek = _unwrap_with_password(user, password)
    if dek is None:
        _register_failure(db, settings, user)
        raise AuthError(GENERIC_LOGIN_ERROR, "invalid_credentials")
    if not user.is_active:
        raise AuthError("Account disabilitato. Contatta l'amministratore.", "account_disabled")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    db.commit()
    return user, dek


def verify_password(user: User, password: str) -> bytes | None:
    """Return the DEK if ``password`` is the user's current password."""
    if not password or len(password) > MAX_PASSWORD_LEN:
        return None
    return _unwrap_with_password(user, password)


def change_password(db: Session, settings: Settings, user: User, current_password: str, new_password: str) -> None:
    dek = verify_password(user, current_password)
    if dek is None:
        raise AuthError("La password attuale non è corretta.", "invalid_credentials")
    validate_password(new_password, user.username)
    _set_password(settings, user, dek, new_password)
    db.commit()


def _set_password(settings: Settings, user: User, dek: bytes, new_password: str) -> None:
    params = crypto.KdfParams.from_json(user.kdf_params)
    salt = crypto.generate_salt()
    key = crypto.derive_key(crypto.normalize_password(new_password), salt, params)
    user.password_salt = salt
    user.password_wrapped_dek = crypto.wrap_dek(key, dek, _pw_aad(user.id))


def regenerate_recovery_code(db: Session, user: User, dek: bytes) -> str:
    params = crypto.KdfParams.from_json(user.kdf_params)
    code = crypto.generate_recovery_code()
    salt = crypto.generate_salt()
    key = crypto.derive_key(crypto.normalize_recovery_code(code), salt, params)
    user.recovery_salt = salt
    user.recovery_wrapped_dek = crypto.wrap_dek(key, dek, _rc_aad(user.id))
    db.commit()
    return code


def recover_account(
    db: Session, settings: Settings, username: str, recovery_code: str, new_password: str
) -> tuple[User, bytes, str]:
    """Reset the password with the recovery code. Returns (user, dek, new recovery code)."""
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    generic = AuthError("Nome utente o codice di recupero non validi.", "invalid_recovery")
    if user is None or _is_locked(user):
        _dummy_kdf(settings)
        raise generic
    params = crypto.KdfParams.from_json(user.kdf_params)
    key = crypto.derive_key(crypto.normalize_recovery_code(recovery_code), user.recovery_salt, params)
    try:
        dek = crypto.unwrap_dek(key, user.recovery_wrapped_dek, _rc_aad(user.id))
    except crypto.DecryptionError:
        _register_failure(db, settings, user)
        raise generic from None
    validate_password(new_password, user.username)
    if not user.is_active:
        raise AuthError("Account disabilitato. Contatta l'amministratore.", "account_disabled")
    _set_password(settings, user, dek, new_password)
    # Invalidate every existing session: whoever had the old password is out.
    for s in list(user.sessions):
        db.delete(s)
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    new_code = regenerate_recovery_code(db, user, dek)
    return user, dek, new_code


# --------------------------------------------------------------------------- sessions


@dataclass
class Principal:
    user: User
    dek: bytes
    session: AuthSession
    secret: bytes

    @property
    def csrf_token(self) -> str:
        return crypto.b64e(crypto.hmac_sha256(self.secret, b"csrf"))


def _ttl(settings: Settings, kind: str) -> tuple[timedelta, timedelta]:
    if kind == "api":
        return timedelta(days=settings.api_token_idle_days), timedelta(days=settings.api_token_max_days)
    return timedelta(hours=settings.web_session_idle_hours), timedelta(days=settings.web_session_max_days)


def create_session(
    db: Session, settings: Settings, user: User, dek: bytes, kind: str, label: str | None = None
) -> tuple[str, AuthSession]:
    assert kind in ("web", "api")
    purge_expired_sessions(db)
    sid = crypto.new_id()
    secret = secrets.token_bytes(32)
    idle, _ = _ttl(settings, kind)
    now = utcnow()
    sess = AuthSession(
        id=sid,
        user_id=user.id,
        kind=kind,
        secret_hash=crypto.sha256(secret),
        wrapped_dek=crypto.wrap_dek(crypto.hkdf(secret, b"730tracker-session-dek"), dek, _session_aad(sid, user.id)),
        label_blob=crypto.encrypt(dek, label[:120].encode("utf-8"), session_label_aad(sid, user.id)) if label else None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + idle,
    )
    db.add(sess)
    db.commit()
    return f"{sid}.{crypto.b64e(secret)}", sess


def resolve_token(db: Session, settings: Settings, token: str | None, kind: str) -> Principal | None:
    if not token or "." not in token or len(token) > 200:
        return None
    sid, _, secret_b64 = token.partition(".")
    try:
        secret = crypto.b64d(secret_b64)
    except (ValueError, TypeError):
        return None
    sess = db.get(AuthSession, sid)
    if sess is None or sess.kind != kind:
        return None
    if not crypto.constant_time_eq(sess.secret_hash, crypto.sha256(secret)):
        return None
    now = utcnow()
    idle, max_age = _ttl(settings, kind)
    if sess.expires_at <= now or sess.created_at + max_age <= now:
        db.delete(sess)
        db.commit()
        return None
    user = sess.user
    if user is None or not user.is_active:
        return None
    try:
        dek = crypto.unwrap_dek(
            crypto.hkdf(secret, b"730tracker-session-dek"), sess.wrapped_dek, _session_aad(sess.id, user.id)
        )
    except crypto.DecryptionError:
        return None
    if (now - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = now
        sess.expires_at = now + idle
        db.commit()
    return Principal(user=user, dek=dek, session=sess, secret=secret)


def revoke_session(db: Session, sess: AuthSession) -> None:
    db.delete(sess)
    db.commit()


def session_label(principal_dek: bytes, sess: AuthSession) -> str | None:
    if not sess.label_blob:
        return None
    try:
        return crypto.decrypt(principal_dek, sess.label_blob, session_label_aad(sess.id, sess.user_id)).decode("utf-8")
    except crypto.DecryptionError:
        return None


def purge_expired_sessions(db: Session) -> int:
    """Delete idle-expired sessions (not committed: callers commit). Runs on every new session."""
    return db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow())).rowcount or 0
