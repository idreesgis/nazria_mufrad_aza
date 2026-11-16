"""Read the raw OCR export CSV.

The export has no header row and uses a non-standard CSV dialect: the escape
character is an apostrophe, i.e. ``'"`` is a literal double quote and ``''`` is
a literal apostrophe (``doublequote`` is off). Standard CSV readers mis-split
roughly 250 of the 1,879 records because of this; with the right dialect every
record has exactly 20 fields.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(1 << 30)

# Column positions in the export (determined by profiling; see docs/DATA_DICTIONARY.md)
COLUMNS = [
    "legacy_id",          # 0  surrogate id in the OCR tool
    "page_key",           # 1  volume*1000 + page_no
    "image_file",         # 2  page_<n>.png
    "ocr_text",           # 3  raw OCR (Markdown-ish)
    "ocr_status",         # 4  completed / ...
    "ocr_error",          # 5  always empty
    "ocr_completed_at",   # 6  timestamp
    "review_status",      # 7  pending / in_progress
    "corrected_text",     # 8  manual correction (4 pages)
    "is_corrected",       # 9  '1' when corrected
    "reviewed_at",        # 10 timestamp
    "reviewer_note",      # 11 always empty
    "reviewer",           # 12 'None' / empty
    "html_text",          # 13 HTML rendering of ocr_text
    "source_section_id",  # 14 OCR batch / section id (1-5)
    "volume_no",          # 15 1 = جلد اول, 2 = جلد دوم
    "audio_duration_s",   # 16 TTS duration
    "audio_file",         # 17 TTS mp3
    "audio_generated_at", # 18
    "audio_status",       # 19 not_generated / ready
]


@dataclass
class RawPage:
    legacy_id: int
    page_key: int
    image_file: str
    page_no: int
    volume_no: int
    source_section_id: int | None
    ocr_text: str
    html_text: str
    corrected_text: str
    ocr_status: str
    review_status: str
    is_corrected: bool
    ocr_completed_at: str | None
    reviewed_at: str | None
    audio_status: str
    audio_file: str | None
    audio_duration_s: float | None

    @property
    def best_text(self) -> str:
        """Manual correction wins over raw OCR when present."""
        return self.corrected_text if self.corrected_text.strip() else self.ocr_text


def _none(s: str) -> str | None:
    s = s.strip()
    return s if s and s != "None" else None


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_pages(path: str | Path) -> list[RawPage]:
    pages: list[RawPage] = []
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, doublequote=False, escapechar="'")
        for lineno, row in enumerate(reader, 1):
            if not row:
                continue
            if len(row) != len(COLUMNS):
                raise ValueError(f"record {lineno}: expected {len(COLUMNS)} fields, got {len(row)}")
            r = dict(zip(COLUMNS, row))
            page_no = int(r["image_file"].removeprefix("page_").removesuffix(".png"))
            pages.append(
                RawPage(
                    legacy_id=int(r["legacy_id"]),
                    page_key=int(r["page_key"]),
                    image_file=r["image_file"],
                    page_no=page_no,
                    volume_no=int(r["volume_no"]),
                    source_section_id=int(r["source_section_id"]) if r["source_section_id"] else None,
                    ocr_text=r["ocr_text"],
                    html_text=r["html_text"],
                    corrected_text=r["corrected_text"],
                    ocr_status=r["ocr_status"] or "unknown",
                    review_status=r["review_status"] or "unknown",
                    is_corrected=r["is_corrected"] == "1",
                    ocr_completed_at=_none(r["ocr_completed_at"]),
                    reviewed_at=_none(r["reviewed_at"]),
                    audio_status=r["audio_status"] or "not_generated",
                    audio_file=_none(r["audio_file"]),
                    audio_duration_s=float(r["audio_duration_s"]) if _none(r["audio_duration_s"]) else None,
                )
            )
    pages.sort(key=lambda p: (p.volume_no, p.page_no))
    seen = set()
    for p in pages:
        k = (p.volume_no, p.page_no)
        if k in seen:
            raise ValueError(f"duplicate page {k}")
        seen.add(k)
    return pages
