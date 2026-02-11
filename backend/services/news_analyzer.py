"""
News Article Authenticity Analyzer
Analyzes news articles from URLs for fake news detection.

Features:
1. URL scraping and content extraction
2. Text-based authenticity classification
3. Source credibility checking
4. Evidence-based reasoning
"""
import asyncio
import re
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from uuid import uuid4
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


@dataclass
class ArticleAnalysis:
    """Result of news article authenticity analysis"""
    url: str
    title: str
    content: str
    domain: str
    
    # Authenticity scores
    authenticity_score: float  # 0-1, higher = more authentic
    credibility_label: str     # "likely_real", "uncertain", "likely_fake"
    confidence: float          # Model confidence
    
    # Evidence
    evidence: List[Dict] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    trust_signals: List[str] = field(default_factory=list)
    
    # Source analysis
    domain_reputation: Optional[str] = None
    fact_check_results: List[Dict] = field(default_factory=list)
    
    # Metadata
    analyzed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    word_count: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "title": self.title,
            "domain": self.domain,
            "authenticity_score": self.authenticity_score,
            "credibility_label": self.credibility_label,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "risk_factors": self.risk_factors,
            "trust_signals": self.trust_signals,
            "domain_reputation": self.domain_reputation,
            "word_count": self.word_count,
            "analyzed_at": self.analyzed_at
        }


# Known domain reputations (simplified - in production use a proper database)
TRUSTED_DOMAINS = {
    "reuters.com": "high",
    "apnews.com": "high",
    "bbc.com": "high",
    "bbc.co.uk": "high",
    "nytimes.com": "high",
    "washingtonpost.com": "high",
    "theguardian.com": "high",
    "npr.org": "high",
    "wsj.com": "high",
    "economist.com": "high",
    "thehindu.com": "high",
    "indianexpress.com": "medium",
    "timesofindia.indiatimes.com": "medium",
    "ndtv.com": "medium",
    "hindustantimes.com": "medium",
}

SUSPICIOUS_DOMAINS = {
    "naturalnews.com": "known_misinformation",
    "infowars.com": "known_misinformation",
    "beforeitsnews.com": "known_misinformation",
    "worldnewsdailyreport.com": "satire_often_shared_as_real",
}

# Clickbait and sensational patterns
CLICKBAIT_PATTERNS = [
    r"you won't believe",
    r"shocking",
    r"breaking:",
    r"urgent:",
    r"this will change everything",
    r"doctors hate",
    r"one weird trick",
    r"exposed!",
    r"they don't want you to know",
    r"\d+ reasons why",
    r"what happens next will",
]

# Credibility indicators
CREDIBILITY_INDICATORS = [
    r"according to",
    r"sources say",
    r"reported by",
    r"study shows",
    r"research indicates",
    r"official statement",
    r"confirmed",
    r"fact-check",
]


