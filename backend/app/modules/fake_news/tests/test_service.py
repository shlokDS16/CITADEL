"""Pure service surfaces: signed share-link tokens (HMAC over a
server-secret-derived key) + the Layer-3 verdict fusion (honesty rules)."""
from __future__ import annotations

from app.modules.fake_news import service


def _fv(combined_risk, l2_verdict, claims, l2_conf=0.6, debunked=None):
    return service._final_verdict(
        combined_risk, l2_verdict, l2_conf, claims, debunked)


def test_l3_contradiction_not_buried_as_uncertain():
    # Regression: a fact-checked-false claim (FALSE @ 0.78) with clean
    # prose (low L2 style risk, l2_verdict LIKELY_REAL) was wrongly
    # emerging as UNCERTAIN. L3 is authoritative → must be FAKE-family.
    risk, verdict, conf, _nr, _note = _fv(
        0.32, "LIKELY_REAL", [{"verdict": "FALSE", "confidence": 0.78}])
    assert verdict == "LIKELY_FAKE"
    assert risk >= 0.80


def test_strong_factcheck_false_is_fake():
    _r, verdict, _c, _nr, _n = _fv(
        0.5, "UNCERTAIN", [{"verdict": "FALSE", "confidence": 0.90}])
    assert verdict == "FAKE"


def test_weak_false_not_gated_behind_style_risk():
    # SUSPICIOUS with near-zero style risk must still warn (was suppressed
    # by the old `combined_risk >= 0.4` gate).
    _r, verdict, _c, nr, _n = _fv(
        0.05, "LIKELY_REAL", [{"verdict": "SUSPICIOUS", "confidence": 0.6}])
    assert verdict == "LIKELY_FAKE"
    assert nr is True


def test_honesty_unverified_still_uncertain():
    # No verifiable claims + clean style must NOT assert REAL — the
    # honesty downgrade to UNCERTAIN is intentional and preserved.
    _r, verdict, _c, nr, _n = _fv(0.2, "LIKELY_REAL", [])
    assert verdict == "UNCERTAIN"
    assert nr is True


def test_honesty_corroborated_true_still_real():
    _r, verdict, _c, _nr, _n = _fv(
        0.1, "LIKELY_REAL", [{"verdict": "TRUE", "confidence": 0.9}])
    assert verdict == "REAL"


def test_share_token_roundtrip():
    tok = service.make_share_token("analysis-123")
    assert service.verify_share_token(tok) == "analysis-123"


def test_share_token_tamper__rejected():
    tok = service.make_share_token("analysis-123")
    flipped = ("A" if tok[0] != "A" else "B") + tok[1:]
    assert service.verify_share_token(flipped) is None


def test_share_token_expired__rejected():
    tok = service.make_share_token("analysis-123", ttl_days=-1)
    assert service.verify_share_token(tok) is None


def test_share_token_garbage__rejected():
    assert service.verify_share_token("not-a-real-token") is None
    assert service.verify_share_token("") is None
