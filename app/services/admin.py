# SPDX-License-Identifier: AGPL-3.0-or-later
"""Instance administration: registration policy, invites, account lifecycle.

Nothing here can read user content: admins never hold another user's key.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AppSetting, Invite, User, utcnow
from ..security import crypto
from . import storage

REGISTRATION_MODES = {
    "open": "Aperta a tutti",
    "invite": "Solo su invito",
    "closed": "Chiusa",
}


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def registration_mode(db: Session) -> str:
    return get_setting(db, "registration_mode", "invite")


def has_users(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


def create_invite(db: Session, settings: Settings, admin: User, note: str | None) -> tuple[str, Invite]:
    token = secrets.token_urlsafe(24)
    inv = Invite(
        id=crypto.new_id(),
        token_hash=crypto.sha256(token.encode()),
        created_by=admin.id,
        expires_at=utcnow() + timedelta(days=settings.invite_valid_days),
        note=(note or "").strip()[:80] or None,
    )
    db.add(inv)
    db.commit()
    return token, inv


def find_valid_invite(db: Session, token: str | None) -> Invite | None:
    if not token or len(token) > 100:
        return None
    inv = db.scalar(select(Invite).where(Invite.token_hash == crypto.sha256(token.encode())))
    if inv is None or inv.used_at is not None or inv.expires_at <= utcnow():
        return None
    return inv


def claim_invite(db: Session, token: str | None) -> str | None:
    """Atomically mark a valid invite as used; returns its id, or None if it was already taken.

    A single conditional UPDATE, so two concurrent registrations cannot both redeem it.
    """
    if not token or len(token) > 100:
        return None
    now = utcnow()
    res = db.execute(
        update(Invite)
        .where(Invite.token_hash == crypto.sha256(token.encode()), Invite.used_at.is_(None), Invite.expires_at > now)
        .values(used_at=now)
    )
    db.commit()
    if res.rowcount != 1:
        return None
    return db.scalar(select(Invite.id).where(Invite.token_hash == crypto.sha256(token.encode())))


def release_invite(db: Session, invite_id: str | None) -> None:
    """Undo claim_invite when the registration then fails (e.g. username taken)."""
    if invite_id:
        db.execute(update(Invite).where(Invite.id == invite_id).values(used_at=None))
        db.commit()


def list_invites(db: Session) -> list[Invite]:
    return list(db.scalars(select(Invite).order_by(Invite.created_at.desc())).all())


def delete_invite(db: Session, invite_id: str) -> None:
    inv = db.get(Invite, invite_id)
    if inv:
        db.delete(inv)
        db.commit()


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)).all())


def active_admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0


def delete_user(db: Session, settings: Settings, user: User) -> None:
    """Delete an account with all its data (encrypted files, receipts, sessions)."""
    storage.delete_user_files(db, settings, user.id)
    db.delete(user)
    db.commit()