class NewsArticleAnalyzer:
    """
    Analyzes news articles for authenticity.
    
    Uses multiple signals:
    1. Domain reputation
    2. Content analysis (clickbait, sensationalism)
    3. Writing quality
    4. Source citations
    5. ML classification (when integrated)
    """
    
    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    async def analyze_url(self, url: str) -> ArticleAnalysis:
        """
        Main analysis function - takes URL and returns authenticity analysis
        """
        # Step 1: Extract content
        title, content, domain = await self._extract_article(url)
        
        # Step 2: Analyze domain reputation
        domain_rep = self._check_domain_reputation(domain)
        
        # Step 3: Content analysis
        risk_factors, trust_signals = self._analyze_content(title, content)
        
        # Step 4: Calculate authenticity score
        score, label, confidence = self._calculate_authenticity(
            domain_rep, risk_factors, trust_signals, content
        )
        
        # Step 5: Generate evidence
        evidence = self._generate_evidence(
            domain, domain_rep, risk_factors, trust_signals, score
        )
        
        return ArticleAnalysis(
            url=url,
            title=title,
            content=content[:2000] + "..." if len(content) > 2000 else content,
            domain=domain,
            authenticity_score=score,
            credibility_label=label,
            confidence=confidence,
            evidence=evidence,
            risk_factors=risk_factors,
            trust_signals=trust_signals,
            domain_reputation=domain_rep,
            word_count=len(content.split())
        )
    
    async def _extract_article(self, url: str) -> Tuple[str, str, str]:
        """Extract article content from URL"""
        try:
            # Parse domain
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            
            # Fetch page
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title = ""
            if soup.title:
                title = soup.title.string or ""
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)
            
            # Extract main content
            # Try common article containers
            content = ""
            
            # Try article tag
            article = soup.find('article')
            if article:
                paragraphs = article.find_all('p')
                content = ' '.join(p.get_text(strip=True) for p in paragraphs)
            
            # Fallback: all paragraphs
            if not content or len(content) < 100:
                paragraphs = soup.find_all('p')
                content = ' '.join(p.get_text(strip=True) for p in paragraphs)
            
            # Clean up
            content = re.sub(r'\s+', ' ', content).strip()
            
            return title, content, domain
            
        except Exception as e:
            return f"Error extracting: {str(e)}", "", urlparse(url).netloc
    
    def _check_domain_reputation(self, domain: str) -> str:
        """Check domain reputation"""
        domain_lower = domain.lower()
        
        # Check trusted domains
        for trusted, level in TRUSTED_DOMAINS.items():
            if trusted in domain_lower:
                return f"trusted_{level}"
        
        # Check suspicious domains
        for suspicious, reason in SUSPICIOUS_DOMAINS.items():
            if suspicious in domain_lower:
                return f"suspicious_{reason}"
        
        return "unknown"
    
    def _analyze_content(self, title: str, content: str) -> Tuple[List[str], List[str]]:
        """Analyze content for risk factors and trust signals"""
        risk_factors = []
        trust_signals = []
        
        full_text = f"{title} {content}".lower()
        
        # Check for clickbait patterns
        for pattern in CLICKBAIT_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                risk_factors.append(f"Clickbait pattern: '{pattern}'")
        
        # Check for credibility indicators
        for indicator in CREDIBILITY_INDICATORS:
            if re.search(indicator, full_text, re.IGNORECASE):
                trust_signals.append(f"Credibility indicator: '{indicator}'")
        
        # Check for all caps (sensationalism)
        words = content.split()
        caps_words = sum(1 for w in words if w.isupper() and len(w) > 3)
        if caps_words > 5:
            risk_factors.append(f"Excessive capitalization ({caps_words} words)")
        
        # Check for excessive punctuation
        if content.count('!') > 5:
            risk_factors.append(f"Excessive exclamation marks ({content.count('!')})")
        
        # Check article length
        word_count = len(words)
        if word_count < 100:
            risk_factors.append(f"Very short article ({word_count} words)")
        elif word_count > 500:
            trust_signals.append(f"Substantial article length ({word_count} words)")
        
        # Check for quotes (indicates sourcing)
        quote_count = content.count('"') // 2
        if quote_count >= 2:
            trust_signals.append(f"Contains quotes from sources ({quote_count})")
        
        # Check for numbers/statistics (indicates research)
        numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', content)
        if len(numbers) >= 3:
            trust_signals.append(f"Contains statistics/data ({len(numbers)} numbers)")
        
        return risk_factors, trust_signals
    
    def _calculate_authenticity(
        self, 
        domain_rep: str, 
        risk_factors: List[str], 
        trust_signals: List[str],
        content: str
    ) -> Tuple[float, str, float]:
        """Calculate authenticity score"""
        score = 0.5  # Start neutral
        
        # Domain reputation impact (±0.3)
        if "trusted_high" in domain_rep:
            score += 0.3
        elif "trusted_medium" in domain_rep:
            score += 0.15
        elif "suspicious" in domain_rep:
            score -= 0.4
        
        # Risk factors (each -0.08)
        score -= len(risk_factors) * 0.08
        
        # Trust signals (each +0.05)
        score += len(trust_signals) * 0.05
        
        # Clamp score
        score = max(0.0, min(1.0, score))
        
        # Determine label
        if score >= 0.7:
            label = "likely_real"
        elif score >= 0.4:
            label = "uncertain"
        else:
            label = "likely_fake"
        
        # Confidence based on evidence strength
        evidence_count = len(risk_factors) + len(trust_signals)
        if "unknown" in domain_rep:
            confidence = 0.5 + (evidence_count * 0.03)
        else:
            confidence = 0.7 + (evidence_count * 0.02)
        confidence = min(0.95, confidence)
        
        return round(score, 3), label, round(confidence, 3)
    
    def _generate_evidence(
        self,
        domain: str,
        domain_rep: str,
        risk_factors: List[str],
        trust_signals: List[str],
        score: float
    ) -> List[Dict]:
        """Generate evidence list for transparency"""
        evidence = []
        
        # Domain evidence
        if "trusted" in domain_rep:
            evidence.append({
                "type": "domain",
                "finding": f"Source ({domain}) is from a reputable news organization",
                "impact": "positive",
                "weight": 0.3
            })
        elif "suspicious" in domain_rep:
            evidence.append({
                "type": "domain", 
                "finding": f"Source ({domain}) has history of publishing misinformation",
                "impact": "negative",
                "weight": 0.4
            })
        else:
            evidence.append({
                "type": "domain",
                "finding": f"Source ({domain}) has unknown reputation",
                "impact": "neutral",
                "weight": 0.0
            })
        
        # Risk factor evidence
        for risk in risk_factors[:3]:  # Top 3
            evidence.append({
                "type": "content_risk",
                "finding": risk,
                "impact": "negative",
                "weight": 0.08
            })
        
        # Trust signal evidence
        for signal in trust_signals[:3]:  # Top 3
            evidence.append({
                "type": "content_trust",
                "finding": signal,
                "impact": "positive",
                "weight": 0.05
            })
        
        return evidence


