from .documents import router as documents_router
from .chat import router as chat_router
from .tickets import router as tickets_router
from .resumes import router as resumes_router
from .expenses import router as expenses_router
from .anomaly import router as anomaly_router
from .admin import router as admin_router
from .news import router as news_router
from .dashboard import router as dashboard_router
from .support_tickets import router as support_tickets_router
from .traffic_violations import router as traffic_violations_router

# Import modules for main.py
from . import documents, chat, tickets, resumes, expenses, anomaly, admin, news
from . import dashboard, support_tickets, traffic_violations

__all__ = [
    'documents', 
    'chat', 
    'tickets', 
    'resumes', 
    'expenses', 
    'anomaly', 
    'admin',
    'news',
    'dashboard',
    'support_tickets',
    'traffic_violations'
]

