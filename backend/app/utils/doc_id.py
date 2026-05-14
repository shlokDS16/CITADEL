"""Sequential DOC-XXXX id generator backed by Postgres `next_doc_id()` function."""
from __future__ import annotations

from app.database import get_supabase


def generate_doc_id() -> str:
    """Returns next sequential id like 'DOC-2841'. Server-side increment via RPC."""
    res = get_supabase().rpc("next_doc_id").execute()
    return res.data
