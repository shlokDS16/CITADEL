"""Sequential JOB-XXXX / CAND-XXXX id generators backed by Postgres RPCs."""
from __future__ import annotations

from app.database import get_supabase


def generate_job_code() -> str:
    return get_supabase().rpc("next_job_code").execute().data


def generate_cand_code() -> str:
    return get_supabase().rpc("next_cand_code").execute().data
