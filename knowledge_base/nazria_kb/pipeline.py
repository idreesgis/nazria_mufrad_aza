"""End-to-end build: CSV -> in-memory Dataset (no database needed)."""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import PIPELINE_VERSION
from .clean import CleanPage, HeaderModel, clean_page
from .dialogues import Conversation, generate
from .entities import Disease, DietGuideline, Remedy, extract_entities
from .normalize import search_key
from .parse import RawPage, file_sha256, read_pages
from .structure import Chunk, Topic, Treatise, assign_treatises, build_chunks, build_topics

log = logging.getLogger("nazria_kb")
UID_NAMESPACE = uuid.UUID("5d0c3a52-6f43-4c1e-9b0e-6e617a726961")

BOOKS = {
    1: dict(title="کلیات تحقیقات صابر ملتانی", volume_name="جلد اول"),
    2: dict(title="کلیات تحقیقات صابر ملتانی", volume_name="جلد دوم"),
}
AUTHOR = "حکیم انقلاب دوست محمد صابر ملتانی"
PUBLISHER = "ادارہ مطبوعات سلیمانی، اردو بازار لاہور"


@dataclass
class Dataset:
    source_path: str
    source_sha256: str
    raw_pages: list[RawPage]
    pages: list[CleanPage]
    treatises: list[Treatise]
    page_treatise: dict[tuple[int, int], int]
    topics: list[Topic]
    chunks: list[Chunk]
    diseases: list[Disease]
    remedies: list[Remedy]
    diets: list[DietGuideline]
    conversations: list[Conversation]
    conversation_uids: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def stats(self) -> dict:
        flags = Counter(f for p in self.pages for f in p.flags)
        return {
            "pipeline_version": PIPELINE_VERSION,
            "source_sha256": self.source_sha256,
            "pages": len(self.pages),
            "pages_per_volume": dict(Counter(p.volume_no for p in self.pages)),
            "pages_excluded_from_kb": sum(1 for p in self.pages if {"ocr_failed", "table_of_contents"} & set(p.flags)),
            "page_quality_flags": dict(flags),
            "unclear_markers": sum(p.unclear_count for p in self.pages),
            "mean_page_quality": round(sum(p.quality_score for p in self.pages) / len(self.pages), 3),
            "treatises": len(self.treatises),
            "topics": len(self.topics),
            "topics_by_type": dict(Counter(t.topic_type for t in self.topics)),
            "sections": sum(len(t.sections) for t in self.topics),
            "chunks": len(self.chunks),
            "chunks_by_role": dict(Counter(c.role for c in self.chunks)),
            "chunk_chars_avg": round(sum(len(c.text) for c in self.chunks) / max(1, len(self.chunks))),
            "diseases": len(self.diseases),
            "remedies": len(self.remedies),
            "remedy_ingredients": sum(len(r.ingredients) for r in self.remedies),
            "diet_guidelines": len(self.diets),
            "conversations": len(self.conversations),
            "conversations_by_type": dict(Counter(c.conv_type for c in self.conversations)),
            "conversation_turns": sum(len(c.turns) for c in self.conversations),
            "timings_s": self.timings,
        }


def _uids(convs: list[Conversation], topics: list[Topic]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for c in convs:
        t = topics[c.topic_index]
        base = f"{c.conv_type}|{c.template_id}|{t.volume_no}|{search_key(t.title)}|{t.pages[0] if t.pages else 0}"
        seen[base] += 1
        out.append(str(uuid.uuid5(UID_NAMESPACE, f"{base}|{seen[base]}")))
    return out


def build(csv_path: str | Path) -> Dataset:
    timings: dict[str, float] = {}
    t0 = time.time()
    raw = read_pages(csv_path)
    sha = file_sha256(csv_path)
    timings["parse"] = round(time.time() - t0, 2)
    log.info("parsed %d pages", len(raw))

    t0 = time.time()
    headers = HeaderModel().fit([p.best_text for p in raw])
    pages = [clean_page(p.best_text, p.volume_no, p.page_no, headers) for p in raw]
    timings["clean"] = round(time.time() - t0, 2)
    log.info("cleaned pages; flags=%s", dict(Counter(f for p in pages for f in p.flags)))

    t0 = time.time()
    treatises, page_map = assign_treatises(pages)
    topics = build_topics(pages, treatises, page_map)
    chunks = build_chunks(topics, treatises)
    diseases, remedies, diets = extract_entities(topics)
    timings["structure"] = round(time.time() - t0, 2)
    log.info("%d treatises, %d topics, %d chunks", len(treatises), len(topics), len(chunks))

    t0 = time.time()
    page_quality = {(p.volume_no, p.page_no): p.quality_score for p in pages}
    convs = generate(topics, treatises, page_quality)
    timings["dialogues"] = round(time.time() - t0, 2)
    log.info("%d conversations", len(convs))

    ds = Dataset(str(csv_path), sha, raw, pages, treatises, page_map, topics, chunks, diseases, remedies, diets,
                 convs, timings=timings)
    ds.conversation_uids = _uids(convs, topics)
    return ds
