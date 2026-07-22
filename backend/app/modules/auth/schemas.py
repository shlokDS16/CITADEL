"""Auth request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Role = Literal["gov_admin", "gov_officer", "gov_analyst", "citizen"]


class LoginIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    portal: Literal["government", "citizen"] = Field(
        ..., description="Which portal the login came from — a gov account "
        "cannot log in through the citizen portal or vice versa.",
    )

    @field_validator("username")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Access-token lifetime, seconds.")
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    role: Role
    last_login_at: Optional[datetime] = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class LogoutIn(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class RegisterIn(BaseModel):
    """Self-registration for either portal.

    CITADEL ships as an open showcase, so the government portal accepts
    self-signup too. A government signup is granted `gov_officer` (full
    operational workflow: approve incidents, issue challans, triage
    tickets) but never `gov_admin` — admin is seeded and owns the admin
    panel. Citizen signup grants `citizen`.
    """
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=255)
    portal: Literal["government", "citizen"] = "citizen"

    @field_validator("username", mode="before")
    @classmethod
    def _trim_username(cls, v: str) -> str:
        # Mobile keyboards often append a trailing space / autocapitalize;
        # trim before the pattern check so a stray space is not a hard 422.
        return v.strip() if isinstance(v, str) else v


class ClaimIn(BaseModel):
    """Adopt rows created under the pre-auth browser uuid into this account."""
    anonymous_uid: str = Field(..., description="The browser's citadel_tk_uid.")


class ClaimOut(BaseModel):
    migrated: dict[str, int] = Field(
        ..., description="Rows re-owned per table, e.g. {'expenses': 12, 'tickets': 3}."
    )
