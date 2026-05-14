"""
5-dimension scoring engine. Each dimension returns 0..100; final = weighted sum.

Public:
  - score_candidate(parsed_resume, parsed_jd, weights, bias_flags, redacted_text)
      → {"final_score", "breakdown", "auto_action_blocked", "skills_matched", "skills_missing"}

Embedding for skill semantic match comes from `app.modules.document_intelligence.indexer`
(BGE-small via fastembed, hash-stub fallback).
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from app.modules.document_intelligence.indexer import _embedder
from app.modules.resume.parser import _groq_chat

log = logging.getLogger("citadel.resume.scorer")

EDUCATION_LEVELS = {"none": 0, "diploma": 40, "bachelors": 60, "masters": 80, "phd": 100}
EDU_RANK = {"none": 0, "diploma": 1, "bachelors": 2, "masters": 3, "phd": 4}

# Cosine similarity thresholds (tuned for hash-stub embedder which produces
# very low similarities; with BGE these would be ~0.75 / 0.65).
MUST_MATCH_THRESHOLD = 0.55
NICE_MATCH_THRESHOLD = 0.40


# ---------------------------------------------------------------
# Cosine helpers (use the existing embedder lazily)
# ---------------------------------------------------------------
def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b: return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    try:
        return _embedder().embed(texts)
    except Exception as e:
        log.warning("Embedder failed (%s) — returning zero vectors", e)
        return [[0.0] * 384 for _ in texts]


# ---------------------------------------------------------------
# Skills score
# ---------------------------------------------------------------
def _skills_score(parsed_resume: dict, parsed_jd: dict) -> tuple[float, list[str], list[str]]:
    rs = (parsed_jd.get("required_skills") or {})
    must = [s.strip() for s in (rs.get("must_have") or []) if s.strip()]
    nice = [s.strip() for s in (rs.get("nice_to_have") or []) if s.strip()]

    cand_skills_d = (parsed_resume.get("skills") or {})
    cand_skills = list({*(cand_skills_d.get("technical") or []),
                        *(cand_skills_d.get("certifications") or [])})
    cand_skills = [s.strip() for s in cand_skills if s and s.strip()]

    if not must and not nice:
        return 50.0, [], []
    if not cand_skills:
        return 0.0, [], must

    # Embed everything once
    all_skills = must + nice + cand_skills
    embeds = _embed(all_skills)
    must_e = embeds[: len(must)]
    nice_e = embeds[len(must): len(must) + len(nice)]
    cand_e = embeds[len(must) + len(nice):]

    matched_must, matched_nice = [], []
    missing_must = []
    for i, m in enumerate(must):
        best = max((_cosine(must_e[i], ce) for ce in cand_e), default=0.0)
        # Also accept exact lower-case substring match
        if best >= MUST_MATCH_THRESHOLD or any(m.lower() in c.lower() or c.lower() in m.lower() for c in cand_skills):
            matched_must.append(m)
        else:
            missing_must.append(m)
    for i, n in enumerate(nice):
        best = max((_cosine(nice_e[i], ce) for ce in cand_e), default=0.0)
        if best >= NICE_MATCH_THRESHOLD or any(n.lower() in c.lower() or c.lower() in n.lower() for c in cand_skills):
            matched_nice.append(n)

    must_pct = (len(matched_must) / len(must)) if must else 0.0
    nice_pct = (len(matched_nice) / len(nice)) if nice else 0.0
    score = round(must_pct * 70 + nice_pct * 30, 2)
    return score, matched_must + matched_nice, missing_must


# ---------------------------------------------------------------
# Experience score
# ---------------------------------------------------------------
def _experience_score(parsed_resume: dict, parsed_jd: dict) -> float:
    ex_jd = parsed_jd.get("experience") or {}
    min_y = float(ex_jd.get("min_years") or 0)
    max_y = float(ex_jd.get("max_years") or 0)
    titles_pref = ex_jd.get("preferred_titles") or []
    inds_pref = [s.lower() for s in (ex_jd.get("preferred_industries") or [])]

    cand_years = float(parsed_resume.get("total_experience_years") or 0)
    work = parsed_resume.get("work_experience") or []
    cand_titles = [w.get("title") or "" for w in work]
    cand_companies = " ".join(((w.get("company") or "") for w in work)).lower()

    # Years sub-score (max 60)
    if min_y == 0 and max_y == 0:
        years_score = 30  # no constraint → neutral
    elif cand_years < min_y:
        years_score = max(0, 60 * (cand_years / min_y)) if min_y else 0
    elif max_y and cand_years > max_y:
        years_score = max(40, 60 - (cand_years - max_y) * 2)   # over-qualified soft penalty
    else:
        years_score = 60

    # Title relevance (max 25)
    title_score = 0
    if titles_pref and cand_titles:
        all_t = titles_pref + [t for t in cand_titles if t]
        embeds = _embed(all_t)
        pref_e = embeds[: len(titles_pref)]
        cand_e = embeds[len(titles_pref):]
        sims = [max((_cosine(pe, ce) for ce in cand_e), default=0.0) for pe in pref_e]
        avg = sum(sims) / len(sims) if sims else 0
        title_score = min(25, max(0, avg * 30))

    # Industry relevance (max 15) — keyword in any company description
    ind_score = 0
    for ind in inds_pref:
        if ind in cand_companies:
            ind_score = 15
            break

    return round(years_score + title_score + ind_score, 2)


# ---------------------------------------------------------------
# Education score
# ---------------------------------------------------------------
def _education_score(parsed_resume: dict, parsed_jd: dict) -> float:
    edu_jd = parsed_jd.get("education") or {}
    min_lvl = (edu_jd.get("minimum_level") or "bachelors").lower()
    pref_fields = [f.lower() for f in (edu_jd.get("preferred_fields") or [])]
    gpa_threshold = edu_jd.get("gpa_threshold")

    cand_edu = parsed_resume.get("education") or []
    if not cand_edu:
        return 20  # no education declared

    # Pick the highest-level degree found
    cand_levels = []
    for e in cand_edu:
        deg = (e.get("degree") or "").lower()
        if "phd" in deg or "doctor" in deg:
            cand_levels.append("phd")
        elif "master" in deg or "m.s" in deg or "m.tech" in deg or "mba" in deg:
            cand_levels.append("masters")
        elif "bachelor" in deg or "b.tech" in deg or "b.e" in deg or "b.com" in deg or "b.sc" in deg:
            cand_levels.append("bachelors")
        elif "diploma" in deg:
            cand_levels.append("diploma")
        else:
            cand_levels.append("none")
    cand_lvl = max(cand_levels, key=lambda x: EDU_RANK.get(x, 0)) if cand_levels else "none"

    base = 50 if EDU_RANK.get(cand_lvl, 0) >= EDU_RANK.get(min_lvl, 0) else 30 * EDU_RANK.get(cand_lvl, 0) / max(EDU_RANK.get(min_lvl, 1), 1)

    # Field relevance (max 30)
    field_score = 0
    cand_fields = [(e.get("field") or "").lower() for e in cand_edu if e.get("field")]
    if pref_fields and cand_fields:
        if any(any(pf in cf or cf in pf for pf in pref_fields) for cf in cand_fields):
            field_score = 30
        else:
            # fallback: embedding similarity
            all_f = pref_fields + cand_fields
            embeds = _embed(all_f)
            pref_e = embeds[: len(pref_fields)]
            cand_e = embeds[len(pref_fields):]
            sims = [max((_cosine(pe, ce) for ce in cand_e), default=0.0) for pe in pref_e]
            field_score = min(30, max(0, (sum(sims) / len(sims)) * 40)) if sims else 0
    elif not pref_fields:
        field_score = 15  # no constraint → partial

    # GPA bonus (max 20)
    gpa_score = 0
    if gpa_threshold is not None:
        for e in cand_edu:
            try:
                if float(e.get("gpa") or 0) >= float(gpa_threshold):
                    gpa_score = 20
                    break
            except Exception:
                continue
    else:
        gpa_score = 10  # no requirement → small bonus

    return round(min(100.0, base + field_score + gpa_score), 2)


# ---------------------------------------------------------------
# Location score
# ---------------------------------------------------------------
def _location_score(parsed_resume: dict, parsed_jd: dict, redacted: bool) -> float:
    if redacted:
        return 50.0
    loc_jd = parsed_jd.get("location") or {}
    cities = [c.lower() for c in (loc_jd.get("preferred_cities") or [])]
    remote_ok = bool(loc_jd.get("remote_ok"))
    relocate_ok = bool(loc_jd.get("relocation_ok"))

    cand_loc = (parsed_resume.get("location") or {})
    city = (cand_loc.get("city") or "").lower()
    state = (cand_loc.get("state") or "").lower()
    summary = (parsed_resume.get("summary") or "").lower()

    if city and city in cities:
        return 100.0
    # Same state heuristic — not enough data; treat any preferred city in state as 70
    if state and any(state in c for c in cities):
        return 70.0
    if remote_ok and ("remote" in summary or "work from home" in summary):
        return 90.0
    if relocate_ok:
        return 50.0
    return 20.0


# ---------------------------------------------------------------
# Culture-fit score (Groq)
# ---------------------------------------------------------------
CULTURE_PROMPT = """You assess organisational culture fit. You will be given:
- A list of cultural keywords + values from the job description.
- A short candidate summary + work descriptions.

