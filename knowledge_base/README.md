# Nazria Mufrad Aza — Knowledge Base & Hakeem–Patient Dataset

Pipeline that turns the OCR export of **«کلیات تحقیقات صابر ملتانی»** (Hakeem Dost Muhammad Saber
Multani, جلد اول + جلد دوم, 1,879 pages) into:

1. a **cleaned, structured knowledge base** (treatises → topics → role sections → RAG chunks),
2. **structured medical entities** (diseases, remedies + ingredients, diet guidance, the six Mufrad Aza tehreekat),
3. a **rule-based Urdu Hakeem ↔ Patient conversation dataset**, every Hakeem answer traceable to book pages,

and loads it all into **PostgreSQL** (schema `nazria`) for a self-hosted conversational model
(RAG retrieval + fine-tuning).

## Pipeline

```
urdu_book.csv ──parse──► 1,879 pages ──clean──► typed blocks ──structure──► 25 treatises
 (non-standard CSV)      (2 volumes)   (headers,   (heading/label/  │          2,942 topics
                                        loops,      para/list)      │          3,999 sections
                                        preambles)                  ├─► 6,163 knowledge chunks (RAG)
                                                                    ├─► 289 diseases · 228 remedies · 395 ingredients · 124 diet
                                                                    └─► 2,976 conversations / 7,534 turns
                                                                              │
                                                            PostgreSQL (one transaction, COPY) + JSONL exports
```

| Stage | Module | What it does |
|---|---|---|
| parse | `nazria_kb/parse.py` | Reads the export. Its CSV dialect uses `'` as the escape char (`'"` = `"`); standard readers mis-split ~250 records. |
| clean | `nazria_kb/clean.py` | Urdu normalisation (Arabic ي/ك/ه → ی/ک/ہ, digits), removes running headers (book title, treatise title, printed page no.), code fences, LLM preambles ("Here is the extracted text…"), OCR repetition loops and hallucinated English/code; flags & scores each page. |
| structure | `nazria_kb/structure.py` | Assigns each page to a treatise from its running header (fuzzy-merged OCR variants, run smoothing), merges paragraphs across pages, splits topics on headings and classifies sections into roles (`definition, causes, symptoms, diagnosis, treatment, recipe, dosage, diet, properties, note`), detects tehreek, builds ≤1,400-char chunks on sentence boundaries. |
| entities | `nazria_kb/entities.py` | Diseases, remedies (dosage form, composition, preparation, dose, actions, cautions), ingredient + quantity parsing (تولہ، ماشہ، رتی، حصہ، سیر …, Urdu number words), diet guidance. |
| dialogues | `nazria_kb/dialogues.py` | Deterministic template generator: `consultation` (multi-turn), `remedy_inquiry`, `qa`. Each Hakeem turn carries source refs; every conversation ends with a safety/referral note. |
| db / export | `nazria_kb/db.py`, `export.py` | Idempotent schema, full refresh in one transaction, integrity checks, JSONL + quality report. |

## Usage

```bash
pip install -r requirements.txt

# 1. Build only (no DB): writes JSONL exports + QUALITY_REPORT.md
python -m nazria_kb build --csv /path/to/urdu_book.csv --out output/

# 2. Load into PostgreSQL (DSN from an env var — never on the command line)
export NAZRIA_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
python -m nazria_kb load --csv /path/to/urdu_book.csv

# 3. Re-run integrity checks any time
python -m nazria_kb verify

# tests
python -m pytest -q tests
```

Alternative without Python on the target: restore the dump  
`gunzip -c nazria_kb_dump.sql.gz | psql "$NAZRIA_DATABASE_URL"` (creates schema `nazria` only).

**Operational guarantees**
- *Atomic*: the load is one transaction; a failure leaves the previous data intact.
- *Idempotent*: re-running replaces data; every run is recorded in `nazria.ingest_runs` with source SHA-256 and counts.
- *Review-safe*: expert decisions live in `nazria.conversation_reviews`, keyed by a deterministic `conversation_uid`, and are never truncated.
- *Deterministic*: same CSV → same dataset (seeded templates).
- *Least privilege*: the loader only needs `CREATE` on the database (for schema `nazria`) — use a dedicated DB user.

## Using it from the app

- **RAG**: query `nazria.knowledge_chunks` (`tsv` GIN index, `context_path`, `pages`, `tehreek_code`).
  For semantic search, add pgvector: `ALTER TABLE nazria.knowledge_chunks ADD COLUMN embedding vector(<dim>);`
  and fill it with your local embedding model.
- **Fine-tuning**: `nazria.v_training_messages` returns chat records `{"messages":[system,user,assistant…],"meta":{…}}`
  (`patient` → `user`, `hakeem` → `assistant`); filter on `review_status = 'approved'`.
- **Structured cards**: `diseases`, `remedies`/`remedy_ingredients`, `diet_guidelines`, `tehreek` (mizaj wording taken from the book).

See `sql/example_queries.sql` and `docs/DATA_DICTIONARY.md`.

## Data quality & limitations

- Source is OCR. Spelling errors remain (e.g. «مسار ملتانی»); only 4 pages were corrected in the source tool.
  5 pages are unusable (`ocr_failed` — need re-OCR) and 35 index pages are excluded from the knowledge base.
- Topic boundaries/roles come from rules over headings; some topics are fragments or mis-typed.
- Conversations are **template-based**: correct and grounded but repetitive, with generic patient intake answers.
  They are a seed dataset; richer dialogues need an LLM generation pass later.
- **All conversations are `pending_review`.** A qualified Hakeem must review before any clinical use or training.
  The dataset is informational and does not replace examination by a practitioner.
- The book's text is the publisher's copyrighted work; the raw CSV and generated data are not committed to git.
