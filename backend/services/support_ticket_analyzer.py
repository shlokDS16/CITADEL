"""
Customer Support Ticket Analyzer for C.I.T.A.D.E.L.
Classifies, prioritizes, and routes citizen support tickets using NLP.
"""

from typing import Dict, List, Optional
from datetime import datetime
from uuid import uuid4

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY


class TicketAnalyzer:
    """
    Classify, prioritize, and route citizen support tickets.
    Uses NLP for intent extraction and urgency prediction.
    """
    
    CATEGORIES = {
        'water_supply': ['water', 'leak', 'pipe', 'supply', 'tap', 'drainage', 'sewage'],
        'electricity': ['power', 'outage', 'electricity', 'transformer', 'billing', 'meter', 'voltage'],
        'roads': ['pothole', 'road', 'traffic', 'street', 'sidewalk', 'highway', 'bridge'],
        'sanitation': ['garbage', 'waste', 'trash', 'dump', 'collection', 'cleaning', 'hygiene'],
        'tax': ['tax', 'property tax', 'payment', 'bill', 'assessment', 'refund', 'dues'],
        'permits': ['permit', 'license', 'approval', 'building', 'construction', 'certificate'],
        'public_safety': ['crime', 'theft', 'harassment', 'safety', 'emergency', 'police'],
        'healthcare': ['hospital', 'clinic', 'medicine', 'health', 'vaccination', 'ambulance']
    }
    
    URGENCY_KEYWORDS = {
        'high': ['emergency', 'urgent', 'immediate', 'critical', 'danger', 'flooding', 'fire', 'accident', 'life-threatening'],
        'medium': ['soon', 'asap', 'quickly', 'important', 'needed', 'priority'],
        'low': ['whenever', 'eventually', 'future', 'suggestion', 'feedback', 'inquiry']
    }
    
    DEPARTMENT_ROUTING = {
        'water_supply': 'Water Department',
        'electricity': 'Electricity Board',
        'roads': 'Public Works Department',
        'sanitation': 'Sanitation Department',
        'tax': 'Revenue Department',
        'permits': 'Building Department',
        'public_safety': 'Public Safety Division',
        'healthcare': 'Health Department',
        'general': 'General Administration'
    }
    
    SLA_HOURS = {
        'high': 24,
        'medium': 72,
        'low': 168  # 1 week
    }
    
    def __init__(self):
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    async def analyze_ticket(
        self, 
        title: str,
        description: str,
        user_id: str,
        contact_email: Optional[str] = None
    ) -> Dict:
        """
        Main analysis pipeline.
        Returns: category, priority, urgency, suggested resolution, routing.
        """
        full_text = f"{title} {description}"
        
        # Analysis steps
        category = self._classify_category(full_text)
        urgency = self._predict_urgency(full_text)
        priority = self._calculate_priority(urgency, category)
        suggestion = self._generate_response_suggestion(category, full_text)
        department = self.DEPARTMENT_ROUTING.get(category, 'General Administration')
        sla_hours = self.SLA_HOURS.get(priority, 72)
        
        ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        
        result = {
            'ticket_id': ticket_id,
            'title': title,
            'description': description,
            'category': category,
            'urgency': urgency,
            'priority': priority,
            'suggested_response': suggestion,
            'route_to_department': department,
            'estimated_sla_hours': sla_hours,
            'requires_escalation': priority == 'high',
            'status': 'open',
            'created_at': datetime.now().isoformat()
        }
        
        # Store in database
        try:
            self.supabase.table('tickets').insert({
                'id': str(uuid4()),
                'user_id': user_id,
                'title': title,
                'text': description,
                'category': category,
                'priority_score': {'high': 1, 'medium': 2, 'low': 3}.get(priority, 2),
                'status': 'open',
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            print(f"Warning: Failed to store ticket: {e}")
        
        return result
    
    def _classify_category(self, text: str) -> str:
        """Classify ticket into predefined categories"""
        text_lower = text.lower()
        
        category_scores = {}
        for category, keywords in self.CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            category_scores[category] = score
        
        if max(category_scores.values(), default=0) > 0:
            return max(category_scores, key=category_scores.get)
        else:
            return 'general'
    
    def _predict_urgency(self, text: str) -> str:
        """Predict urgency level from text"""
        text_lower = text.lower()
        
        for urgency_level, keywords in self.URGENCY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return urgency_level
        
        return 'medium'
    
    def _calculate_priority(self, urgency: str, category: str) -> str:
        """Calculate priority based on urgency and category"""
        # High-impact categories get elevated priority
        high_impact_categories = {'public_safety', 'water_supply', 'electricity', 'healthcare'}
        
        if urgency == 'high':
            return 'high'
        elif urgency == 'medium' and category in high_impact_categories:
            return 'high'
        elif urgency == 'medium':
            return 'medium'
        else:
            return 'low'
    
    def _generate_response_suggestion(self, category: str, text: str) -> str:
        """Generate templated auto-response"""
        templates = {
            'water_supply': "Thank you for reporting the water supply issue. Our team has been notified and will inspect the area within 24 hours. For emergencies, please call our helpline at 1800-XXX-XXXX.",
            'electricity': "Your electricity concern has been logged. We will dispatch a technician to assess the situation. Expected resolution: 48 hours. Track status at our portal.",
            'roads': "We have received your road maintenance request. Our public works department will evaluate and schedule repairs based on priority assessment.",
            'sanitation': "Your sanitation concern has been registered. Our team will address this within 72 hours. Thank you for helping keep our city clean.",
            'tax': "Your tax-related inquiry has been forwarded to the Revenue Department. An officer will contact you within 5 business days.",
            'permits': "Your permit request is being processed. Please check the online portal for status updates or visit the Building Department office.",
            'public_safety': "Your safety concern has been prioritized. If this is an emergency, please call 100 immediately. Otherwise, our team will follow up within 24 hours.",
            'healthcare': "Your healthcare request has been logged. For immediate medical emergencies, please call 108. Our health department will respond within 48 hours.",
            'general': "Thank you for contacting us. Your ticket has been assigned to the appropriate department. You will receive an update within 72 hours."
        }
        
        return templates.get(category, templates['general'])
    
    async def get_ticket_status(self, ticket_id: str, user_id: str) -> Optional[Dict]:
        """Get status of a specific ticket"""
        try:
            result = self.supabase.table('tickets')\
                .select('*')\
                .eq('user_id', user_id)\
                .execute()
            
            if result.data:
                return result.data[0]
        except Exception:
            pass
        return None
    
    async def get_user_tickets(self, user_id: str) -> List[Dict]:
        """Get all tickets for a user"""
        try:
            result = self.supabase.table('tickets')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('created_at', desc=True)\
                .execute()
            
            return result.data or []
        except Exception:
            return []


# Singleton instance
_ticket_analyzer = None

def get_ticket_analyzer() -> TicketAnalyzer:
    """Get singleton ticket analyzer instance"""
    global _ticket_analyzer
    if _ticket_analyzer is None:
        _ticket_analyzer = TicketAnalyzer()
    return _ticket_analyzer
