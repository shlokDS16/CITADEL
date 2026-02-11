# C.I.T.A.D.E.L. Module Dependencies

## Dependency Graph

```
┌─────────────────────────────────────────────────────────────┐
│                      CORE LAYER                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Supabase │  │ SentenceT│  │  config  │  │  audit   │     │
│  │  Client  │  │ransformer│  │   .py    │  │ service  │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
└───────┼─────────────┼─────────────┼─────────────┼───────────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│                    MIDDLEWARE LAYER                          │
│  ┌───────────────────┐     ┌───────────────────┐            │
│  │  access_control   │◄────│   context_engine  │            │
│  └─────────┬─────────┘     └─────────┬─────────┘            │
└────────────┼─────────────────────────┼──────────────────────┘
             │                         │
             ▼                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    SERVICE LAYER                             │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ rag_service │  │news_analyzer│  │anomaly_svc  │          │
│  │ (existing)  │  │ (existing)  │  │ (existing)  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│  ┌──────┴─────────────┐  │  ┌─────────────┴──────┐          │
│  │  resume_service    │  │  │  expense_service   │          │
│  │    (existing)      │  │  │    (existing)      │          │
│  └────────────────────┘  │  └────────────────────┘          │
│                          │                                   │
│  ┌─────────────┐  ┌──────┴──────┐  ┌─────────────┐          │
│  │ document_   │  │ticket_      │  │traffic_     │          │
│  │intelligence │  │analyzer     │  │violations   │◄───NEW   │
│  │    (NEW)    │  │   (NEW)     │  │   (NEW)     │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Critical Dependencies

| Service | Depends On | Breaks If Missing |
|---------|------------|-------------------|
| rag_service | Supabase, SentenceTransformer | ❌ Fatal |
| news_analyzer | requests, BeautifulSoup | ❌ Fatal |
| anomaly_service | Supabase, sklearn | ❌ Fatal |
| expense_service | Supabase, Tesseract | ❌ Fatal |
| resume_service | Supabase, SentenceTransformer | ❌ Fatal |
| context_engine | Supabase | ⚠️ Degrades to stateless |
| access_control | None (pure logic) | ⚠️ Bypasses auth |
| document_intelligence | Tesseract, context_engine | ⚠️ Isolated failure |
| ticket_analyzer | context_engine | ⚠️ Isolated failure |
| traffic_violations | OpenCV, context_engine | ⚠️ Isolated failure |

## Cascade Failure Risks

1. **Supabase Down** → All services fail (except pure-compute like news_analyzer scraping)
2. **context_engine crash** → New modules fail, existing modules unaffected
3. **access_control crash** → All authenticated routes fail
