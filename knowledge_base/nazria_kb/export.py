"""File exports (no DB needed): JSONL for fine-tuning / RAG and a quality report."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .pipeline import Dataset
from .normalize import search_key


def _w(path: Path, rows) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def export(ds: Dataset, out_dir: str | Path) -> dict[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    counts["conversations.jsonl"] = _w(out / "conversations.jsonl", (
        {
            "messages": [{"role": "system", "content": c.system_prompt}] + [
                {"role": "user" if t.role == "patient" else "assistant", "content": t.content} for t in c.turns],
            "meta": {"uid": uid, "type": c.conv_type, "title": c.title, "volume": c.volume_no, "pages": c.pages,
                     "template": c.template_id, "quality_score": c.quality_score, "review_status": "pending_review"},
        } for uid, c in zip(ds.conversation_uids, ds.conversations)))
    tr = {t.ordinal: t for t in ds.treatises}
    counts["knowledge_chunks.jsonl"] = _w(out / "knowledge_chunks.jsonl", (
        {"id": f"v{c.volume_no}-t{c.topic_index}-s{c.section_index}-c{c.ordinal}", "volume": c.volume_no,
         "treatise": tr[c.treatise_ordinal].title, "topic": ds.topics[c.topic_index].title, "role": c.role,
         "context": c.context, "text": c.text, "pages": c.pages, "tehreek": ds.topics[c.topic_index].tehreek}
        for c in ds.chunks))
    counts["topics.jsonl"] = _w(out / "topics.jsonl", (
        {"index": i, "volume": t.volume_no, "treatise": tr[t.treatise_ordinal].title, "title": t.title,
         "type": t.topic_type, "tehreek": t.tehreek, "pages": t.pages,
         "sections": [{"role": s.role, "heading": s.heading, "text": s.text, "pages": s.pages} for s in t.sections]}
        for i, t in enumerate(ds.topics)))
    counts["remedies.jsonl"] = _w(out / "remedies.jsonl", (
        {"name": r.name, "dosage_form": r.dosage_form, "indication": r.indication, "tehreek": r.tehreek,
         "composition": r.composition_text, "preparation": r.preparation_text, "dosage": r.dosage_text,
         "actions": r.actions_text, "caution": r.caution_text, "pages": r.pages,
         "ingredients": [{"name": i.name, "quantity": i.quantity_text, "value": i.quantity_value, "unit": i.unit}
                         for i in r.ingredients]} for r in ds.remedies))
    (out / "stats.json").write_text(json.dumps(ds.stats(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "QUALITY_REPORT.md").write_text(quality_report(ds), encoding="utf-8")
    return counts


def quality_report(ds: Dataset) -> str:
    s = ds.stats()
    lines = ["# Data quality report", "",
             f"Source SHA-256: `{ds.source_sha256}`  ", f"Pipeline version: `{s['pipeline_version']}`", "",
             "## Pages", "", "| metric | value |", "|---|---|"]
    for k in ("pages", "pages_excluded_from_kb", "unclear_markers", "mean_page_quality"):
        lines.append(f"| {k} | {s[k]} |")
    lines += ["", "### Page quality flags", "", "| flag | pages | meaning |", "|---|---|---|"]
    meaning = {
        "ocr_failed": "OCR produced only garbage (repetition loop); page excluded from the knowledge base",
        "degenerate_output": "OCR repetition loop removed",
        "hallucinated_text": "OCR model invented English/code text; removed",
        "table_of_contents": "index/TOC page; excluded from the knowledge base",
        "near_empty": "less than 80 characters of text (title/blank pages)",
        "llm_preamble": "'Here is the extracted text…' line removed",
        "two_column_layout": "two-column page; reading order may be imperfect",
        "high_latin_ratio": "page is mostly English",
    }
    for f, n in sorted(s["page_quality_flags"].items(), key=lambda x: -x[1]):
        lines.append(f"| {f} | {n} | {meaning.get(f, '')} |")
    bad = [p for p in ds.pages if "ocr_failed" in p.flags]
    if bad:
        lines += ["", "**Pages needing re-OCR:** " + ", ".join(f"vol {p.volume_no} p.{p.page_no}" for p in bad)]
    lines += ["", "## Treatises", "", "| # | vol | title | pages |", "|---|---|---|---|"]
    for t in ds.treatises:
        lines.append(f"| {t.ordinal} | {t.volume_no} | {t.title} | {t.pages[0]}–{t.pages[-1]} ({len(t.pages)}) |")
    lines += ["", "## Structure", "", "| metric | value |", "|---|---|"]
    for k in ("topics", "sections", "chunks", "chunk_chars_avg", "diseases", "remedies", "remedy_ingredients",
              "diet_guidelines", "conversations", "conversation_turns"):
        lines.append(f"| {k} | {s[k]} |")
    lines += ["", "Topics by type: " + ", ".join(f"{k}={v}" for k, v in s["topics_by_type"].items()),
              "", "Conversations by type: " + ", ".join(f"{k}={v}" for k, v in s["conversations_by_type"].items()),
              "", "## Known limitations", "",
              "- Text is OCR output: spelling errors remain (e.g. 'مسار ملتانی' for 'صابر ملتانی'); only 4 pages were manually corrected at source.",
              "- Topic boundaries and roles are inferred from headings with rules; some topics are fragments.",
              "- Conversations are rule-based templates: wording is repetitive and the patient's intake answers are generic.",
              "- Every conversation is `pending_review`: a qualified Hakeem must approve before clinical use or training.",
              ""]
    teh = Counter(t.tehreek for t in ds.topics if t.tehreek)
    lines += ["## Tehreek coverage (topics)", "", ", ".join(f"{k}: {v}" for k, v in teh.most_common()), ""]
    dup = Counter(search_key(c.text) for c in ds.chunks)
    lines += [f"Duplicate chunk texts: {sum(v - 1 for v in dup.values() if v > 1)}", ""]
    return "\n".join(lines)
