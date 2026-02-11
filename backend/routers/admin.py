"""
Admin Router - Administrative API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from services.audit_service import (
    generate_evidence_bundle, get_decision_lineage,
    record_human_override
)

router = APIRouter()


class HumanOverride(BaseModel):
    decision: str  # 'approved', 'rejected', 'modified'
    notes: Optional[str] = None
    corrected_output: Optional[dict] = None


@router.get("/evidence/{decision_id}")
async def get_evidence(decision_id: UUID):
    """Generate and get evidence bundle for an AI decision"""
    try:
        bundle = await generate_evidence_bundle(decision_id)
        return bundle
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/lineage/{decision_id}")
async def get_lineage(decision_id: UUID):
    """Get full lineage chain for an AI decision"""
    lineage = await get_decision_lineage(decision_id)
    return {"decision_id": str(decision_id), "lineage": lineage}


@router.post("/override/{decision_id}")
async def human_override(decision_id: UUID, override: HumanOverride):
    """Record a human override of an AI decision"""
    try:
        reviewer_id = UUID("00000000-0000-0000-0000-000000000001")
        await record_human_override(
            decision_id=decision_id,
            reviewer_id=reviewer_id,
            decision=override.decision,
            notes=override.notes,
            corrected_output=override.corrected_output
        )
        return {"success": True, "message": "Override recorded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
