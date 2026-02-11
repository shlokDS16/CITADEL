"""
Ticket Analyzer Service
- Intent classification
- Priority prediction
- Resolution hints via RAG
- HITL workflow integration
"""
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID, uuid4
from datetime import datetime

from supabase import create_client

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    CONFIDENCE_THRESHOLD_LOW, CONFIDENCE_THRESHOLD_HIGH,
    REQUIRE_HITL_FOR_ENFORCEMENT
)
from services.audit_service import log_ai_decision, log_audit_event
from services.rag_service import retrieve_context, generate_answer

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Category taxonomy
CATEGORIES = {
    "infrastructure": ["roads", "water", "electricity", "sewage", "bridges"],
    "civic_services": ["garbage", "streetlights", "parks", "public_toilets"],
    "documentation": ["birth_certificate", "property_tax", "building_permit", "license"],
    "complaint": ["corruption", "harassment", "service_delay", "misinformation"],
    "query": ["status_check", "information_request", "clarification"]
}

PRIORITY_KEYWORDS = {
    "critical": ["emergency", "danger", "life-threatening", "immediate", "urgent"],
    "high": ["broken", "not working", "leak", "overflow", "blocked"],
    "medium": ["delay", "slow", "pending", "waiting"],
    "low": ["inquiry", "question", "information", "status"]
}


