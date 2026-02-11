# C.I.T.A.D.E.L. Rollback Plan

## Backup Location
All pre-modification files are stored in: `.tmp/backups/[filename]_[timestamp].py`

---

## Rollback Procedures

### If RBAC Middleware Breaks Auth
```bash
# Remove middleware from main.py
# Restore original main.py from backup
cp .tmp/backups/main_*.py backend/main.py
uvicorn main:app --reload
```

### If Context Engine Causes Errors
```bash
# Disable context injection in services
# Services should fall back to stateless operation
```

### If New Module Crashes Server
```bash
# Comment out router registration in main.py
# Restart server
# Mark module as "Disabled" in CRITICAL_FIXES.md
```

### If Supabase Tables Cause Conflicts
```sql
-- Drop new tables only (preserve existing)
DROP TABLE IF EXISTS user_profiles CASCADE;
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS ai_audit_logs CASCADE;
-- Note: Keep existing tables (documents, vectors, etc.)
```

---

## Priority Fallback Order
If time runs out, disable modules in this order (least to most critical):
1. Traffic Violations (newest, most complex)
2. Document Intelligence (can demo with existing doc_classifier)
3. Context Engine (fall back to stateless)
4. RBAC (demo as single-role if needed)

**Core modules that MUST work:**
- RAG Chatbot
- Fake News Detection
- Anomaly Detection
- Expense OCR
- Resume Screening
