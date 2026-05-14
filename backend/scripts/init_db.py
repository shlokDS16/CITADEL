"""
Initialize Supabase: create storage buckets + check tables exist + seed templates if missing.

Run from backend/ dir:
    python -m scripts.init_db

This script does NOT execute DDL — Supabase REST does not allow that.
You must run `migrations/001_document_intelligence.sql` in the Supabase SQL editor first.
This script verifies the migration applied correctly and creates the storage buckets.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import get_supabase

supa = get_supabase()


def step(label: str):
    print(f"\n--- {label} ---")


# ------------------------------------------------------------------
# 1. Verify tables exist
# ------------------------------------------------------------------
step("Verifying tables")

REQUIRED_TABLES = ["documents", "document_chunks", "audit_log", "templates", "users", "doc_id_counter"]

table_status: dict[str, str] = {}
for tbl in REQUIRED_TABLES:
    try:
        # head=True returns no rows, just confirms table exists
        supa.table(tbl).select("*", head=True, count="exact").execute()
        table_status[tbl] = "OK"
    except Exception as e:
        table_status[tbl] = f"MISSING ({type(e).__name__})"

for t, s in table_status.items():
    print(f"  {t:20s} -> {s}")

missing = [t for t, s in table_status.items() if s != "OK"]
if missing:
    print()
    print(f"!! {len(missing)} tables are missing.")
    print("   Run migrations/001_document_intelligence.sql in the Supabase SQL Editor:")
    print(f"   {settings.SUPABASE_URL}/project/_/sql")
    sys.exit(1)


# ------------------------------------------------------------------
# 2. Verify next_doc_id() function
# ------------------------------------------------------------------
step("Verifying next_doc_id() function")
try:
    r = supa.rpc("next_doc_id").execute()
    sample_id = r.data
    print(f"  Generated test id: {sample_id}")
except Exception as e:
    print(f"  FAIL: {e}")
    print("  Re-run the migration SQL in Supabase SQL Editor.")
    sys.exit(1)


# ------------------------------------------------------------------
# 3. Create storage buckets if missing
# ------------------------------------------------------------------
step("Creating storage buckets")

for bucket_name in (settings.SUPABASE_BUCKET_DOCUMENTS, settings.SUPABASE_BUCKET_PROCESSED):
    try:
        existing = [b.name for b in supa.storage.list_buckets()]
        if bucket_name in existing:
            print(f"  {bucket_name:15s} -> already exists")
            continue
        supa.storage.create_bucket(
            bucket_name,
            options={"public": False, "file_size_limit": settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024},
        )
        print(f"  {bucket_name:15s} -> CREATED (private, {settings.MAX_UPLOAD_SIZE_MB}MB limit)")
    except Exception as e:
        print(f"  {bucket_name:15s} -> error: {e}")


# ------------------------------------------------------------------
# 4. Verify templates seeded
# ------------------------------------------------------------------
step("Verifying seed templates")
try:
    r = supa.table("templates").select("id, document_type, name, is_system").execute()
    rows = r.data or []
    print(f"  {len(rows)} templates present")
    for row in sorted(rows, key=lambda x: x["document_type"]):
        marker = " [SYSTEM]" if row["is_system"] else ""
        print(f"    {row['document_type']:20s}  {row['name']}{marker}")
except Exception as e:
    print(f"  FAIL: {e}")
    sys.exit(1)


# ------------------------------------------------------------------
# 5. Done
# ------------------------------------------------------------------
print()
print("=" * 60)
print("Supabase initialization complete.")
print("Next: cd backend && uvicorn app.main:app --reload --port 8000")
print("=" * 60)
