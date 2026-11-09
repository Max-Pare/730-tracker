# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encrypted user profile: own name/codice fiscale and family members."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..ocr.validators import is_valid_cf
from ..security import crypto
from ..security.auth import Principal
from .domain import RELATIONS, _clean_str


def _cf(v):
    s = _clean_str(v, 20)
    if not s:
        return None
    s = s.upper().replace(" ", "")
    if not is_valid_cf(s):
        raise ValueError("Codice fiscale non valido")
    return s


class FamilyMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: crypto.new_id()[:12])
    name: str
    tax_code: str | None = None
    relation: str = "altro"
    dependent: bool = True  # "a carico"

    @field_validator("name", mode="before")
    @classmethod
    def _v_name(cls, v):
        s = _clean_str(v, 80)
        if not s:
            raise ValueError("Nome obbligatorio")
        return s

    @field_validator("tax_code", mode="before")
    @classmethod
    def _v_cf(cls, v):
        return _cf(v)

    @field_validator("relation", mode="before")
    @classmethod
    def _v_rel(cls, v):
        return v if v in RELATIONS else "altro"


class Profile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    full_name: str | None = None
    tax_code: str | None = None
    family: list[FamilyMember] = Field(default_factory=list)

    @field_validator("full_name", mode="before")
    @classmethod
    def _v_name(cls, v):
        return _clean_str(v, 80)

    @field_validator("tax_code", mode="before")
    @classmethod
    def _v_cf(cls, v):
        return _cf(v)

    def member(self, member_id: str) -> FamilyMember | None:
        return next((m for m in self.family if m.id == member_id), None)

    def known_tax_codes(self) -> dict[str, str]:
        out = {m.tax_code: m.id for m in self.family if m.tax_code}
        if self.tax_code:
            out[self.tax_code] = "self"
        return out

    def beneficiary_label(self, beneficiary: str | None) -> str:
        if not beneficiary or beneficiary == "self":
            return self.full_name or "Me stesso/a"
        m = self.member(beneficiary)
        return m.name if m else "Familiare rimosso"

    def beneficiary_options(self) -> list[tuple[str, str]]:
        opts = [("self", self.beneficiary_label("self"))]
        opts += [(m.id, f"{m.name}{'' if m.dependent else ' (non a carico)'}") for m in self.family]
        return opts


def _aad(user_id: str) -> str:
    return f"profile:{user_id}"


def load_profile(p: Principal) -> Profile:
    if not p.user.profile_blob:
        return Profile()
    return Profile.model_validate(crypto.decrypt_json(p.dek, p.user.profile_blob, _aad(p.user.id)))


def save_profile(db: Session, p: Principal, profile: Profile) -> None:
    p.user.profile_blob = crypto.encrypt_json(p.dek, profile.model_dump(mode="json"), _aad(p.user.id))
    db.commit()
