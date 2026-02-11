# 📚 C.I.T.A.D.E.L. — Findings & Research Notes

## Dataset Sources

### Document Intelligence

| Dataset | Source | Type | Usage |
|---------|--------|------|-------|
| FUNSD | [Kaggle](https://www.kaggle.com/datasets/mehulgupta2016154/funsd-dataset) | Form Understanding | Field extraction training |
| RVL-CDIP | [HuggingFace](https://huggingface.co/datasets/rvl_cdip) | Document Classification | Document type detection |
| Custom PDFs | Synthetic | Policy documents | RAG indexing demo |

### Ticket Analysis

| Dataset | Source | Type | Usage |
|---------|--------|------|-------|
| Customer Support Tickets | [Kaggle](https://www.kaggle.com/datasets/suraj520/customer-support-ticket-dataset) | CSV | Intent classification |
| Complaint Dataset | [UCI](https://archive.ics.uci.edu/ml/datasets/Consumer+Complaints) | Text | Priority prediction |

### Traffic Detection (Secondary)

| Dataset | Source | Type | Usage |
|---------|--------|------|-------|
| Traffic Signs | [Kaggle](https://www.kaggle.com/datasets/ahemateja19bec1025/traffic-sign-dataset-classification) | Images | Signal detection |
| Helmet Detection | [Roboflow](https://universe.roboflow.com/) | Images | Safety violation |

### Sensor Data (Secondary)

| Dataset | Source | Type | Usage |
|---------|--------|------|-------|
| Air Quality | [OpenAQ](https://openaq.org/) | Time-series | Anomaly detection |
| Fire/Smoke | [Kaggle](https://www.kaggle.com/datasets/phylake1337/fire-dataset) | Images | Alert generation |

---

## Technical Constraints

### Supabase Limits (Free Tier)
- Database: 500MB
- Storage: 1GB
- Edge Functions: 500K invocations/month
- Realtime: 200 concurrent connections

### Model Considerations
- Use Gemini API for LLM tasks (RAG, summarization)
- Use open models for classification (local or cloud)
- pgvector for embeddings (dimension: 768 or 1536)

---

## Architecture Decisions

### Decision 1: Embedding Model
**Choice**: text-embedding-3-small (OpenAI) or Gemini embeddings
**Rationale**: Balance of quality and cost for hackathon scope
**Dimension**: 1536 (OpenAI) or 768 (Gemini)

### Decision 2: OCR Pipeline
**Choice**: Tesseract + pdf2image OR Google Vision API
**Rationale**: Tesseract for cost, Vision API for accuracy
**Fallback**: Manual text input for demo

### Decision 3: Classification Approach
**Choice**: Fine-tuned small model OR few-shot with LLM
**Rationale**: Few-shot faster to implement, acceptable accuracy
**Upgrade Path**: Fine-tune post-hackathon

---

## Assumptions

1. **Demo Data Labeled**: All synthetic/Kaggle data clearly marked as demo
2. **No Real PII**: Only synthetic PII for detection testing
3. **Single Region**: All services in Asia-Pacific for latency
4. **Auth Simplified**: Email/password auth, no SSO for demo
5. **Push Mocked**: Email/SMS alerts logged, not actually sent

---

## Open Questions

- [ ] Specific Gemini model version for production?
- [ ] Vector dimension preference (768 vs 1536)?
- [ ] UI framework preference (Next.js, Vite, vanilla)?
- [ ] Deployment target (Vercel, local demo)?

---
