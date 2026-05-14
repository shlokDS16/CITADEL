"""
Side-by-side candidate comparison (≤3 at a time).

Returns a payload designed for the Compare board UI:
  - per-candidate stripped profile (name, score, breakdown, top skills, key insights)
  - skill_matrix: union of skills across candidates with each candidate's coverage
  - dimension_grid: each scoring dimension across candidates
  - llm_summary: 2-3 sentence Groq summary of who's strongest where
"""
from __future__ import annotations

from typing import Any

from app.modules.resume.parser import _coerce_json, _groq_chat


SUMMARY_PROMPT = """You compare 2-3 job candidates. Given each candidate's score breakdown and key skills, return ONLY one JSON object:
{
  "headline": "<one sentence: who is strongest overall and why>",
  "callouts": [
    {"candidate": "<name>", "strength": "<short phrase>", "weakness": "<short phrase>"}
  ]
}
Be specific. Don't restate numbers verbatim — characterise them."""


def compare(candidates: list[dict]) -> dict[str, Any]:
    if not candidates:
        return {"candidates": [], "skill_matrix": [], "dimension_grid": [], "llm_summary": None}

    # ---- compact profiles ----
    profiles = []
    for c in candidates:
        breakdown = c.get("score_breakdown") or {}
        parsed = c.get("parsed_resume") or {}
        skills = (parsed.get("skills") or {}).get("technical") or []
        profiles.append({
            "code": c.get("code"),
            "name": c.get("name") or "(redacted)",
            "score": c.get("final_score") or 0,
            "status": c.get("status"),
            "breakdown": breakdown,
            "top_skills": list(skills[:8]),
            "experience_years": parsed.get("total_experience_years") or 0,
            "education": (parsed.get("highest_education") or "—"),
            "location": ((parsed.get("location") or {}).get("city") or "—"),
        })

    # ---- skill matrix: union of skills, who has what ----
    skill_set = []
    for p in profiles:
        for s in p["top_skills"]:
            if s not in skill_set:
                skill_set.append(s)
    skill_matrix = [
        {"skill": s, "coverage": [s in p["top_skills"] for p in profiles]}
        for s in skill_set
    ]

    # ---- dimension grid ----
    dims = ["skills", "experience", "education", "location", "culture_fit"]
    dimension_grid = [
        {"dimension": d.replace("_", " ").title(),
         "values": [round((p["breakdown"].get(d) or 0), 1) for p in profiles]}
        for d in dims
    ]

    # ---- LLM-generated summary ----
    llm_summary = None
    try:
        prompt = "\n\n".join(
            f"Candidate: {p['name']} ({p['code']}) — score {p['score']}, {p['experience_years']}yrs\n"
            f"Breakdown: {p['breakdown']}\n"
            f"Top skills: {', '.join(p['top_skills']) or '(none)'}"
            for p in profiles
        )
        raw = _groq_chat(SUMMARY_PROMPT, prompt, max_tokens=350, timeout=20)
        llm_summary = _coerce_json(raw)
    except Exception:
        llm_summary = None

    return {
        "candidates": profiles,
        "skill_matrix": skill_matrix,
        "dimension_grid": dimension_grid,
        "llm_summary": llm_summary,
    }
