"""
Adversarial-evasion defense (Layer 1 pre-pass).

Misinformation authors mangle text to slip past keyword/hash filters:
homoglyphs (Cyrillic 'a' for Latin 'a'), leetspeak ('v@ccine'), zero-width
characters, letter-spacing ('f r e e  m o n e y'), full-width unicode.

This module produces a *deobfuscated* variant of the text used for L1
keyword/hash matching (NOT for the transformer classifiers — those see the
original, they handle natural text better), plus the evasion signals
themselves (heavy obfuscation is itself a fake-news red flag).

Pure stdlib, deterministic, never raises.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Common confusable codepoints -> ASCII. Curated for the scripts actually
# seen in Indian misinformation (Latin/Cyrillic/Greek). Full-width and
# styled-math letters are handled by NFKC before this map is applied.
_CONFUSABLES: dict[str, str] = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
    "ԁ": "d", "н": "n", "г": "r", "т": "t",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "Ѕ": "S",
    "ο": "o", "ρ": "p", "α": "a", "ε": "e", "ι": "i",
    "ν": "v", "υ": "u",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Χ": "X",
}

# Leetspeak — applied ONLY to the match-variant, inside word-ish runs so we
# don't destroy real numbers / prices.
_LEET: dict[str, str] = {
    "@": "a", "4": "a", "8": "b", "(": "c", "3": "e", "6": "g", "1": "i",
    "!": "i", "0": "o", "5": "s", "$": "s", "7": "t", "+": "t", "|": "l",
    "9": "g", "2": "z",
}

# Zero-width spaces/joiners, bidi controls, BOM, soft hyphen, word joiner,
# invisible math operators. Built from explicit codepoints so there are no
# invisible characters in this source file.
_ZW_CODEPOINTS: tuple[int, ...] = (
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,
    0xFEFF, 0x00AD,
)
_ZERO_WIDTH = re.compile("[" + "".join(chr(c) for c in _ZW_CODEPOINTS) + "]")
_SPACED_LETTERS = re.compile(r"(?:\b\w\b[ .\-]){3,}\w\b")
_MULTI_SPACE = re.compile(r"\s{2,}")
_LEET_WORD = re.compile(r"[A-Za-z@$0-9!|+()]{3,}")


@dataclass
class NormalizationResult:
    original: str
    normalized: str            # cleaned, human-readable (NFKC + confusables + zw strip)
    match_variant: str         # aggressive deobfuscation for keyword/hash matching
    signals: list[str] = field(default_factory=list)
    obfuscation_score: float = 0.0   # 0..1 — how mangled the input is


def _fold_confusables(text: str) -> tuple[str, int]:
    out: list[str] = []
    hits = 0
    for ch in text:
        rep = _CONFUSABLES.get(ch)
        if rep is not None:
            out.append(rep)
            hits += 1
        else:
            out.append(ch)
    return "".join(out), hits


def _is_ascii_alpha(c: str) -> bool:
    return c.isascii() and c.isalpha()


def _deleet_word(m: re.Match[str]) -> str:
    """De-leet only *interior* symbols flanked by ASCII letters.

    This deliberately ignores leading/trailing punctuation so ordinary text
    like "citizens!!!" is NOT mangled to "citizensiii" — a leet char only
    counts when it sits between two letters ("v@ccine" -> "vaccine").
    """
    w = m.group(0)
    if not any(_is_ascii_alpha(c) for c in w):
        return w
    chars = list(w)
    changed = False
    for i in range(1, len(chars) - 1):
        c = chars[i]
        if c in _LEET and _is_ascii_alpha(chars[i - 1]) and _is_ascii_alpha(chars[i + 1]):
            chars[i] = _LEET[c]
            changed = True
    return "".join(chars) if changed else w


def normalize(text: str) -> NormalizationResult:
    """Deobfuscate `text`; report the evasion signals found.

    Returns the original untouched plus two derived forms:
      - ``normalized``: safe human-readable cleanup (used for display/excerpt)
      - ``match_variant``: aggressive lowercase deobfuscation (L1 matching only)
    """
    if not text:
        return NormalizationResult(original=text, normalized=text, match_variant="")

    signals: list[str] = []
    score = 0.0

    zw_count = len(_ZERO_WIDTH.findall(text))
    cleaned = _ZERO_WIDTH.sub("", text)
    if zw_count:
        signals.append(f"zero_width_chars:{zw_count}")
        score += min(0.3, 0.05 * zw_count)

    nfkc = unicodedata.normalize("NFKC", cleaned)
    if nfkc != cleaned:
        signals.append("unicode_normalized")
        score += 0.1

    folded, conf_hits = _fold_confusables(nfkc)
    if conf_hits:
        signals.append(f"homoglyph_substitution:{conf_hits}")
        score += min(0.4, 0.03 * conf_hits)

    normalized = _MULTI_SPACE.sub(" ", folded).strip()

    mv = folded.lower()
    if _SPACED_LETTERS.search(mv):
        signals.append("letter_spacing_evasion")
        score += 0.25
        mv = re.sub(
            r"\b\w(?:[ .\-]\w){2,}\b",
            lambda m: re.sub(r"[ .\-]", "", m.group(0)),
            mv,
        )
    pre_leet = mv
    mv = _LEET_WORD.sub(_deleet_word, mv)
    if mv != pre_leet:
        signals.append("leetspeak")
        score += 0.2
    match_variant = _MULTI_SPACE.sub(" ", mv).strip()

    return NormalizationResult(
        original=text,
        normalized=normalized,
        match_variant=match_variant,
        signals=signals,
        obfuscation_score=round(min(1.0, score), 4),
    )
