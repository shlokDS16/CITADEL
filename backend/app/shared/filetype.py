"""
Content-based upload validation (CITADEL shared).

security-baseline.md requires uploads be validated by *content*, not just
a trusted extension ("mime sniff"). python-magic is intentionally NOT used
here: libmagic on Windows / Python 3.14 is fragile (the `python-magic-bin`
wheel is unmaintained and has no 3.14 build). Signature sniffing is
exactly what libmagic does for these formats, is deterministic, and adds
no native dependency — the correct engineering call for this box.

``assert_upload_kind`` is layered *behind* the existing extension
allowlist (defense in depth): the extension gate rejects the obvious, the
content sniff defeats a renamed payload (e.g. a ZIP/PE/script uploaded as
``evidence.jpg`` to attack the deepfake pipeline, or a binary smuggled as
``graph.csv``).
"""
from __future__ import annotations

from fastapi import HTTPException

# startswith signatures → family
_IMG_SIGS: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image"),               # JPEG
    (b"\x89PNG\r\n\x1a\n", "image"),          # PNG
    (b"GIF87a", "image"), (b"GIF89a", "image"),  # GIF
    (b"BM", "image"),                         # BMP
    (b"II*\x00", "image"), (b"MM\x00*", "image"),  # TIFF (LE/BE)
]
_VID_SIGS: list[tuple[bytes, str]] = [
    (b"\x1aE\xdf\xa3", "video"),              # Matroska / WebM (EBML)
    (b"FLV\x01", "video"),                    # FLV
    (b"0&\xb2u", "video"),                    # ASF / WMV
]
# QuickTime / ISO-BMFF top-level box types seen at bytes[4:8]
_MP4_BOXES = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}

_BINARY_SIGS: list[bytes] = [
    b"%PDF-",                                 # PDF
    b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",  # ZIP / OOXML / jar
    b"\x1f\x8b",                              # gzip
    b"Rar!\x1a\x07",                          # RAR
    b"7z\xbc\xaf\x27\x1c",                    # 7z
    b"\xfd7zXZ\x00",                          # xz
    b"\x7fELF",                               # ELF
    b"MZ",                                    # DOS/PE (exe/dll)
    b"\xca\xfe\xba\xbe",                      # Mach-O / Java class
    b"\xd0\xcf\x11\xe0",                      # legacy MS Office (OLE)
]

# A real ISO-BMFF top-level box (ftyp/…) declares a small size; ASCII
# text read as a big-endian uint32 is always huge (≥ ~0x20202020 ≈ 538M
# for 4 printable bytes), so this ceiling cleanly separates a genuine box
# prefix from a text/CSV collision without needing the whole file.
_MAX_BOX = 1 << 20


def detect_kind(content: bytes) -> str:
    """Best-effort content family from magic bytes:
    ``image`` | ``video`` | ``binary`` | ``text``."""
    head = content[:64]

    # ISO-BMFF (mp4/mov/m4v): a known box type at [4:8] AND a *valid*
    # 32-bit big-endian box-size prefix at [0:4]. Without the size check,
    # any text whose 5th-8th bytes spell e.g. "ftyp"/"free" (a CSV column
    # header, a JSON key at that offset) false-classifies as video and
    # gets a spurious 415. Real box sizes: 1 = 64-bit size follows,
    # 0 = box runs to EOF, else the box length in bytes.
    if len(content) >= 8 and content[4:8] in _MP4_BOXES:
        box_size = int.from_bytes(content[:4], "big")
        if box_size in (0, 1) or 8 <= box_size <= _MAX_BOX:
            return "video"
    # RIFF container — disambiguate WEBP (image) vs AVI (video) by FourCC
    if head[:4] == b"RIFF" and len(content) >= 12:
        fourcc = content[8:12]
        if fourcc == b"WEBP":
            return "image"
        if fourcc == b"AVI ":
            return "video"
    for sig, kind in _IMG_SIGS:
        if head.startswith(sig):
            return kind
    for sig, kind in _VID_SIGS:
        if head.startswith(sig):
            return kind
    for sig in _BINARY_SIGS:
        if head.startswith(sig):
            return "binary"

    # Text heuristic: NUL is a near-certain binary marker; otherwise the
    # sample must be overwhelmingly printable (tolerates latin-1 CSVs).
    sample = content[:65536]
    if not sample:
        return "text"
    # UTF-16/UTF-32 text is NUL-dense; a BOM makes it unambiguous. Excel
    # "Unicode Text (.txt)" and Notepad "Unicode" export UTF-16LE — a real
    # citizen upload that must not 415 as "binary".
    if (sample[:2] in (b"\xff\xfe", b"\xfe\xff")
            or sample[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "text"
    if b"\x00" in sample:
        return "binary"
    try:
        sample.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        printable = sum(1 for b in sample
                        if b in (9, 10, 13) or 32 <= b <= 126 or b >= 0xA0)
        return "text" if printable / len(sample) > 0.85 else "binary"


def assert_upload_kind(filename: str | None, content: bytes,
                       allowed: set[str]) -> str:
    """Sniff ``content`` and raise ``415`` if its real family is not in
    ``allowed`` — defeats extension-spoofed uploads. Returns the kind."""
    kind = detect_kind(content)
    if kind not in allowed:
        raise HTTPException(
            status_code=415,
            detail=(f"file content does not match an accepted type for "
                    f"this endpoint (detected: {kind}; "
                    f"expected: {', '.join(sorted(allowed))})"),
        )
    return kind
