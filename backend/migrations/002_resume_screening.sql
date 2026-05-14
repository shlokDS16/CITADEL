-- =====================================================================
-- CITADEL — Resume Screening module — initial migration
-- Run this in: Supabase SQL Editor → New query → Paste → Run
-- Idempotent: safe to re-run.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------
-- 1. Sequential JOB-XXXX counter
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_id_counter (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  current_value INTEGER NOT NULL DEFAULT 2026000
);
INSERT INTO job_id_counter (id, current_value) VALUES (1, 2026000) ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION next_job_code() RETURNS TEXT AS $$
DECLARE next_val INTEGER;
BEGIN
  UPDATE job_id_counter SET current_value = current_value + 1 WHERE id = 1 RETURNING current_value INTO next_val;
  RETURN 'JOB-' || next_val;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------
-- 2. Sequential CAND-XXXX counter
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cand_id_counter (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  current_value INTEGER NOT NULL DEFAULT 1000
);
INSERT INTO cand_id_counter (id, current_value) VALUES (1, 1000) ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION next_cand_code() RETURNS TEXT AS $$
DECLARE next_val INTEGER;
BEGIN
  UPDATE cand_id_counter SET current_value = current_value + 1 WHERE id = 1 RETURNING current_value INTO next_val;
  RETURN 'CAND-' || next_val;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------
-- 3. Jobs
--    `parsed_jd` is the full structured JSON (schema in build prompt §2).
--    `scoring_weights` and `bias_flags` are PER-JOB, not global.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  department TEXT,
  urgency TEXT NOT NULL DEFAULT 'NORMAL',
  status TEXT NOT NULL DEFAULT 'open',
  openings INT NOT NULL DEFAULT 1,
  -- Free-text JD as supplied by HR (or extracted from PDF/DOCX)
  raw_jd_text TEXT,
  -- Structured JD: required_skills, experience, education, location, culture_fit
  parsed_jd JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Per-job scoring + bias config
  scoring_weights JSONB NOT NULL DEFAULT '{"skills":40,"experience":25,"education":15,"location":10,"culture_fit":10}'::jsonb,
  bias_flags JSONB NOT NULL DEFAULT '{"redact_gender":true,"redact_age":true,"redact_location":false,"redact_name":true}'::jsonb,
  auto_shortlist_threshold FLOAT NOT NULL DEFAULT 70.0,
  posted_by TEXT,
  posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_urgency ON jobs(urgency);
CREATE INDEX IF NOT EXISTS idx_jobs_dept ON jobs(department);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs(posted_at DESC);