Return ONLY a JSON object: {"score": <0-100 integer>, "reasoning": "<one sentence>"}.

Score 0-100 based on whether the candidate's language patterns, leadership signals, volunteering, and accomplishments align with the listed culture. Be strict — generic resumes score 50-60, strong alignment scores 80+, weak alignment scores under 40."""


def _culture_score(parsed_resume: dict, parsed_jd: dict) -> tuple[float, str]:
    cf = parsed_jd.get("culture_fit") or {}
    keywords = cf.get("keywords") or []
    values = cf.get("values") or []
    if not keywords and not values:
        return 60.0, "No culture criteria provided — neutral score."

    summary = parsed_resume.get("summary") or ""
    work_desc = " ".join(
        (" | ".join(w.get("responsibilities") or []) for w in (parsed_resume.get("work_experience") or []))
    )[:2000]
    user = (
        f"Cultural keywords: {', '.join(keywords)}\n"
        f"Values: {', '.join(values)}\n\n"
        f"Candidate summary: {summary or '(none)'}\n\n"
        f"Work descriptions: {work_desc or '(none)'}"
    )
    try:
        import json as _json
        from app.modules.resume.parser import _coerce_json
        raw = _groq_chat(CULTURE_PROMPT, user, max_tokens=200, timeout=20)
        data = _coerce_json(raw)
        score = float(data.get("score") or 50)
        reasoning = str(data.get("reasoning") or "")
        return max(0.0, min(100.0, score)), reasoning
    except Exception as e:
        log.warning("culture_score Groq call failed: %s", e)
        return 60.0, "(fallback) Could not run culture analysis — assigned neutral 60."


