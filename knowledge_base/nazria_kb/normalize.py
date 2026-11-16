"""Urdu text normalisation helpers.

Two levels:
* ``normalize_urdu`` – canonical display text (keeps diacritics/ZWNJ).
* ``search_key``     – aggressive key for matching/dedup (no diacritics,
                       no punctuation, single spaces).
"""
from __future__ import annotations

import re
import unicodedata

# Arabic-script code points that OCR emits but Urdu orthography writes differently
_CHAR_MAP = {
    "ي": "ی",  # ي Arabic yeh        -> ی Farsi/Urdu yeh
    "ى": "ی",  # ى alef maksura      -> ی
    "ك": "ک",  # ك Arabic kaf        -> ک keheh
    "ه": "ہ",  # ه Arabic heh        -> ہ heh goal
    "ھھ": "ھ",
    " ": " ",       # NBSP
    " ": " ", " ": " ", " ": " ", " ": " ",
    "ـ": "",        # tatweel
    "​": "",        # zero width space
    "﻿": "",        # BOM
    "‎": "", "‏": "", "‪": "", "‫": "", "‬": "",
    "٫": ".",       # Arabic decimal separator
}
# Arabic-Indic digits (U+0660..9) -> Extended Arabic-Indic (Urdu) digits (U+06F0..9)
_CHAR_MAP.update({chr(0x0660 + i): chr(0x06F0 + i) for i in range(10)})

_MAP_RE = re.compile("|".join(sorted(map(re.escape, _CHAR_MAP), key=len, reverse=True)))
_DIACRITICS_RE = re.compile("[ً-ٰٟۖ-ۭؔ-ؚ]")
_PUNCT_RE = re.compile(r"[،؛؟۔٪-٭!-/:-@\[-`{-~«»“”‘’…–—•·*#]")
_WS_RE = re.compile(r"[ \t]+")
_DIGITS = str.maketrans({**{chr(0x06F0 + i): str(i) for i in range(10)}, **{chr(0x0660 + i): str(i) for i in range(10)}})

URDU_DIGIT_RE = r"[0-9٠-٩۰-۹]"


def normalize_urdu(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _MAP_RE.sub(lambda m: _CHAR_MAP[m.group(0)], text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    return text


def search_key(text: str) -> str:
    text = normalize_urdu(text)
    text = _DIACRITICS_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def to_int(text: str) -> int | None:
    digits = re.sub(r"\D", "", (text or "").translate(_DIGITS))
    return int(digits) if digits else None


def to_latin_digits(text: str) -> str:
    return (text or "").translate(_DIGITS)


def latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isascii()) / len(letters)
