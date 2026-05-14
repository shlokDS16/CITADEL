-- =====================================================================
-- CITADEL — Document Intelligence module — initial migration
-- Run this in: Supabase Dashboard → SQL Editor → New query → Paste → Run
-- Idempotent: safe to re-run.
-- =====================================================================

-- 0. Extensions ------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;


-- 1. Sequential DOC-ID counter --------------------------------------
CREATE TABLE IF NOT EXISTS doc_id_counter (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  current_value INTEGER NOT NULL DEFAULT 2840
);

INSERT INTO doc_id_counter (id, current_value)
VALUES (1, 2840)
ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION next_doc_id() RETURNS TEXT AS $$
DECLARE
  next_val INTEGER;
BEGIN
  UPDATE doc_id_counter
  SET current_value = current_value + 1
  WHERE id = 1
  RETURNING current_value INTO next_val;
  RETURN 'DOC-' || next_val;
END;
$$ LANGUAGE plpgsql;


-- 2. Templates table -------------------------------------------------
CREATE TABLE IF NOT EXISTS templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  document_type TEXT NOT NULL,
  fields JSONB NOT NULL,                 -- [{name, type, required, ...}, ...]
  is_system BOOLEAN NOT NULL DEFAULT FALSE,
  avg_accuracy FLOAT NOT NULL DEFAULT 0,
  docs_processed INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_templates_type_name
  ON templates(document_type, name);


-- 3. Documents table -------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id TEXT UNIQUE NOT NULL,            -- DOC-2847 (sequential)
  batch_id UUID,
  filename TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  document_type TEXT NOT NULL,
  detected_type TEXT,                     -- if auto-detect was used
  status TEXT NOT NULL DEFAULT 'PROCESSING',  -- PROCESSING | PENDING_REVIEW | APPROVED | REJECTED | ARCHIVED
  priority TEXT NOT NULL DEFAULT 'normal',    -- low | normal | high | urgent
  confidence FLOAT,
  language TEXT NOT NULL DEFAULT 'en',        -- en | hi | en+hi

  -- Extracted content
  extracted_text TEXT,
  redacted_text TEXT,
  extracted_fields JSONB,                 -- template-mapped fields

  -- PII
  pii_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  pii_results JSONB,                      -- {type: {count, status, confidence, positions}}
  pii_count INTEGER NOT NULL DEFAULT 0,

  -- Signature
  signature_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  signature_status TEXT,                  -- detected | not_found | unclear

  -- Metadata
  tags TEXT[] NOT NULL DEFAULT '{}',
  department TEXT,
  title TEXT,
  uploaded_by TEXT,
  file_size_bytes BIGINT,
  mime_type TEXT,
  storage_path TEXT,                      -- path in `documents` bucket
  processed_storage_path TEXT,            -- path in `processed` bucket

  -- Timestamps
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  approved_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ,
  rejected_at TIMESTAMPTZ,

  -- SLA flag
  sla_breached BOOLEAN NOT NULL DEFAULT FALSE,

  -- Template linkage
  template_id UUID REFERENCES templates(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_priority ON documents(priority);
CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_documents_doc_id ON documents(doc_id);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_archived_at ON documents(archived_at DESC);


-- 4. Document chunks table (RAG vector index) -----------------------
CREATE TABLE IF NOT EXISTS document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT NOT NULL,
  embedding vector(384),                  -- bge-small-en-v1.5
  document_type TEXT,
  tags TEXT[],
  department TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);


-- 5. Audit log table ------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  action TEXT NOT NULL,                   -- uploaded | processed | pii_detected | approved | rejected | archived | reassigned | edited
  details JSONB,
  performed_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_document ON audit_log(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at DESC);


-- 6. Users table (for passport key system) --------------------------
-- Lightweight — we mostly lean on Supabase Auth for the "real" auth,
-- but the passport key is a project-specific second-factor used by Templates.
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE,
  display_name TEXT,
  passport_key_hash TEXT,                 -- bcrypt
  passport_key_shown BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- 7. Seed default templates -----------------------------------------
