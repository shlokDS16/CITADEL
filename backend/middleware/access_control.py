"""
Role-Based Access Control Middleware for C.I.T.A.D.E.L.
Enforces portal-specific access to API endpoints.
"""

from enum import Enum
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Optional


class UserRole(Enum):
    CITIZEN = "citizen"
    GOVERNMENT_OFFICIAL = "government_official"
    ADMIN = "admin"


class AccessControl:
    """
    Enforces role-based access to modules.
    Government modules: Document Intelligence, Resume Screening, Traffic Violations, Anomaly Detection (write)
    Citizen modules: RAG Chatbot, Fake News Detection, Support Tickets, Expense Categorizer
    Shared: Expense Categorizer (different views), Anomaly Detection (read-only for citizens)
    """
    
    GOVERNMENT_ONLY = {
        "/api/documents/process",
        "/api/documents/extract",
        "/api/resumes",
        "/api/traffic-violations",
        "/api/anomaly/manage",
        "/api/admin"
    }
    
    CITIZEN_ONLY = {
        "/api/support-tickets",
    }
    
    @staticmethod
    def verify_access(role: str, endpoint: str) -> bool:
        try:
            user_role = UserRole(role)
        except ValueError:
            return False
        
        # Admin has universal access
        if user_role == UserRole.ADMIN:
            return True
            
        # Check government-only endpoints
        for gov_ep in AccessControl.GOVERNMENT_ONLY:
            if endpoint.startswith(gov_ep):
                return user_role == UserRole.GOVERNMENT_OFFICIAL
            
        # Check citizen-only endpoints  
        for cit_ep in AccessControl.CITIZEN_ONLY:
            if endpoint.startswith(cit_ep):
                return user_role == UserRole.CITIZEN
            
        # Shared endpoints allow both
        return True


async def verify_role(
    x_user_role: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None)
):
    """Dependency for FastAPI routes to enforce access control"""
    if not x_user_role or not x_user_id:
        # Allow unauthenticated access for demo (remove in production)
        return {"user_id": "anonymous", "role": "citizen"}
    
    try:
        UserRole(x_user_role)
        return {"user_id": x_user_id, "role": x_user_role}
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid user role")


async def enforce_role_based_access(request: Request, call_next):
    """
    Middleware to intercept all requests and verify role-based permissions.
    Add this to main.py with: app.middleware("http")(enforce_role_based_access)
    """
    
    # Skip auth check for public endpoints
    public_paths = ["/", "/docs", "/health", "/openapi.json", "/redoc"]
    if request.url.path in public_paths or request.url.path.startswith("/docs"):
        return await call_next(request)
    
    user_role = request.headers.get("x-user-role", "citizen")
    endpoint = request.url.path
    
    if not AccessControl.verify_access(user_role, endpoint):
        return JSONResponse(
            status_code=403,
            content={"detail": f"Role '{user_role}' cannot access '{endpoint}'"}
        )
    
    response = await call_next(request)
    return response
