from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from services.news_analyzer import analyze_news_url
from typing import Dict, List, Optional
from datetime import datetime
from uuid import uuid4

router = APIRouter(tags=["News Authenticity"])

class NewsRequest(BaseModel):
    url: HttpUrl

class NewsResponse(BaseModel):
    url: str
    title: str
    authenticity_score: float
    credibility_label: str
    confidence: float
    domain_reputation: str
    evidence: List[Dict]
    risk_factors: List[str]
    trust_signals: List[str]
    analyzed_at: str

@router.post("/analyze", response_model=NewsResponse)
async def analyze_article(request: NewsRequest):
    """
    Analyze a news article for authenticity.
    """
    try:
        # call the service
        result = await analyze_news_url(str(request.url))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_status():
    return {"status": "News Analyzer Online", "version": "1.0.0"}


@router.get("/")
async def get_fake_news_overview(
    limit: int = 10
):
    """
    Root endpoint for fake news service.
    Returns recent fact-checks performed and service status.
    """
    # Return static data for validation - in production, integrate with context engine
    return {
        'service': 'fake_news_detector',
        'status': 'operational',
        'version': '1.0.0',
        'recent_checks': [],
        'total_checks': 0
    }

