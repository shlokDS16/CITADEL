"""
Data Seeder - Load sample datasets into Supabase
Run this script to populate the database with demo data
"""
import json
import asyncio
from pathlib import Path
from uuid import uuid4

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from services.document_intel import upload_document
from services.ticket_service import create_ticket
from services.resume_service import parse_resume, create_job, match_resume_to_job
from services.expense_service import ingest_expense
from services.anomaly_service import ingest_sensor_reading

DATA_DIR = Path(__file__).parent


async def seed_documents():
    """Seed sample documents"""
    print("📄 Seeding documents...")
    with open(DATA_DIR / "documents.json") as f:
        docs = json.load(f)["documents"]
    
    for doc in docs:
        content = doc["content"].encode('utf-8')
        await upload_document(
            file_content=content,
            filename=f"{doc['title']}.txt",
            doc_type=doc["doc_type"],
            source_tier="demo",
            uploader_id=uuid4()
        )
        print(f"  ✓ {doc['title']}")
    print(f"  Loaded {len(docs)} documents\n")


async def seed_tickets():
    """Seed sample tickets"""
    print("🎫 Seeding tickets...")
    with open(DATA_DIR / "tickets.json") as f:
        tickets = json.load(f)
    
    for ticket in tickets:
        await create_ticket(
            title=ticket["title"],
            description=ticket["description"],
            submitter_id=uuid4()
        )
        print(f"  ✓ {ticket['title'][:50]}...")
    print(f"  Loaded {len(tickets)} tickets\n")


async def seed_resumes_and_jobs():
    """Seed resumes and jobs"""
    print("📋 Seeding resumes and jobs...")
    
    # Load resumes
    with open(DATA_DIR / "resumes.json") as f:
        resumes = json.load(f)
    
    resume_ids = []
    for resume in resumes:
        content = resume["content"].encode('utf-8')
        result = await parse_resume(content, f"{resume['candidate_name']}.txt", resume["candidate_name"])
        resume_ids.append(result["id"])
        print(f"  ✓ Resume: {resume['candidate_name']}")
    
    # Load jobs
    with open(DATA_DIR / "jobs.json") as f:
        jobs = json.load(f)
    
    job_ids = []
    for job in jobs:
        result = await create_job(
            title=job["title"],
            department=job["department"],
            description=job["description"],
            required_skills=job["required_skills"],
            preferred_skills=job.get("preferred_skills"),
            experience_min=job["experience_min"]
        )
        job_ids.append(result["id"])
        print(f"  ✓ Job: {job['title']}")
    
    # Match first job to all resumes
    print("  Matching resumes to jobs...")
    for resume_id in resume_ids:
        for job_id in job_ids:
            await match_resume_to_job(resume_id, job_id)
    
    print(f"  Loaded {len(resumes)} resumes, {len(jobs)} jobs\n")


async def seed_expenses():
    """Seed sample expenses"""
    print("💰 Seeding expenses...")
    with open(DATA_DIR / "expenses.json") as f:
        expenses = json.load(f)
    
    for exp in expenses:
        await ingest_expense(
            department=exp["department"],
            amount=exp["amount"],
            description=exp["description"]
        )
    print(f"  Loaded {len(expenses)} expenses\n")


async def seed_sensors():
    """Seed sample sensor readings"""
    print("📡 Seeding sensor readings...")
    with open(DATA_DIR / "sensors.json") as f:
        readings = json.load(f)
    
    for reading in readings:
        await ingest_sensor_reading(
            sensor_id=reading["sensor_id"],
            sensor_type=reading["sensor_type"],
            value=reading["value"],
            location=reading.get("location")
        )
    print(f"  Loaded {len(readings)} sensor readings\n")


async def main():
    print("\n" + "="*50)
    print("  C.I.T.A.D.E.L. Data Seeder")
    print("="*50 + "\n")
    
    await seed_documents()
    await seed_tickets()
    await seed_resumes_and_jobs()
    await seed_expenses()
    await seed_sensors()
    
    print("="*50)
    print("  ✅ All data loaded successfully!")
    print("="*50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