async def analyze_news_url(url: str) -> Dict:
    """
    Convenience function to analyze a URL
    Returns dict with analysis results
    """
    analyzer = NewsArticleAnalyzer()
    result = await analyzer.analyze_url(url)
    return result.to_dict()


# CLI for testing
if __name__ == "__main__":
    import sys
    
    async def main():
        print(f"\n{'='*60}")
        print("  News Article Authenticity Analyzer")
        print(f"{'='*60}\n")
        
        # Test URLs
        test_urls = [
            "https://www.bbc.com/news",  # Trusted source
            "https://www.reuters.com/world/",  # Trusted source
        ]
        
        if len(sys.argv) > 1:
            test_urls = [sys.argv[1]]
        
        analyzer = NewsArticleAnalyzer()
        
        for url in test_urls:
            print(f"\n📰 Analyzing: {url}")
            print("-" * 50)
            
            try:
                result = await analyzer.analyze_url(url)
                
                # Display results
                emoji = "🟢" if result.credibility_label == "likely_real" else (
                    "🟡" if result.credibility_label == "uncertain" else "🔴"
                )
                
                print(f"\nTitle: {result.title[:80]}...")
                print(f"Domain: {result.domain}")
                print(f"Domain Reputation: {result.domain_reputation}")
                print(f"\n{emoji} Verdict: {result.credibility_label.upper()}")
                print(f"   Authenticity Score: {result.authenticity_score:.1%}")
                print(f"   Confidence: {result.confidence:.1%}")
                
                if result.risk_factors:
                    print(f"\n⚠️ Risk Factors ({len(result.risk_factors)}):")
                    for rf in result.risk_factors[:3]:
                        print(f"   - {rf}")
                
                if result.trust_signals:
                    print(f"\n✅ Trust Signals ({len(result.trust_signals)}):")
                    for ts in result.trust_signals[:3]:
                        print(f"   - {ts}")
                
                print(f"\nWord Count: {result.word_count}")
                
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print(f"\n{'='*60}\n")
    
    asyncio.run(main())
