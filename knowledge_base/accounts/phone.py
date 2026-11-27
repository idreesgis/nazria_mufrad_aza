"""Phone numbers as login names: one canonical form (+<country><number>) whatever the patient types."""
from __future__ import annotations

import re

from django.conf import settings

_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_phone(raw: str, country_code: str | None = None) -> str:
    """'0300-1234567', '+92 300 1234567', '00923001234567', '۰۳۰۰۱۲۳۴۵۶۷' -> '+923001234567'.
    Raises ValueError for anything that is not a plausible phone number."""
    cc = country_code or settings.NAZRIA_DEFAULT_COUNTRY_CODE
    s = (raw or "").translate(_URDU_DIGITS).strip()
    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
    elif s.startswith("0"):
        digits = cc + s[1:]
    else:
        digits = s if s.startswith(cc) and len(s) > 10 else cc + s
    if not digits.isdigit() or not 10 <= len(digits) <= 15:
        raise ValueError("not a valid phone number")
    return "+" + digits
