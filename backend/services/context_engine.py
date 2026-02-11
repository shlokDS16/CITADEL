"""
Unified Context Engine for C.I.T.A.D.E.L.
Manages user context across all modules for session-aware intelligence.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from uuid import uuid4

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY


class CitizenContext(BaseModel):
    """Context object for citizen users"""
    user_id: str
    session_id: str
    role: str = "citizen"
    
    # RAG history
    rag_queries: List[Dict[str, Any]] = Field(default_factory=list)
    rag_cited_documents: List[str] = Field(default_factory=list)
    
    # Uploaded documents (for expense claims, etc.)
    uploaded_documents: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Support tickets
    active_tickets: List[str] = Field(default_factory=list)
    ticket_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Fake news checks
    fake_news_queries: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Expense claims
    submitted_expenses: List[Dict[str, Any]] = Field(default_factory=list)
    
    last_updated: datetime = Field(default_factory=datetime.now)


class GovernmentContext(BaseModel):
    """Context object for government officials"""
    user_id: str
    session_id: str
    role: str = "government_official"
    department: Optional[str] = None
    
    # Document processing
    processed_documents: List[Dict[str, Any]] = Field(default_factory=list)
    flagged_inconsistencies: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Resume screening
    active_job_postings: List[str] = Field(default_factory=list)
    screened_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Traffic violations
    detected_violations: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Infrastructure monitoring
    acknowledged_anomalies: List[str] = Field(default_factory=list)
    active_alerts: List[Dict[str, Any]] = Field(default_factory=list)
    
    last_updated: datetime = Field(default_factory=datetime.now)


class ContextEngine:
    """
    Manages user context across modules.
    Stores in Supabase 'chat_sessions' table for persistence (reusing existing table).
    """
    
    def __init__(self, supabase_client=None):
        self.supabase = supabase_client or create_client(SUPABASE_URL, SUPABASE_KEY)
    
    async def get_context(
        self, 
        user_id: str, 
        session_id: Optional[str] = None, 
        role: str = "citizen"
    ) -> Union[CitizenContext, GovernmentContext]:
        """Retrieve or create user context"""
        
        if not session_id:
            session_id = str(uuid4())
        
        try:
            result = self.supabase.table('chat_sessions')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('id', session_id)\
                .execute()
            
            if result.data and len(result.data) > 0:
                context_data = result.data[0].get('context_data', {})
                if context_data:
                    if role == "citizen":
                        return CitizenContext(**context_data)
                    else:
                        return GovernmentContext(**context_data)
        except Exception:
            pass
        
        # Create new context
        if role == "citizen":
            ctx = CitizenContext(user_id=user_id, session_id=session_id)
        else:
            ctx = GovernmentContext(user_id=user_id, session_id=session_id)
        
        await self.save_context(ctx)
        return ctx
    
    async def save_context(self, context: Union[CitizenContext, GovernmentContext]):
        """Persist context to database"""
        try:
            # Convert datetime to string for JSON
            context_dict = context.model_dump()
            context_dict['last_updated'] = context_dict['last_updated'].isoformat()
            
            self.supabase.table('chat_sessions').upsert({
                'id': context.session_id,
                'user_id': context.user_id,
                'session_type': context.role,
                'context_data': context_dict,
                'updated_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            print(f"Warning: Failed to save context: {e}")
    
    async def update_rag_history(
        self, 
        context: CitizenContext, 
        query: str, 
        response: str, 
        sources: List[str]
    ):
        """Called by RAG service after each query"""
        context.rag_queries.append({
            'query': query,
            'response': response[:500],  # Truncate for storage
            'timestamp': datetime.now().isoformat()
        })
        context.rag_cited_documents.extend(sources)
        context.last_updated = datetime.now()
        await self.save_context(context)
    
    async def add_processed_document(
        self, 
        context: GovernmentContext, 
        doc_id: str, 
        doc_type: str, 
        extracted_data: Dict
    ):
        """Called by Document Intelligence after processing"""
        if isinstance(context, GovernmentContext):
            context.processed_documents.append({
                'doc_id': doc_id,
                'doc_type': doc_type,
                'extracted_data': extracted_data,
                'timestamp': datetime.now().isoformat()
            })
            await self.save_context(context)
    
    async def add_ticket(self, context: CitizenContext, ticket_id: str, category: str):
        """Called by Ticket Analyzer after creating ticket"""
        if isinstance(context, CitizenContext):
            context.active_tickets.append(ticket_id)
            context.ticket_history.append({
                'ticket_id': ticket_id,
                'category': category,
                'created_at': datetime.now().isoformat()
            })
            await self.save_context(context)
    
    async def add_violation(
        self, 
        context: GovernmentContext, 
        violation_id: str, 
        violation_type: str,
        confidence: float
    ):
        """Called by Traffic Violations after detection"""
        if isinstance(context, GovernmentContext):
            context.detected_violations.append({
                'violation_id': violation_id,
                'type': violation_type,
                'confidence': confidence,
                'timestamp': datetime.now().isoformat()
            })
            await self.save_context(context)
    
    async def cross_reference_data(
        self, 
        context: Union[CitizenContext, GovernmentContext], 
        entity_type: str, 
        entity_value: str
    ) -> Dict[str, List]:
        """
        Find related data across modules.
        Example: If processing building permit for Address X, check if anomaly detector
        has flagged sensor readings at Address X.
        """
        related_data = {}
        
        if isinstance(context, GovernmentContext):
            # Check if this address has anomalies
            related_data['anomalies'] = [
                alert for alert in context.active_alerts 
                if entity_value.lower() in str(alert.get('location', '')).lower()
            ]
            
            # Check if this location has traffic violations
            related_data['violations'] = [
                v for v in context.detected_violations 
                if entity_value.lower() in str(v.get('location', '')).lower()
            ]
            
            # Check processed documents for this entity
            related_data['documents'] = [
                doc for doc in context.processed_documents
                if entity_value.lower() in str(doc.get('extracted_data', {})).lower()
            ]
        
        return related_data


# Singleton instance
_context_engine = None

def get_context_engine() -> ContextEngine:
    """Get singleton context engine instance"""
    global _context_engine
    if _context_engine is None:
        _context_engine = ContextEngine()
    return _context_engine
