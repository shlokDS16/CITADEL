"""
Spend-anomaly detection for a citizen's expenses.

Two layers, honestly labelled:

  1. Statistical rule (always available) — flags a transaction when it is
     both > 2x the category's 90-day average AND > a robust-z outlier
     against the category history (median + MAD). Matches spec-08's
     "amount > 2x category 30d avg" intent but uses median/MAD because a
     personal-finance category with one prior ₹45k TV purchase would drag
     a plain mean far enough to hide the next outlier.

  2. IsolationForest (spec-08) — only consulted once the category has
     >= MIN_SAMPLES_FOR_FOREST transactions. Below that the forest is
     numerology: contamination=0.05 over eight points flags nothing
     meaningful. When it runs, BOTH layers must agree to flag — the
     forest tempers the rule, it does not add flags of its own, so a
     citizen never sees "the model said so" without a plain-language
     magnitude reason attached.

The anomaly_reason string is written for the citizen, not the log:
"₹45,000 Shopping vs ₹6,800 90-day average" — spec-08's exact shape.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any, Optional

log = logging.getLogger("citadel.expenses.anomaly")

MIN_SAMPLES_STAT = 3          # below this there is no baseline to compare
MIN_SAMPLES_FOR_FOREST = 20
MULTIPLE_OF_AVG = 2.0
ROBUST_Z_CUTOFF = 3.5


def _rupees(paise: int | float) -> str:
    return f"₹{round(paise / 100):,}"


def score(
    amount_paise: int,
    category: str,
    history_paise: list[int],
    overall_history_paise: Optional[list[int]] = None,
) -> tuple[bool, Optional[str]]:
    """Decide whether this amount is anomalous.

    Baseline preference: the citizen's history in the SAME category. When
    that is too thin (< MIN_SAMPLES_STAT), fall back to their all-category
    transaction distribution — otherwise the first big purchase in any
    category could never flag, and that first-ever ₹45k spend against a
    ₹500-typical account is precisely the anomaly worth surfacing.
    Returns (is_anomaly, reason). Never raises.
    """
    scope = "90-day average"
    if len(history_paise) < MIN_SAMPLES_STAT and overall_history_paise:
        history_paise = overall_history_paise
        scope = "typical transaction (all categories)"

    n = len(history_paise)
    if n < MIN_SAMPLES_STAT:
        return False, None

    avg = sum(history_paise) / n
    if avg <= 0:
        return False, None

    # Layer 1a: magnitude vs average
    if amount_paise <= MULTIPLE_OF_AVG * avg:
        return False, None

    # Layer 1b: robust z against median/MAD — guards against a history
    # whose average is already inflated by one prior outlier
    med = statistics.median(history_paise)
    mad = statistics.median(abs(x - med) for x in history_paise)
    if mad > 0:
        robust_z = 0.6745 * (amount_paise - med) / mad
        if robust_z < ROBUST_Z_CUTOFF:
            return False, None
    # mad == 0 (identical history values) → any 2x+ amount is an outlier

    reason = f"{_rupees(amount_paise)} {category} vs {_rupees(avg)} {scope}"

    # Layer 2: IsolationForest, only with enough data, and only as a veto
    if n >= MIN_SAMPLES_FOR_FOREST:
        verdict = _forest_agrees(amount_paise, history_paise)
        if verdict is False:
            log.debug("forest vetoed stat flag for %s %s", category, amount_paise)
            return False, None
        if verdict is True:
            reason += " (model-confirmed)"

    return True, reason


def _forest_agrees(amount_paise: int, history_paise: list[int]) -> Optional[bool]:
    """True/False = forest verdict; None = unavailable (missing sklearn)."""
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return None
    try:
        x = np.array(history_paise, dtype=float).reshape(-1, 1)
        forest = IsolationForest(contamination=0.05, random_state=42)
        forest.fit(x)
        return bool(forest.predict([[float(amount_paise)]])[0] == -1)
    except Exception as e:  # noqa: BLE001
        log.debug("forest failed: %s", e)
        return None