# ---------------------------------------------------------------
# Bias panel — predicted attributes (only for surfacing, NEVER feeds score)
# ---------------------------------------------------------------
def predict_bias_panel(parsed_resume: dict, redacted_text: str) -> dict:
    """Light heuristics for the per-candidate bias panel surfaced in the UI.
    Predictions are derived from the original (unredacted) text but the SCORE
    itself is calculated from the redacted version. We use the predictions ONLY
    to display 'we noticed signals in this category' for the human reviewer.
    """
    name = (parsed_resume.get("name") or "").strip()
    # Name-gender heuristic (very rough; final answer is "unknown" for ambiguous names)
    male_endings = re.compile(r"(esh|eep|it|ar|kumar|raj|an|av|in|on|am)$", re.IGNORECASE)
    female_endings = re.compile(r"(a|i|ya|priya|kumari|sha|sa|ina)$", re.IGNORECASE)
    first = name.split()[0] if name else ""
    if first and female_endings.search(first):
        gender, gconf = "female", 0.70
    elif first and male_endings.search(first):
        gender, gconf = "male", 0.70
    else:
        gender, gconf = "unknown", 0.50

    # Age band from total_experience_years
    yrs = float(parsed_resume.get("total_experience_years") or 0)
    if yrs < 3:
        age_band = "<25"
    elif yrs < 8:
        age_band = "25-34"
    elif yrs < 18:
        age_band = "35-44"
    elif yrs >= 18:
        age_band = "45+"
    else:
        age_band = "unknown"

    # School tier from highest education institution name (heuristic)
    institutions = " ".join(((e.get("institution") or "") for e in (parsed_resume.get("education") or []))).lower()
    if any(t in institutions for t in ["iit", "iim", "iisc", "nit", "bits"]):
        tier = "tier1"
    elif any(t in institutions for t in ["university", "college"]):
        tier = "tier2"
    else:
        tier = "unknown"

    # auto_action_blocked: block when predicted gender confidence high AND
    # the candidate is over the auto-shortlist threshold (caller decides)
    return {
        "predicted_gender": gender, "predicted_gender_conf": gconf,
        "predicted_age_band": age_band,
        "school_tier_estimate": tier,
        "fairness_diff_pct": 0.0,        # will be recomputed across the cohort by analyzer
        "auto_action_blocked": gconf > 0.85,
        "redacted_attributes": [],       # filled in by orchestrator
    }


