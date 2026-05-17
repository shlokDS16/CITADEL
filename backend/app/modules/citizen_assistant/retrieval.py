"""
Reasoning-based retrieval (PageIndex method) + citizen access guard.

Two-step, vectorless, no chunking — exactly the PageIndex approach:

  STEP 1  TREE SEARCH  — give the LLM the table-of-contents of every
          knowledge tree (titles + summaries + node ids) plus the
          citizen access policy. It reasons which node(s) are relevant
          AND whether the request is citizen-allowed or restricted.

  STEP 2  READ + ANSWER — fetch the full text of the selected nodes,
          add live facts + any uploaded-document tree + (optional) web
          results, and compose a grounded, language-matched answer with
          traceable citations and a short reasoning trace.

Everything runs on Groq via PageIndex's LiteLLM helper.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from app.modules.citizen_assistant import live_facts, web_search
from app.modules.citizen_assistant.pageindex_engine import PI_MODEL, get_trees

log = logging.getLogger("citadel.citizen_assistant.retrieval")


class _QuotaExhausted(Exception):
    """All configured LLM providers are rate/quota limited."""
    def __init__(self, retry_hint: str = ""):
        super().__init__("LLM quota exhausted")
        self.retry_hint = retry_hint


def _provider_chain() -> list[str]:
    """
    Project LLM priority: Groq primary → Gemini fallback (when Groq drained)
    → local Ollama last resort. Only providers with credentials/reachable
    are included; LiteLLM routes each model string to its provider.
    """
    chain = [PI_MODEL.removeprefix("litellm/")]            # groq/...
    gkey = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gkey:
        os.environ.setdefault("GEMINI_API_KEY", gkey)
        chain.append(os.getenv("CITIZEN_GEMINI_MODEL", "gemini/gemini-1.5-flash"))
    try:
        import httpx as _hx
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        _hx.get(base + "/api/tags", timeout=0.6)
        chain.append(f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3.2')}")
    except Exception:
        pass
    return chain


def _is_rate_limit(exc: Exception) -> bool:
    s = (str(exc) or "").lower()
    return ("ratelimit" in s or "rate_limit" in s or "rate limit" in s
            or "quota" in s or "tokens per day" in s or "tpd" in s
            or "429" in s)


def _retry_hint(exc: Exception) -> str:
    import re as _re
    m = _re.search(r"try again in ([0-9]+m[0-9.]+s|[0-9.]+s)", str(exc) or "")
    return m.group(1) if m else ""


def _llm(prompt: str, history: Optional[list] = None, max_tokens: int = 900,
         temperature: float = 0.2) -> str:
    """
    Multi-provider LLM call via LiteLLM. Tries Groq → Gemini → Ollama in
    order, with a small retry per provider for transient empties. Raises
    _QuotaExhausted only when EVERY provider is rate/quota limited (so the
    caller can show an honest "quota reached" message instead of a vague
    failure). Output is capped (PageIndex's own helper sets no max_tokens
    → runaway on sparse prompts).
    """
    import time as _t
    import litellm
    litellm.drop_params = True
    msgs = (list(history) if history else []) + [{"role": "user", "content": prompt}]
    chain = _provider_chain()
    all_rate_limited = True
    quota_hint = ""
    last_err = None

    for model in chain:
        for attempt in range(3):
            try:
                r = litellm.completion(
                    model=model, messages=msgs,
                    temperature=temperature if attempt == 0 else 0.3,
                    max_tokens=max_tokens,
                )
                txt = (r.choices[0].message.content or "").strip()
                if txt:
                    return txt
                all_rate_limited = False  # empty but not rate-limited
            except Exception as e:
                last_err = e
                if _is_rate_limit(e):
                    quota_hint = quota_hint or _retry_hint(e)
                else:
                    all_rate_limited = False
                if not _is_rate_limit(e):
                    _t.sleep(0.5 * (attempt + 1))
                else:
                    break  # next provider — retrying same won't help
    if last_err:
        log.warning("All LLM providers failed (%d in chain): %s",
                    len(chain), last_err)
    if all_rate_limited and last_err is not None:
        raise _QuotaExhausted(quota_hint)
    return ""


def _walk(node: dict, corpus: str, path: list[str], flat: list[dict], by_id: dict):
    if not isinstance(node, dict):
        return
    title = node.get("title") or "(section)"
    nid = str(node.get("node_id") or f"{corpus}:{len(flat)}")
    key = f"{corpus}::{nid}"
    cur_path = path + [title]
    rec = {
        "key": key,
        "corpus": corpus,
        "node_id": nid,
        "title": title,
        "path": " › ".join(cur_path),
        "summary": (node.get("summary") or "").strip(),
        "text": (node.get("text") or node.get("node_text") or "").strip(),
    }
    flat.append(rec)
    by_id[key] = rec
    for child in (node.get("nodes") or []):
        _walk(child, corpus, cur_path, flat, by_id)


def _flatten(trees: dict[str, Any], extra: Optional[dict] = None):
    flat: list[dict] = []
    by_id: dict[str, dict] = {}
    src = dict(trees)
    if extra:
        src["__uploaded__"] = extra
    for corpus, payload in src.items():
        struct = payload.get("structure") if isinstance(payload, dict) else payload
        if isinstance(struct, dict):
            struct = struct.get("nodes") or [struct]
        for top in (struct or []):
            _walk(top, corpus, [], flat, by_id)
    return flat, by_id


# Token-frugal TOC: Groq free tier is 100K tokens/day, and _select runs
# on EVERY query. Tight caps here ~4x the daily query budget.
def _toc_text(flat: list[dict], limit: int = 90) -> str:
    out = []
    for r in flat[:limit]:
        s = (r["summary"] or "")[:90]
        out.append(f'[{r["key"]}] {r["path"]}' + (f" — {s}" if s else ""))
    return "\n".join(out)


_SELECT_SYS = """You are the retrieval reasoner for CITADEL's citizen assistant.
You are given a citizen's question and a TABLE OF CONTENTS of an official
knowledge base (one line per section: [key] path — summary).

