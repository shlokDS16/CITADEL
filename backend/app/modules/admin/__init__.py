"""
Admin panel backend (Phase 6) — gov_admin only.

Control surface for the platform: user management (roles, activation),
the append-only audit log, and platform-wide stats. Every route requires
the gov_admin role, enforced in the router (the seeded rsd account is the
only admin until an admin promotes another).
"""
from app.modules.admin.router import router  # noqa: F401
