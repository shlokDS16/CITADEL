"""
Audit Service - Logs all AI decisions and generates evidence bundles
CRITICAL: All AI services MUST use this for output logging
"""
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from supabase import create_client
from config import (
    SUPABASE_URL, SUPABASE_KEY, 
    CONFIDENCE_THRESHOLD_LOW, ENABLE_ACTIVE_LEARNING
)

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def compute_input_hash(input_data: Any) -> str:
    """Compute SHA256 hash of input for reproducibility"""
    serialized = json.dumps(input_data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


async def log_ai_decision(
    model_name: str,
    model_version: str,
    module: str,
    input_data: Any,
    output: Dict[str, Any],
    confidence: float,
    source_document_id: Optional[UUID] = None,
    vector_ids: Optional[List[UUID]] = None,
    parent_decision_id: Optional[UUID] = None,
    evidence: Optional[List[Dict]] = None,
    explanation: Optional[str] = None
) -> UUID:
    """
    Log an AI decision to the audit table.
    Returns the decision ID for reference.
    
    This function MUST be called by every AI service after inference.
    """
    decision_id = uuid4()
    
    # Determine if human review is required based on confidence
    requires_human_review = confidence < CONFIDENCE_THRESHOLD_LOW
    
    record = {
        "id": str(decision_id),
        "model_name": model_name,
        "model_version": model_version,
        "module": module,
        "input_hash": compute_input_hash(input_data),
        "input_summary": str(input_data)[:500],  # Truncate for readability
        "source_document_id": str(source_document_id) if source_document_id else None,
        "vector_ids": [str(v) for v in vector_ids] if vector_ids else None,
        "parent_decision_id": str(parent_decision_id) if parent_decision_id else None,
        "output": output,
        "confidence": confidence,
        "evidence": evidence,
        "explanation": explanation,
        "requires_human_review": requires_human_review,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Insert decision record
    supabase.table("ai_decisions").insert(record).execute()
    
    # Queue for active learning if low confidence
    if ENABLE_ACTIVE_LEARNING and requires_human_review:
        await queue_for_learning(decision_id, model_name, "low_confidence")
    
    return decision_id


async def queue_for_learning(
    decision_id: UUID,
    model_name: str,
    reason: str
) -> None:
    """Add decision to active learning queue"""
    record = {
        "id": str(uuid4()),
        "decision_id": str(decision_id),
        "model_name": model_name,
        "reason": reason,
        "processed": False,
        "created_at": datetime.utcnow().isoformat()
    }
    supabase.table("learning_queue").insert(record).execute()


async def record_human_override(
    decision_id: UUID,
    reviewer_id: UUID,
    decision: str,  # 'approved', 'rejected', 'modified'
    notes: Optional[str] = None,
    corrected_output: Optional[Dict] = None
) -> None:
    """Record a human override of an AI decision"""
    # Update the AI decision record
    supabase.table("ai_decisions").update({
        "human_reviewed": True,
        "human_reviewer_id": str(reviewer_id),
        "human_decision": decision,
        "human_notes": notes,
        "reviewed_at": datetime.utcnow().isoformat()
    }).eq("id", str(decision_id)).execute()
    
    # If modified, create training sample
    if decision == "modified" and corrected_output:
        original = supabase.table("ai_decisions").select("*").eq("id", str(decision_id)).single().execute()
        
        training_record = {
            "id": str(uuid4()),
            "decision_id": str(decision_id),
            "model_name": original.data["model_name"],
            "input_data": {"hash": original.data["input_hash"]},
            "original_output": original.data["output"],
            "corrected_output": corrected_output,
            "corrected_by": str(reviewer_id),
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("training_samples").insert(training_record).execute()


async def generate_evidence_bundle(decision_id: UUID, bundle_type: str = "json") -> Dict:
    """Generate exportable evidence bundle for a decision"""
    # Fetch decision with full context
    decision = supabase.table("ai_decisions").select("*").eq("id", str(decision_id)).single().execute()
    
    if not decision.data:
        raise ValueError(f"Decision {decision_id} not found")
    
    bundle = {
        "bundle_id": str(uuid4()),
        "decision_id": str(decision_id),
        "generated_at": datetime.utcnow().isoformat(),
        "decision": decision.data,
        "lineage": await get_decision_lineage(decision_id),
        "evidence": decision.data.get("evidence", [])
    }
    
    # Store bundle reference
    bundle_record = {
        "id": bundle["bundle_id"],
        "decision_id": str(decision_id),
        "bundle_type": bundle_type,
        "metadata": bundle,
        "created_at": datetime.utcnow().isoformat()
    }
    supabase.table("evidence_bundles").insert(bundle_record).execute()
    
    return bundle


async def get_decision_lineage(decision_id: UUID) -> List[Dict]:
    """Get full lineage chain for a decision (provenance)"""
    lineage = []
    current_id = decision_id
    
    while current_id:
        decision = supabase.table("ai_decisions").select(
            "id, model_name, model_version, module, confidence, parent_decision_id, created_at"
        ).eq("id", str(current_id)).single().execute()
        
        if not decision.data:
            break
            
        lineage.append(decision.data)
        current_id = decision.data.get("parent_decision_id")
    
    return lineage


async def log_audit_event(
    action: str,
    entity_type: str,
    entity_id: UUID,
    actor_id: Optional[UUID],
    details: Optional[Dict] = None
) -> None:
    """Log generic audit event (immutable)"""
    record = {
        "id": str(uuid4()),
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "actor_id": str(actor_id) if actor_id else None,
        "details": details,
        "created_at": datetime.utcnow().isoformat()
    }
    supabase.table("audit_logs").insert(record).execute()
