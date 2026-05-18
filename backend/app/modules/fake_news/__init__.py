"""
Fake News Detector — CITADEL Citizen Module 2.

Production-grade, multi-layered misinformation analysis:

  L1  Heuristics / RegEx + hash & near-dup match  (heuristics.py + adversarial.py)
  L2  Fast transformer classifiers                 (pipeline.py)
  L3  RAG fact-check + NLI claim verification       (fact_check.py)
  L3+ LLM rationale, high-risk only (Groq)          (llm_rationale.py)
  Multi-modal deepfake / AI-image forensics         (media_forensics.py)
  CIB / propagation analysis (ingest-fed)           (propagation.py)
  HITL review + feedback loop + concept drift       (service.py + drift.py)

Contract: docs/module-specs/06-fake-news-detector.md  (base path /api/v1/fake-news).
Built phase-by-phase — see tasks/todo.md.
"""
from app.modules.fake_news.router import router  # noqa: F401