INSERT INTO templates (name, document_type, fields, is_system) VALUES
  ('Default Invoice', 'invoice', '[
    {"name": "vendor_name", "type": "string", "required": true},
    {"name": "invoice_number", "type": "string", "required": true},
    {"name": "date", "type": "date", "required": true},
    {"name": "due_date", "type": "date", "required": false},
    {"name": "line_items", "type": "array", "required": false},
    {"name": "subtotal", "type": "currency", "required": false},
    {"name": "tax", "type": "currency", "required": false},
    {"name": "total", "type": "currency", "required": true},
    {"name": "payment_terms", "type": "string", "required": false},
    {"name": "bank_details", "type": "string", "required": false},
    {"name": "gst_number", "type": "string", "required": false},
    {"name": "currency", "type": "string", "required": false}
  ]'::jsonb, FALSE),

  ('Default Contract', 'contract', '[
    {"name": "party_a", "type": "string", "required": true},
    {"name": "party_b", "type": "string", "required": true},
    {"name": "effective_date", "type": "date", "required": true},
    {"name": "expiry_date", "type": "date", "required": false},
    {"name": "terms", "type": "text", "required": false},
    {"name": "clauses", "type": "array", "required": false},
    {"name": "signatures", "type": "array", "required": false},
    {"name": "witness", "type": "string", "required": false},
    {"name": "jurisdiction", "type": "string", "required": false},
    {"name": "contract_value", "type": "currency", "required": false},
    {"name": "penalty_clause", "type": "text", "required": false},
    {"name": "renewal_terms", "type": "text", "required": false},
    {"name": "governing_law", "type": "string", "required": false},
    {"name": "dispute_resolution", "type": "text", "required": false},
    {"name": "confidentiality", "type": "text", "required": false},
    {"name": "termination", "type": "text", "required": false},
    {"name": "obligations_a", "type": "text", "required": false},
    {"name": "obligations_b", "type": "text", "required": false}
  ]'::jsonb, FALSE),

  ('Default Permit', 'permit', '[
    {"name": "permit_number", "type": "string", "required": true},
    {"name": "issued_to", "type": "string", "required": true},
    {"name": "issued_by", "type": "string", "required": true},
    {"name": "valid_from", "type": "date", "required": true},
    {"name": "valid_until", "type": "date", "required": true},
    {"name": "permit_type", "type": "string", "required": false},
    {"name": "conditions", "type": "text", "required": false},
    {"name": "authority_seal", "type": "boolean", "required": false},
    {"name": "jurisdiction", "type": "string", "required": false}
  ]'::jsonb, FALSE),

  ('Default ID Document', 'id_document', '[
    {"name": "full_name", "type": "string", "required": true},
    {"name": "id_number", "type": "string", "required": true},
    {"name": "date_of_birth", "type": "date", "required": true},
    {"name": "address", "type": "string", "required": false},
    {"name": "photo_present", "type": "boolean", "required": false},
    {"name": "issue_date", "type": "date", "required": false},
    {"name": "expiry_date", "type": "date", "required": false}
  ]'::jsonb, TRUE),

  ('Default Receipt', 'receipt', '[
    {"name": "receipt_number", "type": "string", "required": true},
    {"name": "date", "type": "date", "required": true},
    {"name": "received_from", "type": "string", "required": true},
    {"name": "amount", "type": "currency", "required": true},
    {"name": "payment_method", "type": "string", "required": false},
    {"name": "purpose", "type": "string", "required": false},
    {"name": "received_by", "type": "string", "required": false},
    {"name": "signature", "type": "boolean", "required": false}
  ]'::jsonb, FALSE),

  ('Default Affidavit', 'affidavit', '[
    {"name": "deponent_name", "type": "string", "required": true},
    {"name": "date", "type": "date", "required": true},
    {"name": "court", "type": "string", "required": false},
    {"name": "case_number", "type": "string", "required": false},
    {"name": "sworn_before", "type": "string", "required": false},
    {"name": "notary", "type": "string", "required": false},
    {"name": "content_summary", "type": "text", "required": false},
    {"name": "witness_1", "type": "string", "required": false},
    {"name": "witness_2", "type": "string", "required": false},
    {"name": "stamp_value", "type": "currency", "required": false},
    {"name": "jurisdiction", "type": "string", "required": false}
  ]'::jsonb, FALSE),

  ('Default Tender', 'tender_notice', '[
    {"name": "tender_number", "type": "string", "required": true},
    {"name": "issuing_authority", "type": "string", "required": true},
    {"name": "title", "type": "string", "required": true},
    {"name": "submission_deadline", "type": "date", "required": true},
    {"name": "earnest_money", "type": "currency", "required": false},
    {"name": "eligibility", "type": "text", "required": false},
    {"name": "scope", "type": "text", "required": false},
    {"name": "contact_person", "type": "string", "required": false},
    {"name": "published_date", "type": "date", "required": false}
  ]'::jsonb, FALSE),

  ('Default Certificate', 'certificate', '[
    {"name": "certificate_type", "type": "string", "required": true},
    {"name": "issued_to", "type": "string", "required": true},
    {"name": "issued_by", "type": "string", "required": true},
    {"name": "date", "type": "date", "required": true},
    {"name": "registration_number", "type": "string", "required": false},
    {"name": "valid_until", "type": "date", "required": false},
    {"name": "purpose", "type": "string", "required": false}
  ]'::jsonb, FALSE),

  ('Default Government Permit', 'government_permit', '[
    {"name": "permit_id", "type": "string", "required": true},
    {"name": "department", "type": "string", "required": true},
    {"name": "applicant", "type": "string", "required": true},
    {"name": "approved_by", "type": "string", "required": false},
    {"name": "conditions", "type": "text", "required": false},
    {"name": "valid_from", "type": "date", "required": true},
    {"name": "valid_until", "type": "date", "required": true},
    {"name": "zone", "type": "string", "required": false}
  ]'::jsonb, FALSE),

  ('Default Report', 'report', '[
    {"name": "title", "type": "string", "required": true},
    {"name": "author", "type": "string", "required": false},
    {"name": "department", "type": "string", "required": false},
    {"name": "date", "type": "date", "required": false},
    {"name": "summary", "type": "text", "required": false},
    {"name": "findings", "type": "text", "required": false},
    {"name": "recommendations", "type": "text", "required": false},
    {"name": "attachments_count", "type": "integer", "required": false}
  ]'::jsonb, FALSE)

