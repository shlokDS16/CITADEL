"""
Citizen Assistant — CITADEL Citizen Portal Module 1.

A vectorless, reasoning-based RAG chatbot built on the self-hosted
PageIndex framework (https://github.com/VectifyAI/PageIndex), powered by
Groq (LiteLLM). It builds hierarchical "table-of-contents" trees from a
citizen knowledge corpus and reasons over them with tree-search instead
of vector similarity.

Answer pipeline (every query):
  1. OCR uploaded file (if any) -> markdown                (OCR.Space)
  2. PageIndex reasoning tree-search over the corpus       (Groq)
  3. External web search to improvise / fill gaps          (keyless DDG)
  -> language-matched, citizen-access-guarded answer
"""
from app.modules.citizen_assistant.router import router  # noqa: F401
