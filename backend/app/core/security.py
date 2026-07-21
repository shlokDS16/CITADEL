"""
Password hashing + JWT issue/verify (security-baseline.md).

Passwords: argon2id (argon2-cffi defaults — time_cost 3, 64MiB, parallel 4).
bcrypt is deliberately NOT used for new hashes.

Tokens: HS256 in dev (RS256 is a prod key-management upgrade, not a code
change — the verify path only needs the algorithm swapped). Two issuers,
`citadel-gov` and `citadel-citizen`, chosen by the account's role: a token
minted for the citizen portal can never pass a gov-issuer check even if
the role claim were tampered toward gov, because the signature covers iss.

Refresh tokens are opaque 256-bit random strings; only their sha256 lands
in the DB. Rotation: every refresh revokes the old row and links the new
one — presenting an already-revoked token is treated as theft and revokes
the user's whole chain.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings

log = logging.getLogger("citadel.core.security")

_ph = PasswordHasher()

GOV_ROLES = ("gov_admin", "gov_officer", "gov_analyst")
ISSUER_GOV = "citadel-gov"
ISSUER_CITIZEN = "citadel-citizen"


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception as e:  # noqa: BLE001 — malformed hash etc.
        log.warning("password verify errored: %s", e)
        return False


def issuer_for_role(role: str) -> str:
    return ISSUER_GOV if role in GOV_ROLES else ISSUER_CITIZEN


def mint_access_token(user_id: str, role: str, username: str) -> tuple[str, int]:
    """→ (token, expires_in_seconds)."""
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=settings.JWT_ACCESS_MINUTES)
    claims: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "username": username,
        "iss": issuer_for_role(role),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256"), int(ttl.total_seconds())


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Verified claims, or None. Issuer is checked against the role INSIDE
    the token so the two portals cannot cross-honour each other's tokens."""
    try:
        claims = jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"],
            options={"require": ["sub", "role", "iss", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError as e:
        log.debug("jwt rejected: %s", e)
        return None
    if claims.get("iss") != issuer_for_role(str(claims.get("role", ""))):
        log.warning("jwt issuer/role mismatch — rejected")
        return None
    return claims


def new_refresh_token() -> tuple[str, str]:
    """→ (raw_token, sha256_hash). Raw goes to the client once; only the
    hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
