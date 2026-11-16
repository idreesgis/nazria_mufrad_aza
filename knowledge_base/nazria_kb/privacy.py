"""Removes identifying details from patient text before it is sent to an external AI provider.

Removed: e-mail addresses; CNIC (12345-1234567-1) and other ID numbers; phone numbers (any run of >= 7 digits,
Latin or Urdu digits, with spaces/dashes/brackets); names the patient introduces ("میرا نام … ہے",
"نام: …", "my name is …") and every later occurrence of those names in the session.

This is a best-effort filter for free text, not a guarantee: the patient is also told, once per session,
that an external service is used and asked not to type personal details. Short numbers (age, days,
doses, page numbers) are kept because they matter clinically and do not identify anyone.
"""
from __future__ import annotations

import re

from .normalize import normalize_urdu

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CNIC_RE = re.compile(r"(?<!\d)\d{5}[-\s]?\d{7}[-\s]?\d(?!\d)")
# a digit group with optional +/00 prefix and separators that contains at least 7 digits
LONG_NUMBER_RE = re.compile(r"(?<![\w])(\+|00)?\(?\d[\d\s\-()]{5,}\d(?![\w])")
_NAME_STOP = r"(?=\s+(?:ہے|ہیں|ہوں|اور|میری|میرا|مجھے|عمر)\b|[،,۔.!?؟\n]|$)"
NAME_PATTERNS = [
    re.compile(r"(?:میرا|میری|مریض کا|مریضہ کا|بچے کا|بچی کا|بیٹے کا|بیٹی کا|شوہر کا|بیوی کا|والد کا|والدہ کا)"
               r"\s+نام\s+(?P<n>\S+(?:\s+\S+){0,2}?)" + _NAME_STOP),
    re.compile(r"(?<!\S)نام\s*[:：]\s*(?P<n>\S+(?:\s+\S+){0,2}?)" + _NAME_STOP),
    re.compile(r"(?i)\b(?:my name is|this is|i am called|patient name[:\s]+)\s*(?P<n>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"),
]
NAME_TOKEN, PHONE_TOKEN, ID_TOKEN, EMAIL_TOKEN = "[نام]", "[فون نمبر]", "[شناختی نمبر]", "[ای میل]"
_SKIP_NAMES = {"ہے", "کیا", "نہیں", "معلوم"}


def find_names(text: str) -> list[str]:
    names = []
    for rx in NAME_PATTERNS:
        for m in rx.finditer(text):
            n = m.group("n").strip()
            if n and n not in _SKIP_NAMES and len(n) >= 2:
                names.append(n)
    return names


def redact_pii(text: str, known_names: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (redacted text, names found in this text). Pass the session's earlier names in ``known_names``."""
    if not text:
        return text, []
    out = normalize_urdu(text)
    out = EMAIL_RE.sub(EMAIL_TOKEN, out)
    out = CNIC_RE.sub(ID_TOKEN, out)

    def number(m: re.Match) -> str:
        digits = sum(ch.isdigit() for ch in m.group(0))
        if digits < 7:
            return m.group(0)
        return PHONE_TOKEN if m.group(0).lstrip("( ").startswith(("+", "0")) else ID_TOKEN
    out = LONG_NUMBER_RE.sub(number, out)
    found = find_names(out)
    for n in sorted(set(found) | set(known_names or []), key=len, reverse=True):
        out = re.sub(r"(?<!\w)" + re.escape(n) + r"(?!\w)", NAME_TOKEN, out)
    return out, found


def redact_messages(messages: list[dict], known_names: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Redact the user turns of a chat (system prompt and book passages are not patient data)."""
    names = list(known_names or [])
    for m in messages:
        if m["role"] == "user":
            names += find_names(normalize_urdu(m["content"]))
    out = []
    for m in messages:
        if m["role"] == "user":
            red, _ = redact_pii(m["content"], names)
            out.append({**m, "content": red})
        else:
            out.append(m)
    return out, sorted(set(names))