ON CONFLICT (document_type, name) DO NOTHING;


-- 8. Helper view: pending review queue with computed time_ago/sla ----
CREATE OR REPLACE VIEW v_queue AS
SELECT
  d.*,
  EXTRACT(EPOCH FROM (NOW() - d.created_at)) AS seconds_in_queue,
  CASE
    WHEN d.priority = 'urgent' AND (NOW() - d.created_at) > INTERVAL '15 minutes' THEN TRUE
    WHEN d.priority = 'high'   AND (NOW() - d.created_at) > INTERVAL '1 hour'      THEN TRUE
    WHEN d.priority = 'normal' AND (NOW() - d.created_at) > INTERVAL '4 hours'     THEN TRUE
    WHEN d.priority = 'low'    AND (NOW() - d.created_at) > INTERVAL '24 hours'    THEN TRUE
    ELSE FALSE
  END AS computed_sla_breached
FROM documents d;


-- 9. Updated_at trigger for templates -------------------------------
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS templates_set_updated_at ON templates;
CREATE TRIGGER templates_set_updated_at
  BEFORE UPDATE ON templates
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =====================================================================
-- DONE. Verify with:
--   SELECT count(*) FROM templates;        -- expect 10
--   SELECT next_doc_id();                  -- expect DOC-2841
--   SELECT count(*) FROM documents;        -- expect 0
-- =====================================================================
