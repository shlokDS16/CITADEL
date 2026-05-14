"""
Supabase client singletons.
- `get_supabase()` → service-role client for backend operations (full access).
- `get_supabase_anon()` → anon client (rarely needed; reserved for user-scoped flows).

We use the service role for all backend writes/reads because every endpoint runs
under server trust. Row-Level-Security on tables stays permissive for
service_role; we enforce auth/authorization in the FastAPI layer.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Service-role Supabase client — full DB + storage access. Backend use only."""
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )


@lru_cache(maxsize=1)
def get_supabase_anon() -> Client:
    """Anon Supabase client — for any flow that must respect RLS."""
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY,
    )


# Default export — service role
supabase: Client = get_supabase()
