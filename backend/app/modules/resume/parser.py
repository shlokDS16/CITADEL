"""
Structured extraction via Groq.

Two public functions:
  - parse_jd_text(text)      → dict matching the parsed_jd schema (title, dept, skills, ...)
  - parse_resume_text(text)  → dict matching the parsed_resume schema

Both use `llama-3.3-70b-versatile`. The prompts are strict — the model is told to
return JSON only, no commentary. We try to recover from sloppy responses by
extracting the first JSON block.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("citadel.resume.parser")


# ---------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------
RESUME_SYSTEM_PROMPT = """You are a precise resume parser. Extract the following fields from the resume text and return ONLY a single valid JSON object — no markdown, no commentary, no code fences. If a field is missing, use null (or empty array). Do not infer values you cannot ground in the text.

Schema:
{
  "name": "",
  "email": "",
  "phone": "",
  "location": {"city": "", "state": "", "country": ""},
  "total_experience_years": 0,
  "highest_education": "",
  "summary": "",
  "education": [
    {"degree": "", "field": "", "institution": "", "year": 0, "gpa": ""}
  ],
  "work_experience": [
    {"title": "", "company": "", "start_year": 0, "end_year": 0, "duration_months": 0, "responsibilities": [], "technologies": []}
  ],
  "skills": {
    "technical": [],
    "soft": [],
    "certifications": [],
    "languages": []
  }
}"""

JD_SYSTEM_PROMPT = """You are a precise job-description parser. Extract these fields and return ONLY one valid JSON object — no markdown, no commentary. If a field is missing, use null or empty arrays. Do not invent.

Schema:
{
  "title": "",
  "department": "",
  "summary": "",
  "required_skills": {
    "must_have": [],
    "nice_to_have": [],
    "minimum_match_percent": 60
  },
  "experience": {
    "min_years": 0,
    "max_years": 0,
    "preferred_titles": [],
    "preferred_industries": []
  },
  "education": {
    "minimum_level": "bachelors",
    "preferred_fields": [],
    "gpa_threshold": null
  },
  "location": {
    "preferred_cities": [],
    "remote_ok": false,
    "relocation_ok": false
  },
  "culture_fit": {
    "keywords": [],
    "values": []
  },
  "urgency": "NORMAL",
  "openings": 1
}

minimum_level must be one of: none, diploma, bachelors, masters, phd
urgency must be one of: LOW, NORMAL, HIGH"""


# ---------------------------------------------------------------
# Core call
# ---------------------------------------------------------------
def _groq_chat(system: str, user: str, *, max_tokens: int = 2000, timeout: int = 30) -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured")
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            settings.GROQ_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_CLASSIFIER_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _coerce_json(raw: str) -> dict[str, Any]:
    """Try to recover JSON from sloppy responses (markdown fences, leading text)."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Find first balanced JSON object
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not coerce JSON from response: {raw[:200]}")


# ---------------------------------------------------------------
# Public
# ---------------------------------------------------------------
def parse_resume_text(text: str) -> dict[str, Any]:
    """Send resume text to Groq, return structured dict."""
    if not text or len(text) < 30:
        return _empty_resume()
    text = text[:18000]      # safety cap (~4500 tokens)
    try:
        raw = _groq_chat(RESUME_SYSTEM_PROMPT, text, max_tokens=2200)
        return _normalize_resume(_coerce_json(raw))
    except Exception as e:
        log.exception("parse_resume_text failed: %s", e)
        return _empty_resume()


def parse_jd_text(text: str) -> dict[str, Any]:
    """Send JD text to Groq, return structured dict."""
    if not text or len(text) < 30:
        return _empty_jd()
    text = text[:12000]
    try:
        raw = _groq_chat(JD_SYSTEM_PROMPT, text, max_tokens=1800)
        return _normalize_jd(_coerce_json(raw))
    except Exception as e:
        log.exception("parse_jd_text failed: %s", e)
        return _empty_jd()


