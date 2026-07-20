"""Citizen Module 4 — Expense Categorizer.

Layered by design (see categorize.py for the rationale): a curated Indian
merchant lexicon does the heavy lifting, a TF-IDF/LinearSVC model covers
the gaps, and the LLM is consulted only for genuinely unseen merchants —
cached by merchant key so a new merchant costs one call ever, not one per
transaction.
"""

def __getattr__(name: str):
    """Lazy re-export so importing a pure helper (merchants/categorize) does
    not drag in FastAPI, the DB client, or any ML weights."""
    if name == "router":
        from app.modules.expenses.router import router
        return router
    raise AttributeError(name)


__all__ = ["router"]