# ---------------------------------------------------------------
# Public scoring orchestrator
# ---------------------------------------------------------------
def score_candidate(
    parsed_resume: dict,
    parsed_jd: dict,
    weights: dict,
    bias_flags: dict,
) -> dict[str, Any]:
    """Returns {final_score, breakdown, ai_insights, skills_matched, skills_missing, bias_panel, culture_reasoning}."""
    weights = weights or {}
    bias_flags = bias_flags or {}

    skills_pts, matched, missing = _skills_score(parsed_resume, parsed_jd)
    exp_pts = _experience_score(parsed_resume, parsed_jd)
    edu_pts = _education_score(parsed_resume, parsed_jd)
    loc_pts = _location_score(parsed_resume, parsed_jd, redacted=bool(bias_flags.get("redact_location")))
    cul_pts, cul_reasoning = _culture_score(parsed_resume, parsed_jd)

    # Weighted composite
    w_skills = float(weights.get("skills", 40)) / 100
    w_exp    = float(weights.get("experience", 25)) / 100
    w_edu    = float(weights.get("education", 15)) / 100
    w_loc    = float(weights.get("location", 10)) / 100
    w_cul    = float(weights.get("culture_fit", 10)) / 100

    final = round(
        skills_pts * w_skills + exp_pts * w_exp + edu_pts * w_edu + loc_pts * w_loc + cul_pts * w_cul,
        2,
    )

    breakdown = {
        "skills":      round(skills_pts, 2),
        "experience":  round(exp_pts, 2),
        "education":   round(edu_pts, 2),
        "location":    round(loc_pts, 2),
        "culture_fit": round(cul_pts, 2),
    }
    bias = predict_bias_panel(parsed_resume, "")
    bias["redacted_attributes"] = [k.replace("redact_", "") for k, v in bias_flags.items() if v]

    return {
        "final_score": final,
        "breakdown": breakdown,
        "ai_insights": build_ai_insights(parsed_resume, parsed_jd, breakdown, matched, missing),
        "skills_matched": matched,
        "skills_missing": missing,
        "bias_panel": bias,
        "culture_reasoning": cul_reasoning,
    }