async def create_ticket(
    title: str,
    description: str,
    submitter_id: UUID,
    source: str = "citizen",
    source_ref_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Create a new ticket with AI classification and priority.
    """
    ticket_id = uuid4()
    
    # Step 1: Classify ticket
    category, subcategory, class_confidence = await classify_ticket(description)
    
    # Step 2: Predict priority
    priority, priority_score = await predict_priority(title, description, category)
    
    # Step 3: Get resolution hint from RAG
    resolution_hint, hint_confidence = await get_resolution_hint(description, category)
    
    # Step 4: Determine if HITL required
    requires_review = (
        class_confidence < CONFIDENCE_THRESHOLD_LOW or
        priority == "critical" or
        (source == "citizen" and category == "complaint")
    )
    
    # Create ticket record
    ticket_record = {
        "id": str(ticket_id),
        "title": title,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "priority": priority,
        "priority_score": priority_score,
        "confidence": min(class_confidence, priority_score),
        "status": "open",
        "source": source,
        "source_ref_id": str(source_ref_id) if source_ref_id else None,
        "resolution_hint": resolution_hint,
        "resolution_confidence": hint_confidence,
        "submitter_id": str(submitter_id),
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("tickets").insert(ticket_record).execute()
    
    # Log ticket creation in history
    await log_ticket_history(
        ticket_id, "created",
        new_value={"status": "open", "category": category, "priority": priority}
    )
    
    # Log AI decisions
    await log_ai_decision(
        model_name="ticket-classify-v1",
        model_version="1.0.0",
        module="ticket_analyzer",
        input_data={"title": title, "description": description[:500]},
        output={"category": category, "subcategory": subcategory, "priority": priority},
        confidence=class_confidence,
        evidence=[{"source": "classification", "category": category}],
        explanation=f"Classified as {category}/{subcategory} with {priority} priority"
    )
    
    # Audit log
    await log_audit_event(
        action="ticket_created",
        entity_type="ticket",
        entity_id=ticket_id,
        actor_id=submitter_id,
        details={"category": category, "priority": priority, "requires_review": requires_review}
    )
    
    return ticket_record


async def classify_ticket(text: str) -> Tuple[str, str, float]:
    """
    Classify ticket into category and subcategory.
    Returns (category, subcategory, confidence)
    """
    text_lower = text.lower()
    
    best_category = "query"
    best_subcategory = "information_request"
    best_score = 0.0
    
    for category, subcategories in CATEGORIES.items():
        category_score = 0
        matched_sub = None
        
        for sub in subcategories:
            # Count keyword matches
            sub_words = sub.replace("_", " ").split()
            matches = sum(1 for word in sub_words if word in text_lower)
            if matches > category_score:
                category_score = matches
                matched_sub = sub
        
        if category_score > best_score:
            best_score = category_score
            best_category = category
            best_subcategory = matched_sub or subcategories[0]
    
    # Normalize confidence
    confidence = min(0.5 + (best_score * 0.15), 0.95)
    
    return best_category, best_subcategory, confidence


async def predict_priority(title: str, description: str, category: str) -> Tuple[str, float]:
    """
    Predict ticket priority based on content and category.
    Returns (priority, score)
    """
    text_lower = (title + " " + description).lower()
    
    priority_scores = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    
    for priority, keywords in PRIORITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                priority_scores[priority] += 1
    
    # Category-based adjustments
    if category == "complaint":
        priority_scores["high"] += 1
    elif category == "query":
        priority_scores["low"] += 1
    
    # Find highest priority
    best_priority = max(priority_scores, key=priority_scores.get)
    
    # Calculate score (normalized)
    total_matches = sum(priority_scores.values())
    if total_matches > 0:
        score = priority_scores[best_priority] / total_matches
        score = 0.5 + (score * 0.4)  # Normalize to 0.5-0.9 range
    else:
        best_priority = "medium"
        score = 0.6
    
    return best_priority, score


async def get_resolution_hint(description: str, category: str) -> Tuple[str, float]:
    """
    Get resolution hint from RAG system based on similar past tickets/policies.
    """
    try:
        # Search for relevant context
        context, _ = await retrieve_context(f"{category} resolution: {description[:200]}")
        
        if context:
            # Generate hint
            hint, confidence, _ = await generate_answer(
                f"How to resolve this {category} issue: {description[:100]}",
                context
            )
            return hint[:500], confidence
    except Exception:
        pass
    
    # Default hints by category
    default_hints = {
        "infrastructure": "Route to Public Works Department for site inspection.",
        "civic_services": "Forward to Municipal Corporation service desk.",
        "documentation": "Check document status in e-governance portal.",
        "complaint": "Escalate to Grievance Redressal Officer.",
        "query": "Check FAQ or contact help desk."
    }
    
    return default_hints.get(category, "Review and assign to appropriate department."), 0.6


async def update_ticket_status(
    ticket_id: UUID,
    new_status: str,
    updated_by: UUID,
    notes: Optional[str] = None
) -> Dict:
    """Update ticket status with audit trail"""
    # Get current ticket
    current = supabase.table("tickets").select("*").eq("id", str(ticket_id)).single().execute()
    
    if not current.data:
        raise ValueError(f"Ticket {ticket_id} not found")
    
    old_status = current.data["status"]
    
    # Update ticket
    update_data = {
        "status": new_status,
        "updated_at": datetime.utcnow().isoformat()
    }
    
    if new_status in ["resolved", "closed"]:
        update_data["resolved_by"] = str(updated_by)
        update_data["resolved_at"] = datetime.utcnow().isoformat()
    
    supabase.table("tickets").update(update_data).eq("id", str(ticket_id)).execute()
    
    # Log history
    await log_ticket_history(
        ticket_id, "status_changed",
        old_value={"status": old_status},
        new_value={"status": new_status, "notes": notes},
        changed_by=updated_by
    )
    
    return {"ticket_id": str(ticket_id), "old_status": old_status, "new_status": new_status}


async def assign_ticket(ticket_id: UUID, assignee_id: UUID, assigned_by: UUID) -> Dict:
    """Assign ticket to operator"""
    supabase.table("tickets").update({
        "assigned_to": str(assignee_id),
        "status": "in_progress",
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", str(ticket_id)).execute()
    
    await log_ticket_history(
        ticket_id, "assigned",
        new_value={"assigned_to": str(assignee_id)},
        changed_by=assigned_by
    )
    
    return {"ticket_id": str(ticket_id), "assigned_to": str(assignee_id)}


async def log_ticket_history(
    ticket_id: UUID,
    action: str,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None,
    changed_by: Optional[UUID] = None
) -> None:
    """Log ticket history entry"""
    record = {
        "id": str(uuid4()),
        "ticket_id": str(ticket_id),
        "action": action,
        "old_value": old_value,
        "new_value": new_value,
        "changed_by": str(changed_by) if changed_by else None,
        "created_at": datetime.utcnow().isoformat()
    }
    supabase.table("ticket_history").insert(record).execute()


async def get_ticket(ticket_id: UUID) -> Optional[Dict]:
    """Get ticket by ID"""
    result = supabase.table("tickets").select("*").eq("id", str(ticket_id)).single().execute()
    return result.data


async def get_ticket_queue(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[UUID] = None,
    limit: int = 50
) -> List[Dict]:
    """Get filtered ticket queue for operators"""
    query = supabase.table("tickets").select("*")
    
    if status:
        query = query.eq("status", status)
    if priority:
        query = query.eq("priority", priority)
    if assigned_to:
        query = query.eq("assigned_to", str(assigned_to))
    
    query = query.order("created_at", desc=True).limit(limit)
    result = query.execute()
    
    return result.data if result.data else []