Decide:
1. access: "allowed" or "restricted". Restricted = the question asks for
   another person's private data; government-official-only operations
   (internal enforcement workflow, camera/sensor IDs, officer
   assignments, approval queues, raw evidence, audit logs, model
   internals/thresholds); credentials/OTP/passwords; or help to commit
   fraud / unlawfully evade a fine. Otherwise "allowed".
2. node_keys: up to 6 [key] values most relevant to answer the question
   (most relevant first). [] if none are relevant.
3. need_web: true if the knowledge base likely does not fully cover this
   and a public web lookup would help; else false.

Reply ONLY as compact JSON:
{"access":"allowed|restricted","reason":"<short>","node_keys":["..."],"need_web":true|false}"""


def _select(query: str, flat: list[dict]) -> dict[str, Any]:
    prompt = (
        _SELECT_SYS
        + "\n\nTABLE OF CONTENTS:\n" + _toc_text(flat)
        + f"\n\nCITIZEN QUESTION: {query}\n\nJSON:"
    )
    raw = _llm(prompt, max_tokens=300, temperature=0)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {"access": "allowed", "reason": "", "node_keys": [], "need_web": True}
    try:
        d = json.loads(m.group(0))
        d.setdefault("access", "allowed")
        d.setdefault("node_keys", [])
        d.setdefault("need_web", True)
        return d
    except Exception:
        return {"access": "allowed", "reason": "", "node_keys": [], "need_web": True}


_REFUSAL = (
    "I'm sorry, but I can't share that — it's restricted to authorised "
    "officials and isn't available through the citizen assistant. "
    "I can still help with your own services, applications, or general "
    "guidance. For anything tied to your personal records, please use the "
    "official authenticated portal or raise a support ticket."
)


def _answer_prompt(query, lang, ctx_blocks, history_note, uploaded):
    parts = [
        "You are CITADEL's citizen assistant — accurate, concise, polite, "
        "and non-judgemental.",
        f"Answer ENTIRELY in {lang}. Use {lang}'s native script if you can "
        f"render it accurately; if not, use clear romanised {lang} instead. "
        f"NEVER output '?' or placeholder/garbled characters, and never "
        f"repeat words. Keep it focused: at most ~180 words.",
        "Ground every factual claim in the CONTEXT below. Do not invent "
        "portal names, fees, deadlines or section numbers. If the context "
        "is insufficient, say what you do know and direct the citizen to "
        "the official source.",
        "When CURRENT/live values are present, use them and ignore any "
        "example figure that conflicts.",
    ]
    if uploaded:
        parts.append("The user uploaded a document — base the answer on "
                      "its content FIRST, then add helpful public context.")
    parts.append("End with a one-line 'Sources:' list referencing the "
                 "section paths (and web links if used). Keep it brief.")
    parts.append("\n=== CONTEXT ===\n" + "\n\n".join(b for b in ctx_blocks if b))
    if history_note:
        parts.append("\n=== RECENT CONVERSATION ===\n" + history_note)
    parts.append(f"\n=== CITIZEN QUESTION ===\n{query}\n\nAnswer:")
    return "\n".join(parts)


def answer(
    query: str,
    language: str = "English",
    history: Optional[list[dict]] = None,
    uploaded_tree: Optional[dict] = None,
    allow_web: bool = True,
) -> dict[str, Any]:
    """Full PageIndex pipeline. Returns a structured answer payload."""
    trees = get_trees()
    if not trees and not uploaded_tree:
        return {
            "answer": "The assistant is still loading its knowledge base. "
                      "Please try again in a few seconds.",
            "restricted": False, "reasoning": [], "sources": [],
            "used_web": False, "confidence": 30,
        }

    flat, by_id = _flatten(trees, uploaded_tree)
    reasoning: list[str] = []

    def _quota(hint: str) -> dict[str, Any]:
        msg = ("⚠ The assistant's AI quota is temporarily exhausted"
               + (f" — please try again in about {hint}" if hint else
                  " — please try again shortly") + ". "
               "Your question was received and understood; this is a "
               "provider usage limit, not an error in your request. "
               "(Tip: an administrator can configure a Gemini or local "
               "Ollama fallback so this never blocks answers.)")
        return {
            "answer": msg, "restricted": False,
            "reasoning": reasoning + ["All LLM providers rate/quota limited."],
            "sources": [], "used_web": False, "confidence": 0,
            "quota_exhausted": True,
        }

    # ---- STEP 1: reasoning tree-search + access decision ----
    try:
        sel = _select(query, flat)
    except _QuotaExhausted as q:
        return _quota(q.retry_hint)
    if (sel.get("access") or "allowed").lower() == "restricted":
        reasoning.append(f"Access check → restricted ({sel.get('reason','policy')}).")
        return {
            "answer": _REFUSAL, "restricted": True, "reasoning": reasoning,
            "sources": [], "used_web": False, "confidence": 95,
        }

    chosen = [by_id[k] for k in (sel.get("node_keys") or []) if k in by_id]
    if uploaded_tree:
        # Always include the uploaded doc's sections up front.
        up = [r for r in flat if r["corpus"] == "__uploaded__"]
        chosen = up[:6] + [c for c in chosen if c["corpus"] != "__uploaded__"]
    if not chosen:
        # Never answer from an empty context (that caused degenerate
        # runaway output on sparse/non-Latin queries). Seed with the
        # most informative section per corpus as a safety net.
        seed: list[dict] = []
        seen_c: set[str] = set()
        for r in sorted(flat, key=lambda x: -len(x.get("text") or "")):
            if r["corpus"] in seen_c:
                continue
            seen_c.add(r["corpus"])
            seed.append(r)
            if len(seed) >= 4:
                break
        chosen = seed
        reasoning.append("No exact section matched — seeded broad context.")
    reasoning.append(
        f"Tree-search selected {len(chosen)} section(s): "
        + (", ".join(c["path"] for c in chosen[:6]) or "none")
    )

    # ---- STEP 2a: live facts (rule changes reflect instantly) ----
    lf = live_facts.get_live_facts()
    ctx_blocks: list[str] = []
    node_text = "\n\n".join(
        f"### {c['path']} [{c['corpus']}:{c['node_id']}]\n{(c['text'] or c['summary'])[:1200]}"
        for c in chosen[:4]
    )
    if node_text:
        ctx_blocks.append("KNOWLEDGE BASE SECTIONS:\n" + node_text)
    if lf["text"]:
        ctx_blocks.append(lf["text"])
        reasoning.append("Injected live fines/rules from the CITADEL system.")

    # ---- STEP 2b: web improvisation ----
    used_web = False
    web_results: list[dict] = []
    if allow_web and (sel.get("need_web") or not chosen):
        web_results = web_search.search(query, max_results=5)
        if web_results:
            ctx_blocks.append(web_search.as_context_block(web_results))
            used_web = True
            reasoning.append(f"Improvised with {len(web_results)} public web result(s).")

    # ---- STEP 3: grounded, language-matched synthesis ----
    history_note = ""
    if history:
        last = history[-4:]
        history_note = "\n".join(
            f"{(h.get('role') or 'user').upper()}: {(h.get('text') or '')[:300]}"
            for h in last
        )
    try:
        final = _llm(_answer_prompt(query, language, ctx_blocks, history_note,
                                    bool(uploaded_tree)), max_tokens=650)
        # Safety net: if the model still degenerated into placeholder spam,
        # retry once forcing plain romanised output.
        if final.count("?") > 25 or (len(final) > 400 and len(set(final.split())) < 12):
            reasoning.append("Detected degraded output — retried in romanised form.")
            retry = _answer_prompt(
                query, f"romanised {language} (Latin letters only, no '?')",
                ctx_blocks, history_note, bool(uploaded_tree))
            final = _llm(retry, max_tokens=600)
    except _QuotaExhausted as q:
        return _quota(q.retry_hint)
    if not final.strip():
        final = ("I couldn't compose a confident answer. Please rephrase, "
                 "or check the official government portal for this service.")

    sources = [
        {"corpus": c["corpus"], "section": c["path"], "node_id": c["node_id"]}
        for c in chosen[:6]
    ]
    for w in web_results:
        sources.append({"corpus": "web", "section": w["title"], "url": w["url"]})

    confidence = 90 if chosen else (70 if used_web else 45)
    return {
        "answer": final.strip(),
        "restricted": False,
        "reasoning": reasoning,
        "sources": sources,
        "used_web": used_web,
        "confidence": confidence,
    }