# ---------------------------------------------------------------
# AI Analysis cards (4 insights surfaced in the UI)
# ---------------------------------------------------------------
def build_ai_insights(parsed_resume: dict, parsed_jd: dict, breakdown: dict,
                      matched: list[str], missing: list[str]) -> list[dict]:
    """Returns 4 insight cards for the UI."""
    insights = []
    must = (parsed_jd.get("required_skills") or {}).get("must_have") or []
    matched_must = [s for s in matched if s in must]

    # 1. Skill match
    if must:
        insights.append({
            "tone": "good" if breakdown["skills"] >= 75 else "warn" if breakdown["skills"] >= 50 else "bad",
            "title": "Strong skill match" if breakdown["skills"] >= 75 else "Partial skill match" if breakdown["skills"] >= 50 else "Skills gap",
            "body": f"{len(matched_must)}/{len(must)} required skills present" + (f"; missing: {', '.join(missing[:3])}" if missing else ""),
        })

    # 2. Experience
    ex_jd = parsed_jd.get("experience") or {}
    yrs = float(parsed_resume.get("total_experience_years") or 0)
    if ex_jd.get("min_years"):
        if yrs < ex_jd["min_years"]:
            insights.append({"tone": "warn",
                             "title": "Experience gap",
                             "body": f"Role asks {ex_jd['min_years']}+ years; candidate has {yrs:g}"})
        elif ex_jd.get("max_years") and yrs > ex_jd["max_years"]:
            insights.append({"tone": "warn",
                             "title": "Possibly over-qualified",
                             "body": f"Role caps at {ex_jd['max_years']} yrs; candidate has {yrs:g}"})
        else:
            insights.append({"tone": "good", "title": "Experience match",
                             "body": f"{yrs:g} yrs within target band {ex_jd['min_years']}–{ex_jd.get('max_years') or '∞'}"})

    # 3. Location
    loc_pts = breakdown.get("location") or 0
    if loc_pts >= 80:
        insights.append({"tone": "good", "title": "Location match", "body": "Candidate is in a preferred city"})
    elif loc_pts >= 50:
        insights.append({"tone": "warn", "title": "Location flexible", "body": "Remote / relocation likely required"})
    else:
        insights.append({"tone": "bad", "title": "Location mismatch", "body": "Outside preferred locations and not remote-friendly"})

    # 4. Bias check (will be enriched downstream by analyzer)
    insights.append({
        "tone": "info",
        "title": "Bias check",
        "body": "Score computed with current redaction config (see audit log)",
    })
    return insights


# ---------------------------------------------------------------
# Skill-profile (radar) — 6 axes derived from breakdown + heuristics
# ---------------------------------------------------------------
def derive_skill_profile(parsed_resume: dict, breakdown: dict) -> dict[str, float]:
    """Map the score breakdown + a couple of heuristics to the 6-axis radar."""
    work = parsed_resume.get("work_experience") or []
    n_jobs = len(work)
    leadership = 0
    comm = 0
    for w in work:
        t = (w.get("title") or "").lower()
        if any(k in t for k in ["lead", "head", "principal", "manager", "director", "chief"]):
            leadership += 30
        if "comm" in t or "marketing" in t or "evangelist" in t:
            comm += 20
        for r in (w.get("responsibilities") or []):
            r = (r or "").lower()
            if any(k in r for k in ["led", "managed", "owned", "mentored", "drove"]):
                leadership += 5
            if any(k in r for k in ["presented", "stakeholder", "communicat"]):
                comm += 5

    # Defaults based on whether work history exists at all
    base_comm = 60 if n_jobs > 0 else 40
    base_lead = 40 if n_jobs > 0 else 25
    return {
        "Technical Skills":  round(breakdown.get("skills", 50), 1),
        "Experience Depth":  round(breakdown.get("experience", 50), 1),
        "Communication":     round(min(100, base_comm + comm), 1),
        "Leadership":        round(min(100, base_lead + leadership), 1),
        "Culture Fit":       round(breakdown.get("culture_fit", 60), 1),
        "Problem Solving":   round((breakdown.get("skills", 50) + breakdown.get("experience", 50)) / 2, 1),
    }
