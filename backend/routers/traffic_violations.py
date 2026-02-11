"""
Traffic Violations Router for C.I.T.A.D.E.L.
Government-facing traffic violation detection and management.
"""

from fastapi import APIRouter, UploadFile, File, Depends, Request, HTTPException
from typing import List, Optional
from pathlib import Path

from services.traffic_violations import get_traffic_detector
from services.context_engine import get_context_engine, GovernmentContext
from middleware.access_control import verify_role

from services.rag_service import supabase # Use the existing supabase client

router = APIRouter()

@router.get("/fines")
async def get_fines():
    """Get all fine amounts from the government database"""
    try:
        response = supabase.table("govt_fines_penalties").select("*").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Ensure temp directory exists
Path(".tmp").mkdir(exist_ok=True)


@router.post("/analyze")
async def analyze_traffic_footage(
    request: Request,
    video: UploadFile = File(...),
    violation_types: str = "helmetless,red_light",
    location: Optional[str] = None,
    auth: dict = Depends(verify_role)
):
    """
    Analyze traffic footage for violations (government officials only).
    
    Args:
        video: Video file to analyze
        violation_types: Comma-separated list of violation types to detect
        location: Optional location/intersection name
    
    Returns:
        Analysis results with detected violations and evidence
    """
    
    # Check role
    if auth['role'] not in ['government_official', 'admin']:
        raise HTTPException(status_code=403, detail="Government officials only")
    
    # Save uploaded file
    video_path = f".tmp/{video.filename}"
    with open(video_path, "wb") as f:
        content = await video.read()
        f.write(content)
    
    # Parse violation types
    types_list = [v.strip() for v in violation_types.split(",")]
    
    # Analyze
    detector = get_traffic_detector()
    result = await detector.analyze_footage(video_path, types_list, location)
    
    # Update government context
    try:
        context_engine = get_context_engine()
        session_id = request.headers.get('x-session-id')
        context = await context_engine.get_context(auth['user_id'], session_id, auth['role'])
        
        if isinstance(context, GovernmentContext):
            for v in result.get('violations', []):
                await context_engine.add_violation(
                    context,
                    v['violation_id'],
                    v['type'],
                    v['confidence']
                )
    except Exception:
        pass  # Context update is non-critical
    
    return result


@router.get("/types")
async def get_violation_types():
    """Get available violation types for detection"""
    detector = get_traffic_detector()
    return {
        "types": detector.VIOLATION_TYPES
    }


@router.get("/stats")
async def get_violation_stats(auth: dict = Depends(verify_role)):
    """Get violation detection statistics"""
    
    if auth['role'] not in ['government_official', 'admin']:
        raise HTTPException(status_code=403, detail="Government officials only")
    
    detector = get_traffic_detector()
    return await detector.get_violation_stats(auth['user_id'])


@router.post("/review/{violation_id}")
async def review_violation(
    violation_id: str,
    action: str,  # 'confirm' or 'reject'
    notes: Optional[str] = None,
    auth: dict = Depends(verify_role)
):
    """Review and confirm/reject a detected violation"""
    
    if auth['role'] not in ['government_official', 'admin']:
        raise HTTPException(status_code=403, detail="Government officials only")
    
    if action not in ['confirm', 'reject']:
        raise HTTPException(status_code=400, detail="Action must be 'confirm' or 'reject'")
    
    return {
        "violation_id": violation_id,
        "action": action,
        "status": "confirmed" if action == "confirm" else "rejected",
        "reviewed_by": auth['user_id'],
        "notes": notes
    }
