# C.I.T.A.D.E.L. Pre-Demo Verification Checklist

## 🟢 Government Portal Flow
- [ ] Can login as government official
- [ ] Dashboard shows 4 modules (Doc Intel, Resume, Traffic, Anomaly)
- [ ] Upload sample permit PDF → extracts fields with confidence scores
- [ ] Upload sample resume → ranks against job description with explanation
- [ ] Upload traffic video → detects at least one violation with evidence
- [ ] Anomaly monitor shows sensor data and flags outliers

## 🔵 Citizen Portal Flow
- [ ] Can login as citizen
- [ ] Dashboard shows 4 modules (RAG, Fake News, Tickets, Expenses)
- [ ] Ask RAG chatbot "What are the building permit requirements?" → gets answer with source citation
- [ ] Submit fake news URL → gets credibility score with explanation
- [ ] Create support ticket → gets auto-categorized with priority and suggested response
- [ ] Upload expense receipt → gets categorized and anomaly-checked

## 🔗 Cross-Module Context
- [ ] Process document as official → RAG can reference it
- [ ] Anomaly detected at address X → Check if violations exist at address X
- [ ] Ticket created by citizen → Context remembers in session

## ⚡ Performance
- [ ] All endpoints respond within 3 seconds
- [ ] No 500 errors in any flow
- [ ] Vector DB returns results (not empty)

## 📊 Data Populated
- [ ] Vector DB has at least 50 municipal documents
- [ ] Anomaly detector has baseline sensor data
- [ ] Resume dataset loaded (at least 10 samples)
- [ ] Ticket categories configured

## 🛡️ Security (RBAC)
- [ ] Government endpoints reject citizen requests (403)
- [ ] Citizen endpoints work for citizens
- [ ] Admin has universal access
- [ ] Public endpoints (/, /health, /docs) accessible without auth

---

## Quick Test Commands

```bash
# Start backend
cd backend
uvicorn main:app --reload --port 8000

# Test health endpoint
curl http://localhost:8000/health

# Test government dashboard (should work)
curl -H "x-user-role: government_official" -H "x-user-id: test123" http://localhost:8000/api/dashboard/

# Test citizen dashboard (should work)
curl -H "x-user-role: citizen" -H "x-user-id: test456" http://localhost:8000/api/dashboard/

# Test RBAC (should return 403)
curl -H "x-user-role: citizen" http://localhost:8000/api/admin/

# Test support ticket
curl -X POST http://localhost:8000/api/support-tickets/submit \
  -H "Content-Type: application/json" \
  -H "x-user-role: citizen" \
  -H "x-user-id: test456" \
  -d '{"title":"Water leak","description":"Emergency water leak on Main Street","contact_email":"test@example.com"}'
```

---

## Demo Script

### Act 1: Citizen Portal (3 min)
1. Open citizen portal
2. Ask AI assistant about building permits
3. Submit a support ticket → show auto-categorization
4. Check fake news on a sample URL

### Act 2: Government Portal (3 min)
1. Switch to government login
2. Show dashboard with all modules
3. Upload a document → show extraction + confidence
4. View anomaly alerts

### Act 3: Cross-Module Intelligence (2 min)
1. Show how context is preserved across modules
2. Demonstrate RBAC (citizen cannot access government endpoints)
3. Show audit trail of AI decisions

---

## Fallback Modes

If any module fails:

| Module | Fallback |
|--------|----------|
| Traffic Violations | Disable, show "Coming Soon" |
| Document Intelligence | Use existing doc_classifier |
| Context Engine | Fall back to stateless |
| RBAC | Demo as single role |