# ---------------------------------------------------------------
# Normalisers — guarantee shape so downstream code never KeyErrors
# ---------------------------------------------------------------
def _empty_resume() -> dict:
    return {
        "name": None, "email": None, "phone": None,
        "location": {"city": None, "state": None, "country": None},
        "total_experience_years": 0,
        "highest_education": None, "summary": None,
        "education": [], "work_experience": [],
        "skills": {"technical": [], "soft": [], "certifications": [], "languages": []},
    }


def _normalize_resume(d: dict) -> dict:
    base = _empty_resume()
    base.update({k: d.get(k) for k in ("name", "email", "phone", "highest_education", "summary")})
    loc = d.get("location") or {}
    base["location"] = {
        "city": loc.get("city"), "state": loc.get("state"), "country": loc.get("country"),
    }
    try:
        base["total_experience_years"] = float(d.get("total_experience_years") or 0)
    except Exception:
        base["total_experience_years"] = 0.0
    base["education"] = d.get("education") or []
    base["work_experience"] = d.get("work_experience") or []
    sk = d.get("skills") or {}
    base["skills"] = {
        "technical": sk.get("technical") or [],
        "soft": sk.get("soft") or [],
        "certifications": sk.get("certifications") or [],
        "languages": sk.get("languages") or [],
    }
    return base


def _empty_jd() -> dict:
    return {
        "title": None, "department": None, "summary": None,
        "required_skills": {"must_have": [], "nice_to_have": [], "minimum_match_percent": 60},
        "experience": {"min_years": 0, "max_years": 0, "preferred_titles": [], "preferred_industries": []},
        "education": {"minimum_level": "bachelors", "preferred_fields": [], "gpa_threshold": None},
        "location": {"preferred_cities": [], "remote_ok": False, "relocation_ok": False},
        "culture_fit": {"keywords": [], "values": []},
        "urgency": "NORMAL", "openings": 1,
    }


def _normalize_jd(d: dict) -> dict:
    base = _empty_jd()
    base["title"] = d.get("title") or base["title"]
    base["department"] = d.get("department") or base["department"]
    base["summary"] = d.get("summary") or base["summary"]
    base["urgency"] = (d.get("urgency") or "NORMAL").upper()
    if base["urgency"] not in {"LOW", "NORMAL", "HIGH"}:
        base["urgency"] = "NORMAL"
    try:
        base["openings"] = int(d.get("openings") or 1)
    except Exception:
        base["openings"] = 1
    rs = d.get("required_skills") or {}
    base["required_skills"] = {
        "must_have": rs.get("must_have") or [],
        "nice_to_have": rs.get("nice_to_have") or [],
        "minimum_match_percent": int(rs.get("minimum_match_percent") or 60),
    }
    ex = d.get("experience") or {}
    base["experience"] = {
        "min_years": int(ex.get("min_years") or 0),
        "max_years": int(ex.get("max_years") or 0),
        "preferred_titles": ex.get("preferred_titles") or [],
        "preferred_industries": ex.get("preferred_industries") or [],
    }
    ed = d.get("education") or {}
    lvl = (ed.get("minimum_level") or "bachelors").lower()
    if lvl not in {"none", "diploma", "bachelors", "masters", "phd"}:
        lvl = "bachelors"
    base["education"] = {
        "minimum_level": lvl,
        "preferred_fields": ed.get("preferred_fields") or [],
        "gpa_threshold": ed.get("gpa_threshold"),
    }
    lo = d.get("location") or {}
    base["location"] = {
        "preferred_cities": lo.get("preferred_cities") or [],
        "remote_ok": bool(lo.get("remote_ok") or False),
        "relocation_ok": bool(lo.get("relocation_ok") or False),
    }
    cf = d.get("culture_fit") or {}
    base["culture_fit"] = {
        "keywords": cf.get("keywords") or [],
        "values": cf.get("values") or [],
    }
    return base
