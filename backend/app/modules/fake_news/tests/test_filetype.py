"""Content-based upload validation (app/shared/filetype.py)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.shared.filetype import assert_upload_kind, detect_kind

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x01" * 12
GIF = b"GIF89a" + b"\x01" * 16
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 8
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 12
AVI = b"RIFF\x24\x00\x00\x00AVI LIST" + b"\x00" * 8
PDF = b"%PDF-1.7\n%\xe2\xe3\n"
ZIP = b"PK\x03\x04\x14\x00" + b"\x00" * 12
ELF = b"\x7fELF\x02\x01" + b"\x00" * 12
PEX = b"MZ\x90\x00" + b"\x00" * 12
TXT = b"url\nhttps://example.com/a\nhttps://example.com/b\n"
JSONB = b'{"nodes":[{"id":"u1"}],"edges":[]}'
NUL = b"a,b\n1,2\n" + b"\x00" * 64


@pytest.mark.parametrize("blob,want", [
    (PNG, "image"), (JPEG, "image"), (GIF, "image"), (WEBP, "image"),
    (MP4, "video"), (WEBM, "video"), (AVI, "video"),
    (PDF, "binary"), (ZIP, "binary"), (ELF, "binary"), (PEX, "binary"),
    (NUL, "binary"), (TXT, "text"), (JSONB, "text"),
])
def test_detect_kind(blob: bytes, want: str):
    assert detect_kind(blob) == want


def test_assert_upload_kind_match_returns_kind():
    assert assert_upload_kind("a.png", PNG, {"image", "video"}) == "image"


def test_assert_upload_kind_image_as_csv__415():
    with pytest.raises(HTTPException) as e:
        assert_upload_kind("a.csv", PNG, {"text"})
    assert e.value.status_code == 415


def test_assert_upload_kind_zip_as_json__415():
    with pytest.raises(HTTPException) as e:
        assert_upload_kind("g.json", ZIP, {"text"})
    assert e.value.status_code == 415


def test_assert_upload_kind_elf_as_jpg__415():
    with pytest.raises(HTTPException) as e:
        assert_upload_kind("evidence.jpg", ELF, {"image", "video"})
    assert e.value.status_code == 415
