"""Signed share-link tokens — the security-critical pure surface
(HMAC over a server-secret-derived key; memory flags this pattern)."""
from __future__ import annotations

from app.modules.fake_news import service


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