-- Touch updated_at on edits
DROP TRIGGER IF EXISTS jobs_set_updated_at ON jobs;
CREATE TRIGGER jobs_set_updated_at BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ---------------------------------------------------------------
-- 4. Candidates
--    `parsed_resume` holds full structured JSON from Groq parser.
--    PII (email, phone) stored plaintext for v1 (Supabase encrypted at rest).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

  -- Top-level fields (mirrored from parsed_resume for query convenience)
  name TEXT,
  email TEXT,
  phone TEXT,
  location TEXT,
  total_experience_years FLOAT,
  highest_education TEXT,
  source TEXT DEFAULT 'Direct',

  -- Full structured parse
  parsed_resume JSONB NOT NULL DEFAULT '{}'::jsonb,
  redacted_text TEXT,    -- text actually fed to scorer (post bias-redaction)

  -- Scoring outputs
  final_score FLOAT,
  score_breakdown JSONB,                  -- {skills:82, experience:71, education:90, location:60, culture_fit:75}
  scoring_config_snapshot JSONB,          -- weights+flags actually used (for audit)
  ai_insights JSONB DEFAULT '[]'::jsonb,  -- 4-card analysis
  bias_panel JSONB,                       -- {predicted_gender, predicted_age_band, fairness_diff_pct, ...}

  -- Lifecycle
  status TEXT NOT NULL DEFAULT 'PROCESSING',  -- PROCESSING | SHORTLISTED | REJECTED | INTERVIEW | OFFER | RECRUITED
  rejection_reason TEXT,
  rejection_note TEXT,
  notes JSONB DEFAULT '[]'::jsonb,         -- list of {ts, author, text}

  -- Original CV file
  cv_filename TEXT,
  cv_storage_path TEXT,
  cv_mime TEXT,
  cv_size_bytes BIGINT,

  -- Timestamps for funnel
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  screened_at TIMESTAMPTZ,
  shortlisted_at TIMESTAMPTZ,
  interview_at TIMESTAMPTZ,
  offer_at TIMESTAMPTZ,
  hired_at TIMESTAMPTZ,
  rejected_at TIMESTAMPTZ,
  scheduled_interview_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_candidates_job ON candidates(job_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(final_score DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_applied ON candidates(applied_at DESC);

DROP TRIGGER IF EXISTS candidates_set_updated_at ON candidates;
CREATE TRIGGER candidates_set_updated_at BEFORE UPDATE ON candidates
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ---------------------------------------------------------------
-- 5. Pipeline transitions (audit trail)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_id UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status TEXT NOT NULL,
  actor TEXT,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_cand ON pipeline_history(candidate_id, created_at DESC);

-- ---------------------------------------------------------------
-- 6. Telegram chats (the bot stores discovered chat_ids here)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_chats (
  chat_id TEXT PRIMARY KEY,
  chat_type TEXT,                  -- private | group | supergroup | channel
  title TEXT,
  username TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_message_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------
-- 7. Seed 5 detailed jobs with full parsed_jd JSON
--    These jobs let the user demo the system without writing JDs first.
-- ---------------------------------------------------------------
INSERT INTO jobs (code, title, department, urgency, openings, raw_jd_text, parsed_jd, posted_by) VALUES
(next_job_code(), 'Senior ML Engineer', 'IT / Smart City', 'HIGH', 2,
 'We seek a Senior Machine Learning Engineer to design and ship production ML systems for civic data — traffic prediction, anomaly detection, and document understanding. You will own model lifecycle from research to deployment, partner with data engineers, and mentor juniors. 5+ years industry ML experience required.',
 '{
   "title": "Senior ML Engineer",
   "department": "IT / Smart City",
   "summary": "Own end-to-end ML systems for civic intelligence: traffic prediction, anomaly detection, document understanding.",
   "required_skills": {
     "must_have": ["Python", "PyTorch", "Scikit-learn", "Production ML", "Docker"],
     "nice_to_have": ["Kubernetes", "MLOps", "Computer Vision", "NLP", "AWS Sagemaker"],
     "minimum_match_percent": 60
   },
   "experience": {
     "min_years": 5, "max_years": 12,
     "preferred_titles": ["Senior ML Engineer", "Machine Learning Engineer", "AI Engineer", "Data Scientist"],
     "preferred_industries": ["Technology", "Finance", "Government", "Research"]
   },
   "education": {
     "minimum_level": "bachelors",
     "preferred_fields": ["Computer Science", "Machine Learning", "Statistics", "Mathematics"],
     "gpa_threshold": null
   },
   "location": {
     "preferred_cities": ["Bengaluru", "Hyderabad", "Pune"],
     "remote_ok": true, "relocation_ok": true
   },
   "culture_fit": {
     "keywords": ["ownership", "research-minded", "production-focused", "mentorship", "ship velocity"],
     "values": ["public service", "rigor", "intellectual humility"]
   }
 }'::jsonb, 'RSD'),

(next_job_code(), 'Urban Planner', 'City Planning', 'NORMAL', 1,
 'Urban Planner with expertise in smart-city design, transit-oriented development, and stakeholder engagement. You will lead master-plan revisions and run public consultations across 3 wards.',
 '{
   "title": "Urban Planner",
   "department": "City Planning",
   "summary": "Lead master-plan revisions and public consultations for 3 wards. Smart-city + TOD focus.",
   "required_skills": {
     "must_have": ["GIS", "AutoCAD", "Master Planning", "Public Consultation", "Stakeholder Management"],
     "nice_to_have": ["BIM", "QGIS", "Land-use Modelling", "Climate Adaptation"],
     "minimum_match_percent": 55
   },
   "experience": {
     "min_years": 3, "max_years": 10,
     "preferred_titles": ["Urban Planner", "Town Planner", "City Planner", "Planning Consultant"],
     "preferred_industries": ["Government", "Architecture", "Consulting"]
   },
   "education": {
     "minimum_level": "masters",
     "preferred_fields": ["Urban Planning", "Architecture", "Civil Engineering", "Geography"]
   },
   "location": {
     "preferred_cities": ["Bengaluru"],
     "remote_ok": false, "relocation_ok": true
   },
   "culture_fit": {
     "keywords": ["empathy", "consensus building", "long-term thinking", "field work"],
     "values": ["public service", "equity", "sustainability"]
   }
 }'::jsonb, 'RSD'),

(next_job_code(), 'Data Analyst (Traffic)', 'Traffic Management', 'NORMAL', 3,
 'Data Analyst for the city traffic command centre. You will build dashboards in Power BI / Metabase, write SQL against our incident DB, and run statistical analyses on congestion patterns. 2+ years experience.',
 '{
   "title": "Data Analyst (Traffic)",
   "department": "Traffic Management",
   "summary": "Build dashboards and run statistical analyses on congestion patterns at the city traffic command centre.",
   "required_skills": {
     "must_have": ["SQL", "Power BI", "Python", "Statistical Analysis", "Excel"],
     "nice_to_have": ["Tableau", "Metabase", "Pandas", "Time Series Analysis", "Geospatial"],
     "minimum_match_percent": 60
   },
   "experience": {
     "min_years": 2, "max_years": 6,
     "preferred_titles": ["Data Analyst", "Business Analyst", "BI Analyst"],
     "preferred_industries": ["Transportation", "Government", "Logistics", "Finance"]
   },
   "education": {
     "minimum_level": "bachelors",
     "preferred_fields": ["Statistics", "Computer Science", "Economics", "Mathematics", "Data Science"]
   },
   "location": {
     "preferred_cities": ["Bengaluru", "Mumbai", "Delhi"],
     "remote_ok": false, "relocation_ok": true
   },
   "culture_fit": {
     "keywords": ["curious", "structured thinking", "communication", "self-starter"],
     "values": ["public service", "evidence-based"]
   }
 }'::jsonb, 'RSD'),

(next_job_code(), 'Civil Engineer', 'PWD', 'NORMAL', 4,
 'Civil Engineer for the Public Works Department covering roads, drainage, and pedestrian infrastructure projects across the eastern division. Site supervision + contract management. 4+ years required.',
 '{
   "title": "Civil Engineer",
   "department": "PWD",
   "summary": "Roads, drainage, pedestrian infra projects across the eastern division. Site supervision + contract management.",
   "required_skills": {
     "must_have": ["Civil Engineering", "Site Supervision", "AutoCAD", "Contract Management", "PWD Codes"],
     "nice_to_have": ["BIM", "STAAD Pro", "Project Management", "Quality Assurance"],
     "minimum_match_percent": 60
   },
   "experience": {
     "min_years": 4, "max_years": 15,
     "preferred_titles": ["Civil Engineer", "Site Engineer", "Project Engineer", "Construction Manager"],
     "preferred_industries": ["Government", "Construction", "Infrastructure"]
   },
   "education": {
     "minimum_level": "bachelors",
     "preferred_fields": ["Civil Engineering", "Construction Management"]
   },
   "location": {
     "preferred_cities": ["Bengaluru"],
     "remote_ok": false, "relocation_ok": true
   },
   "culture_fit": {
     "keywords": ["site presence", "discipline", "safety-first", "vendor management"],
     "values": ["public service", "integrity", "quality"]
   }
 }'::jsonb, 'RSD'),

(next_job_code(), 'Security Architect', 'IT / InfoSec', 'HIGH', 1,
 'Security Architect to design and review the security posture of CITADEL platform — threat modelling, secure-by-design reviews, IAM hardening, and incident response playbooks. 7+ years infosec experience required.',
 '{
   "title": "Security Architect",
   "department": "IT / InfoSec",
   "summary": "Threat modelling, secure-by-design reviews, IAM hardening, and incident response for the CITADEL platform.",
   "required_skills": {
     "must_have": ["Threat Modeling", "OWASP", "IAM", "Cloud Security", "Incident Response"],
     "nice_to_have": ["AWS Security", "Kubernetes Security", "Zero Trust", "PenTest", "ISO 27001"],
     "minimum_match_percent": 65
   },
   "experience": {
     "min_years": 7, "max_years": 20,
     "preferred_titles": ["Security Architect", "Principal Security Engineer", "InfoSec Lead", "CISO"],
     "preferred_industries": ["Technology", "Finance", "Government", "Defense"]
   },
   "education": {
     "minimum_level": "bachelors",
     "preferred_fields": ["Computer Science", "Cybersecurity", "Information Systems"]
   },
   "location": {
     "preferred_cities": ["Bengaluru", "Hyderabad", "Pune", "Delhi"],
     "remote_ok": true, "relocation_ok": true
   },
   "culture_fit": {
     "keywords": ["adversarial mindset", "documentation", "calm under pressure", "cross-team comms"],
     "values": ["public service", "integrity", "rigor"]
   }
 }'::jsonb, 'RSD')
ON CONFLICT (code) DO NOTHING;

-- =====================================================================
-- DONE.  Verify with:
--   SELECT count(*) FROM jobs;                  -- expect ≥ 5
--   SELECT next_job_code();                     -- next code
--   SELECT count(*) FROM candidates;            -- expect 0
-- =====================================================================
