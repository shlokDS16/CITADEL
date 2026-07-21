"""
Auth business logic: credential check, lockout, token lifecycle, claim.

Lockout per security-baseline.md: 5 failed logins in a row → 30-minute
lock. The counter resets on success. Lock state lives on the users row so
it survives restarts and applies across processes.

Audit: login / login_failed / logout / lockout / token_refresh /
token_reuse_detected all land in the append-only audit_log (0.7).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings
from app.core import security
from app.database import get_supabase

log = logging.getLogger("citadel.auth.service")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30

#: The pre-auth demo creds keep working — they are now real seeded
#: accounts, not client-side constants.
SEED_ACCOUNTS = (
    # (fixed uuid, username, password, role, display_name, email)
    ("00000000-0000-0000-0000-000000000001", "rsd", "citadel", "gov_admin", "RSD (Gov Admin)", "rsd@gov.in"),
    ("00000000-0000-0000-0000-000000000002", "citizen", "citizen", "citizen", "Demo Citizen", "citizen@demo.in"),
)


class AuthError(Exception):
    """Message is safe to show the user; status decided by the router."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def _audit(action: str, user_id: Optional[str], details: dict[str, Any]) -> None:
    try:
        get_supabase().table("audit_log").insert({
            "action": action,
            "performed_by": user_id or "anonymous",
            "details": details,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("auth audit write failed: %s", e)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_by_username(username: str) -> Optional[dict[str, Any]]:
    rows = (
        get_supabase().table("users").select("*")
        .ilike("username", username).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _shape_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "username": row.get("username") or "",
        "display_name": row.get("display_name"),
        "role": row.get("role"),
        "last_login_at": row.get("last_login_at"),
    }


# --------------------------------------------------------------------------
# Seeding — idempotent, runs at startup
# --------------------------------------------------------------------------
def ensure_seed_accounts() -> None:
    """Create/repair the two demo accounts. Never overwrites a password
    the user has since changed (only fills NULL hashes)."""
    sb = get_supabase()
    for uid, username, password, role, display, email in SEED_ACCOUNTS:
        try:
            rows = (sb.table("users").select("id, username, password_hash, role")
                    .eq("id", uid).limit(1).execute()).data or []
            if not rows:
                sb.table("users").insert({
                    "id": uid, "username": username, "email": email,
                    "display_name": display, "role": role,
                    "password_hash": security.hash_password(password),
                }).execute()
                log.info("seeded account %s (%s)", username, role)
                continue
            row = rows[0]
            patch: dict[str, Any] = {}
            if not row.get("username"):
                patch["username"] = username
            if not row.get("password_hash"):
                patch["password_hash"] = security.hash_password(password)
            if not row.get("role"):
                patch["role"] = role
            if patch:
                patch.setdefault("display_name", display)
                sb.table("users").update(patch).eq("id", uid).execute()
                log.info("repaired seed account %s: %s", username, list(patch))
        except Exception as e:  # noqa: BLE001
            log.warning("seed account %s failed: %s", username, e)


# --------------------------------------------------------------------------
# Login / lockout
# --------------------------------------------------------------------------
def login(username: str, password: str, portal: str, user_agent: Optional[str]) -> dict[str, Any]:
    user = _user_by_username(username)
    # Verify against a dummy hash on unknown users so response timing does
    # not reveal whether the username exists.
    if user is None or not user.get("password_hash"):
        security.verify_password(password, security.hash_password("timing-pad"))
        _audit("login_failed", None, {"username": username[:64], "reason": "unknown_user"})
        raise AuthError("invalid username or password")

    uid = str(user["id"])
    locked_until = user.get("locked_until")
    if locked_until:
        lu = datetime.fromisoformat(str(locked_until).replace("Z", "+00:00"))
        if lu > _now():
            raise AuthError(
                f"account locked — try again in {max(1, int((lu - _now()).total_seconds() // 60))} min",
                status=423,
            )

    if not user.get("is_active", True):
        raise AuthError("account disabled", status=403)

    role = user.get("role") or "citizen"
    portal_gov = portal == "government"
    if portal_gov != (role in security.GOV_ROLES):
        # right creds through the wrong door still refuses — and does not
        # count as a failed-password attempt
        raise AuthError("this account cannot log in through this portal", status=403)

    if not security.verify_password(password, user["password_hash"]):
        fails = int(user.get("failed_attempts") or 0) + 1
        patch: dict[str, Any] = {"failed_attempts": fails}
        if fails >= MAX_FAILED_ATTEMPTS:
            patch["locked_until"] = (_now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            patch["failed_attempts"] = 0
            _audit("lockout", uid, {"minutes": LOCKOUT_MINUTES})
        get_supabase().table("users").update(patch).eq("id", uid).execute()
        _audit("login_failed", uid, {"attempt": fails})
        if "locked_until" in patch:
            raise AuthError(f"too many failed attempts — locked for {LOCKOUT_MINUTES} min", status=423)
        raise AuthError("invalid username or password")

    # success — reset counters, mint tokens
    get_supabase().table("users").update({
        "failed_attempts": 0, "locked_until": None,
        "last_login_at": _now().isoformat(),
    }).eq("id", uid).execute()

    access, expires_in = security.mint_access_token(uid, role, user.get("username") or username)
    raw_refresh, refresh_hash = security.new_refresh_token()
    get_supabase().table("refresh_tokens").insert({
        "user_id": uid,
        "token_hash": refresh_hash,
        "expires_at": (_now() + timedelta(days=settings.JWT_REFRESH_DAYS)).isoformat(),
        "user_agent": (user_agent or "")[:255] or None,
    }).execute()
    _audit("login", uid, {"portal": portal})

    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "expires_in": expires_in,
        "user": _shape_user({**user, "last_login_at": _now().isoformat()}),
    }


# --------------------------------------------------------------------------
# Refresh (rotating) / logout
# --------------------------------------------------------------------------
def _refresh_row(token_hash: str) -> Optional[dict[str, Any]]:
    rows = (
        get_supabase().table("refresh_tokens").select("*")
        .eq("token_hash", token_hash).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def refresh(raw_token: str, user_agent: Optional[str]) -> dict[str, Any]:
    sb = get_supabase()
    row = _refresh_row(security.hash_refresh_token(raw_token))
    if row is None:
        raise AuthError("invalid refresh token")

    uid = str(row["user_id"])
    if row.get("revoked_at"):
        # Reuse of a rotated-out token = replay/theft signal → kill the chain.
        sb.table("refresh_tokens").update({"revoked_at": _now().isoformat()}) \
            .eq("user_id", uid).is_("revoked_at", "null").execute()
        _audit("token_reuse_detected", uid, {})
        raise AuthError("refresh token reuse detected — all sessions revoked")

    exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if exp < _now():
        raise AuthError("refresh token expired")

    users = (sb.table("users").select("*").eq("id", uid).limit(1).execute()).data or []
    if not users or not users[0].get("is_active", True):
        raise AuthError("account unavailable", status=403)
    user = users[0]
    role = user.get("role") or "citizen"

    # rotate: new row first, then revoke old and link it
    raw_new, new_hash = security.new_refresh_token()
    new_row = sb.table("refresh_tokens").insert({
        "user_id": uid,
        "token_hash": new_hash,
        "expires_at": (_now() + timedelta(days=settings.JWT_REFRESH_DAYS)).isoformat(),
        "user_agent": (user_agent or "")[:255] or None,
    }).execute().data[0]
    sb.table("refresh_tokens").update({
        "revoked_at": _now().isoformat(), "replaced_by": new_row["id"],
    }).eq("id", row["id"]).execute()

    access, expires_in = security.mint_access_token(uid, role, user.get("username") or "")
    _audit("token_refresh", uid, {})
    return {
        "access_token": access,
        "refresh_token": raw_new,
        "expires_in": expires_in,
        "user": _shape_user(user),
    }


def logout(raw_token: str, user_id: Optional[str]) -> None:
    row = _refresh_row(security.hash_refresh_token(raw_token))
    if row and not row.get("revoked_at"):
        get_supabase().table("refresh_tokens").update(
            {"revoked_at": _now().isoformat()}
        ).eq("id", row["id"]).execute()
        _audit("logout", user_id or str(row["user_id"]), {})


# --------------------------------------------------------------------------
# Citizen registration
# --------------------------------------------------------------------------
#: portal -> role granted on self-signup. Government self-signup gets
#: gov_officer (operational, not admin). See RegisterIn docstring.
_SIGNUP_ROLE = {"government": "gov_officer", "citizen": "citizen"}


def register(
    username: str, password: str, display_name: Optional[str],
    email: Optional[str], portal: str = "citizen",
) -> dict[str, Any]:
    if _user_by_username(username):
        raise AuthError("username already taken", status=409)
    role = _SIGNUP_ROLE.get(portal, "citizen")
    row = get_supabase().table("users").insert({
        "username": username,
        "password_hash": security.hash_password(password),
        "role": role,
        "display_name": display_name,
        "email": email,
    }).execute().data[0]
    _audit("register", str(row["id"]), {"username": username[:64], "role": role})
    return _shape_user(row)


# --------------------------------------------------------------------------
# Claim — adopt pre-auth browser rows into the logged-in citizen account
# --------------------------------------------------------------------------
#: table → column(s) holding the anonymous browser uuid
_CLAIM_TARGETS: tuple[tuple[str, str], ...] = (
    ("expenses", "citizen_id"),
    ("receipts", "citizen_id"),
    ("budgets", "citizen_id"),
    ("import_batches", "citizen_id"),
    ("exports", "citizen_id"),
    ("tickets", "submitted_by"),
    ("ticket_upvotes", "citizen_id"),
    ("ticket_comments", "citizen_id"),
)


def claim_anonymous(user_id: str, anonymous_uid: str) -> dict[str, int]:
    """Re-own rows created under the browser uuid. Idempotent; a uuid that
    was never used simply migrates zero rows.

    Guard: refuses to claim another ACCOUNT's uuid — only rows whose owner
    id does not belong to any registered user can be adopted.
    """
    from uuid import UUID

    anon = str(UUID(anonymous_uid))  # raises ValueError on garbage
    sb = get_supabase()
    owner = (sb.table("users").select("id").eq("id", anon).limit(1).execute()).data or []
    if owner:
        raise AuthError("that identity belongs to a registered account", status=403)

    migrated: dict[str, int] = {}
    for table, col in _CLAIM_TARGETS:
        try:
            res = sb.table(table).update({col: user_id}).eq(col, anon).execute()
            n = len(res.data or [])
            if n:
                migrated[table] = n
        except Exception as e:  # noqa: BLE001
            log.warning("claim %s.%s failed: %s", table, col, e)
    if migrated:
        _audit("claim_anonymous", user_id, {"from": anon, "migrated": migrated})
    return migrated
