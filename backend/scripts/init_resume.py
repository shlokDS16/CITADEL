"""
Resume module: verify migration + create storage bucket.

Run from backend/:
    python -m scripts.init_resume
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import get_supabase

supa = get_supabase()
print("--- Verifying resume tables ---")
REQUIRED = ["jobs", "candidates", "pipeline_history", "telegram_chats", "job_id_counter", "cand_id_counter"]
missing = []
for t in REQUIRED:
    try:
        supa.table(t).select("*", head=True, count="exact").execute()
        print(f"  {t:24s} -> OK")
    except Exception:
        missing.append(t)
        print(f"  {t:24s} -> MISSING")

if missing:
    print(f"\n!! Run backend/migrations/002_resume_screening.sql in Supabase SQL Editor:")
    print(f"   {settings.SUPABASE_URL}/project/_/sql")
    sys.exit(1)

print("\n--- Verifying RPC functions ---")
try:
    print(f"  next_job_code() -> {supa.rpc('next_job_code').execute().data}")
    print(f"  next_cand_code() -> {supa.rpc('next_cand_code').execute().data}")
except Exception as e:
    print(f"  FAIL: {e}")
    sys.exit(1)

print("\n--- Storage buckets ---")
existing = [b.name for b in supa.storage.list_buckets()]
if settings.SUPABASE_BUCKET_RESUMES in existing:
    print(f"  {settings.SUPABASE_BUCKET_RESUMES} -> already exists")
else:
    supa.storage.create_bucket(settings.SUPABASE_BUCKET_RESUMES,
                               options={"public": False, "file_size_limit": 10 * 1024 * 1024})
    print(f"  {settings.SUPABASE_BUCKET_RESUMES} -> CREATED (private, 10MB limit)")

print("\n--- Seed jobs ---")
jobs = supa.table("jobs").select("code, title, department").order("code").execute().data or []
for j in jobs:
    print(f"  {j['code']:14s} {j['title']:35s} ({j['department']})")
print(f"  {len(jobs)} jobs total")
print("\nReady. Restart backend (citadel-backend) to pick up the new resume router.")
