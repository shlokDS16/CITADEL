"""Pydantic contract: roundtrip + validation-failure per schema
(testing.md mandatory)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.modules.fake_news import schemas


def test_analyzein_text_roundtrip__strips_control_and_trims():
    a = schemas.AnalyzeIn(text="  Hello\x00 world  ")
    assert a.mode == "TEXT"
    assert a.text == "Hello world"
    again = schemas.AnalyzeIn(**a.model_dump())
    assert again.text == a.text


def test_analyzein_blank_text__rejected():
    with pytest.raises(ValidationError):
        schemas.AnalyzeIn(mode="TEXT", text="   ")


def test_analyzein_url_mode_without_url__rejected():
    with pytest.raises(ValidationError):
        schemas.AnalyzeIn(mode="URL")


def test_analyzein_url_gets_https_prefix():
    a = schemas.AnalyzeIn(mode="URL", url="example.com/story")
    assert a.url.startswith("https://")


def test_bulkin_over_50_urls__rejected():
    with pytest.raises(ValidationError):
        schemas.BulkIn(urls=[f"https://x/{i}" for i in range(51)])


def test_analysisout_minimal_roundtrip():
    o = schemas.AnalysisOut(
        id="a1", submitted_at=datetime.now(timezone.utc),
        mode="TEXT", verdict="UNCERTAIN", confidence=0.5)
    again = schemas.AnalysisOut(**o.model_dump())
    assert again.verdict == "UNCERTAIN"
    assert again.confidence == 0.5


def test_analysisout_confidence_out_of_range__rejected():
    with pytest.raises(ValidationError):
        schemas.AnalysisOut(
            id="a", submitted_at=datetime.now(timezone.utc),
            mode="TEXT", verdict="FAKE", confidence=1.5)
