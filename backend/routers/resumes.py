"""
Resumes Router - Resume Screening API endpoints
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

from services.resume_service import (
    parse_resume, create_job, match_resume_to_job, get_top_candidates, screen_resumes_batch
)

router = APIRouter()


class JobCreate(BaseModel):
    title: str
    department: str
    description: str
    required_skills: List[str]
    preferred_skills: Optional[List[str]] = None
    experience_min: float = 0.0


@router.post("/screen")
async def screen_resumes(
    job_description: str = Form(...),
    files: List[UploadFile] = File(...)
):
    """Screen multiple resumes against a job description"""
    try:
        file_data = []
        for file in files:
            content = await file.read()
            file_data.append((file.filename, content))
        
        # Process in batch
        results = await screen_resumes_batch(file_data, job_description)
        return {"success": True, "candidates": results}
    except Exception as e:
        print(f"Screening error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    candidate_name: Optional[str] = None
):
    """Upload and parse a resume"""
    try:
        content = await file.read()
        result = await parse_resume(content, file.filename, candidate_name)
        return {"success": True, "resume": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs")
async def create_new_job(job: JobCreate):
    """Create a job posting"""
    try:
        result = await create_job(
            title=job.title,
            department=job.department,
            description=job.description,
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            experience_min=job.experience_min
        )
        return {"success": True, "job": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/match/{resume_id}/{job_id}")
async def match_to_job(resume_id: UUID, job_id: UUID):
    """Match a resume to a job"""
    try:
        result = await match_resume_to_job(resume_id, job_id)
        return {"success": True, "match": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates/{job_id}")
async def get_candidates(job_id: UUID, limit: int = 10):
    """Get top candidates for a job"""
    candidates = await get_top_candidates(job_id, limit)
    return {"job_id": str(job_id), "candidates": candidates}
