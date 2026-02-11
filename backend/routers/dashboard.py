"""
Unified Dashboard Router for C.I.T.A.D.E.L.
Returns role-appropriate dashboard data for Government Officials and Citizens.
"""

from fastapi import APIRouter, Depends, Request
from typing import Dict, List, Any

from middleware.access_control import verify_role

router = APIRouter()


@router.get("/")
async def get_dashboard_data(
    request: Request,
    auth: dict = Depends(verify_role)
) -> Dict[str, Any]:
    """Return role-appropriate dashboard data"""
    
    if auth['role'] == 'government_official':
        return _get_government_dashboard_static(auth['user_id'])
    else:
        return _get_citizen_dashboard_static(auth['user_id'])


def _get_government_dashboard_static(user_id: str) -> Dict[str, Any]:
    """Static government dashboard for validation"""
    return {
        'role': 'government_official',
        'user_id': user_id,
        'department': 'General Administration',
        'modules': [
            {
                'name': 'Document Intelligence',
                'description': 'Process and extract data from government forms',
                'endpoint': '/api/documents',
                'icon': 'FileText',
                'stats': {'processed_today': 0, 'pending_reviews': 0}
            },
            {
                'name': 'Resume Screening',
                'description': 'AI-powered candidate evaluation',
                'endpoint': '/api/resumes',
                'icon': 'Users',
                'stats': {'active_postings': 0, 'candidates_screened': 0}
            },
            {
                'name': 'Traffic Violations',
                'description': 'Detect and process traffic violations',
                'endpoint': '/api/traffic-violations',
                'icon': 'Car',
                'stats': {'violations_detected': 0, 'pending_review': 0}
            },
            {
                'name': 'Infrastructure Monitoring',
                'description': 'Real-time sensor anomaly detection',
                'endpoint': '/api/anomaly',
                'icon': 'Activity',
                'stats': {'active_alerts': 0, 'acknowledged': 0}
            }
        ],
        'recent_activity': [],
        'quick_actions': [
            {'label': 'Upload Document', 'action': 'upload_document'},
            {'label': 'View Alerts', 'action': 'view_alerts'},
            {'label': 'Screen Resumes', 'action': 'screen_resumes'}
        ]
    }


def _get_citizen_dashboard_static(user_id: str) -> Dict[str, Any]:
    """Static citizen dashboard for validation"""
    return {
        'role': 'citizen',
        'user_id': user_id,
        'modules': [
            {
                'name': 'AI Assistant',
                'description': 'Ask questions about government services',
                'endpoint': '/api/chat',
                'icon': 'MessageCircle',
                'stats': {'recent_queries': 0, 'documents_cited': 0}
            },
            {
                'name': 'Fake News Checker',
                'description': 'Verify news authenticity',
                'endpoint': '/api/news',
                'icon': 'Shield',
                'stats': {'checks_performed': 0}
            },
            {
                'name': 'Support Tickets',
                'description': 'Submit and track service requests',
                'endpoint': '/api/support-tickets',
                'icon': 'Ticket',
                'stats': {'active_tickets': 0, 'total_submitted': 0}
            },
            {
                'name': 'Expense Claims',
                'description': 'Submit and categorize expenses',
                'endpoint': '/api/expenses',
                'icon': 'Receipt',
                'stats': {'submitted_claims': 0}
            }
        ],
        'recent_activity': [],
        'quick_actions': [
            {'label': 'Ask AI', 'action': 'open_chat'},
            {'label': 'New Ticket', 'action': 'create_ticket'},
            {'label': 'Check News', 'action': 'verify_news'}
        ]
    }


@router.get("/stats")
async def get_dashboard_stats(auth: dict = Depends(verify_role)) -> Dict[str, Any]:
    """Get aggregated statistics for dashboard"""
    
    # In production, query database for real stats
    if auth['role'] == 'government_official':
        return {
            'documents_processed_today': 24,
            'violations_detected_today': 8,
            'active_alerts': 3,
            'pending_reviews': 12,
            'candidates_in_pipeline': 45
        }
    else:
        return {
            'queries_this_month': 15,
            'open_tickets': 2,
            'resolved_tickets': 5,
            'news_checks': 8
        }
