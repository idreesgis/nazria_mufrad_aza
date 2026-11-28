# Nazria Mufrad Aza — Knowledge Base & Hakeem–Patient Dataset

Pipeline that turns the OCR export of **«کلیات تحقیقات صابر ملتانی»** (Hakeem Dost Muhammad Saber
Multani, جلد اول + جلد دوم, 1,879 pages) into:

1. a **cleaned, structured knowledge base** (treatises → topics → role sections → RAG chunks),
2. **structured medical entities** (diseases, remedies + ingredients, diet guidance, the six Mufrad Aza tehreekat),
3. a **rule-based Urdu Hakeem ↔ Patient conversation dataset**, every Hakeem answer traceable to book pages,

and loads it all into **PostgreSQL** (schema `nazria`) for a self-hosted conversational model
(RAG retrieval + fine-tuning).

The **REST API** (Django) is the whole backend of the Android app: patient accounts, the questionnaire and
assessment, pulse-video analysis, and a complete audit log. See the [REST API](#rest-api-for-the-android-app) section below and
[`docs/API.md`](docs/API.md).

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

# 2. Load into PostgreSQL (DSN from an env var — never on the command line; URL-encode the password, % -> %25)
export NAZRIA_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
python -m nazria_kb load --csv /path/to/urdu_book.csv

# 3. Re-run integrity checks any time
python -m nazria_kb verify

# 4. Try a consultation in the terminal (add --save to log it). Engine from NAZRIA_ENGINE (default questionnaire)
python -m nazria_kb consult

# 5. AI reviewer, provider evaluation, training export (see below)
python -m nazria_kb review   --provider local --limit 200 [--weights]
python -m nazria_kb evaluate                      # gemini-3.5-flash, judged by gemini-3.5-flash
python -m nazria_kb export-training --mode human_or_ai --out output/train.jsonl

# tests (no network, no real API calls). DB tests run only against a DISPOSABLE database:
python -m pytest -q tests
NAZRIA_TEST_DATABASE_URL='postgresql://…/scratch_db' python -m pytest -q tests
```

Configuration: copy the variable names from `.env.example` (names only, no secrets).

Alternative without Python on the target: restore the dump  
`gunzip -c nazria_kb_dump.sql.gz | psql "$NAZRIA_DATABASE_URL"` (creates schema `nazria` only).

**Operational guarantees**
- *Atomic*: the load is one transaction; a failure leaves the previous data intact.
- *Idempotent*: re-running replaces data; every run is recorded in `nazria.ingest_runs` with source SHA-256 and counts.
- *Review-safe*: expert decisions live in `nazria.conversation_reviews`, keyed by a deterministic `conversation_uid`, and are never truncated.
- *Deterministic*: same CSV → same dataset (seeded templates).
- *Least privilege*: the loader only needs `CREATE` on the database (for schema `nazria`) — use a dedicated DB user.
- *Contained*: the reload truncates only its own tables, without `CASCADE`, so nothing outside the reload set can be emptied.
- *No secrets in output*: database errors are printed with the DSN and password removed.

## Questionnaire consultation (works without any AI provider)

`nazria_kb/engine.py` → `QuestionnaireEngine`, the current default (`NAZRIA_ENGINE=questionnaire`):

1. **Red-flag triage.** Emergency symptoms stop the consultation and refer the patient to a hospital.
2. **Complaint and profile.** Duration, age group, pregnancy.
3. **Seventeen sign questions.** Each option is weighted toward اعصابی / عضلاتی / غدی and **cites the book volume and
   page**:
   - urine colour, bowel habit, body state, gas, taste, heart, burning urine, catarrh, phlegm (vol. 2 pp. 125–134);
   - appetite, thirst, when pain gets worse, joints, skin, hair, the prevailing feeling, and other signs such as
     dizziness, tremor, sneezing, hoarseness, hiccups, nausea, night blindness and bedwetting (vol. 1
     «تحقیقات امراض و علامات» pp. 549–583, one point each). Their labels name the book's term in brackets, for
     example «(نقرس)», so the patient learns what the book calls the sign.
   - Every question has a "normal / none" answer that adds nothing.
   - After an update that adds questions, run `python manage.py seed_questionnaire`; `deploy/update.sh` does this.
     It only inserts what is missing, never overwrites a Hakeem's edit, and never re-activates a question a Hakeem
     switched off.
4. **Result.** The dominant system or tehreek with its mizaj and the symptoms that point to it, then the matching
   topic (e.g. «عضلاتی قبض»), its recipe and dose **only if safe**, and a referral to a qualified practitioner
   (مستند معالج). The patient sees no book name, author, page reference or "حکیم"; the references stay in the
   question bank for the review tools (`strip_references` also cleans book excerpts and AI explanations).
5. **Diet plan** (`nazria_kb/diet.py`) for the diagnosed tehreek: breakfast, lunch, dinner, fruits, dry fruits and a
   qehwa from the corrective food group of vol. 1 «ترتیب غذا بالنظریہ مفرد اعضاء» pp. 685–687 (patient's tehreek →
   foods of the next tehreek in the cycle), with the book's eating rules (pp. 683–688). If only the dominant system is
   known, the plans of its two tehreeks, each with the feeling that tells which one applies. Notes for diabetes, high
   blood pressure, kidney/liver/heart disease, allergies and medicines come from the patient's info.
6. **Three languages** (`nazria_kb/i18n.py`): Urdu is the source; every fixed patient text (questions, messages,
   result, diet plan, intake form, pulse messages) has English and Arabic translations, and `tests/test_i18n.py`
   fails when one is missing. The API chooses the language by `?lang=`, `Accept-Language` or the user's saved
   language. Emergencies, hazardous ingredients and recipe-like text are detected in all three languages, English
   and Arabic complaints are matched to the Urdu book through a glossary, and book excerpts stay in the original
   Urdu.

Safety (`nazria_kb/safety.py`):
- Recipes containing arsenic, mercury, copper sulphate, kushta, aconite, nux vomica, opium, lead and similar are never shown.
  58 remedies are flagged in `remedies.hazard_flags`, and 160 generated conversations in `conversations.hazard_flags`.
- Children, pregnant or breast-feeding women and the elderly never receive recipes.
- The question bank lives in `questionnaire_questions` / `questionnaire_options`. A Hakeem can tune labels and weights there;
  reloads never overwrite those edits. Sessions are logged in `consultation_sessions` / `consultation_messages`.

- Free-text messages are screened for red flags too (`detect_red_flags`), and every book excerpt shown to a patient
  passes the same hazard and vulnerable-group checks as recipes.

## AI engines (optional) — `llm` and `hybrid`

| `NAZRIA_ENGINE` | What happens |
|---|---|
| `questionnaire` (default) | Rule-based, no AI provider. |
| `llm` | Triage, age group and pregnancy questions, then free-text questions answered **only** from retrieved book passages, with جلد/صفحہ citations; "not covered" → referral to a Hakeem. |
| `hybrid` (recommended once a provider is set) | The questionnaire does triage, intake and the tehreek indication; the LLM explains the result in natural Urdu and answers follow-ups from retrieved passages. |

Providers (`NAZRIA_LLM_PROVIDER`): `local` (vLLM, Ollama, LM Studio, llama.cpp via `NAZRIA_LOCAL_STACK`; patient data stays
on-premises), `openai`, `deepseek`, `anthropic` (Claude), `gemini`. **Project default: `gemini` with the model
`gemini-3.5-flash`**, used when `NAZRIA_LLM_PROVIDER` / `NAZRIA_LLM_MODEL` are not set (both can be overridden).

```bash
export NAZRIA_ENGINE=hybrid NAZRIA_ALLOW_EXTERNAL_PROVIDERS=true GEMINI_API_KEY=...   # key from your secret store
python -m nazria_kb consult
```

Every generated answer is checked: red flags before the model is called, hazardous recipes replaced by the
practitioner-only notice, no recipes for vulnerable patients, citations validated against the retrieved pages
(no valid citation → book excerpts instead), and a disclaimer + referral appended. Provider, model, tokens, latency
and the retrieved chunk ids are logged in `consultation_messages`. **If the provider fails, the consultation continues
with the questionnaire** — the patient always gets an answer.

### Data policy for external providers

`openai`, `deepseek`, `anthropic` and `gemini` **refuse to run unless `NAZRIA_ALLOW_EXTERNAL_PROVIDERS=true`**
(default `false`; `local` always runs). When an external provider is used: phone numbers, CNIC/ID numbers, e-mails
and names the patient typed are removed before sending; the patient is told once that an external AI service is used;
the provider is recorded on the session (`consultation_sessions.provider`, `external_provider = true`).
API keys are read from environment variables (names in `.env.example`) and are never written to the DB, git or logs.

### AI reviewer → human Hakeem

`python -m nazria_kb review --provider <p> --limit N` judges generated conversations against their source chunks
(groundedness, citations, safety, Urdu quality), hazard-flagged ones first, resumable, temperature 0, and stores the
verdict with `reviewer_type = 'ai'`. A human review always overrides an AI review and is never overwritten.
`--weights` / `--weights-only` writes `output/QUESTIONNAIRE_WEIGHTS_REVIEW.md` — a report; weights are never changed
automatically. The hand-over guide for the Hakeem is **[docs/REVIEW_GUIDE.md](docs/REVIEW_GUIDE.md)**.
Training export: `--mode human_only` (future default) or `--mode human_or_ai` (now; `NAZRIA_TRAINING_REVIEW_MODE`).

### Provider evaluation

`python -m nazria_kb evaluate` (default: `gemini-3.5-flash`, judged by `gemini-3.5-flash`; other providers with
`--provider gemini,anthropic:<model>`, no judge with `--judge-provider none`) runs a fixed question set
and writes `output/EVALUATION_REPORT.md` (safety handling, groundedness, citation accuracy, Urdu fluency, latency,
tokens, cost if `NAZRIA_PRICE_*` is set).

Details: **[docs/AI_PROVIDER_ARCHITECTURE.md](docs/AI_PROVIDER_ARCHITECTURE.md)**.

## REST API for the Android app (the whole backend)

This is a single Django project: Django 5.2 LTS, Django REST Framework, JWT login, and an OpenAPI spec in
[`docs/openapi.yaml`](docs/openapi.yaml). It contains everything the Android app talks to.

| App | What it does |
|---|---|
| `accounts` | Patients register and log in with phone + password or **Google, Facebook, Apple or Microsoft** (django-allauth; JWT); Hakeem/admin roles; profile; consent record. |
| `consultations` | Questionnaire, emergency triage, book-based assessment (the same `nazria_kb` code as the CLI), each patient's history, AI explanation (off until `NAZRIA_ENGINE=hybrid`). |
| `patients` | The patients of an account (self, family): general info, its change history, prefilled questionnaire answers and re-diagnosis. |
| `pulse` | Pulse-video (PPG) upload and analysis. It was the separate `pulse_diagnosis` project and is now part of this API. |
| `audit` | One append-only log row per API or admin request: who, what, when, IP and result. The database refuses changes to it. |

Nothing is deleted automatically. A patient's "delete" only hides an item from their own history, and staff see the
complete history of every patient. [`docs/API.md`](docs/API.md) covers the endpoints, the login and consultation
flows and the error codes for the Android developer.

**Local setup** (Windows or PyCharm too), using the same `.env` and database as the knowledge base:

```bash
pip install -r requirements.txt
# in .env: DJANGO_SECRET_KEY, DJANGO_DEBUG=true (local), NAZRIA_DATABASE_URL (already there)
python manage.py create_api_schema       # schema "nazria_api" for Django's tables (never "public")
python manage.py migrate
python manage.py create_api_client android-app                     # the app key (X-Api-Key), shown once
python manage.py create_staff --phone 03XXXXXXXXX --name Admin --admin   # admin/Hakeem login (asks a password)
python manage.py runserver 0.0.0.0:8000
```

- Interactive API docs: `http://localhost:8000/api/docs/` (when `DJANGO_DEBUG=true`).
- Admin: `/admin/` (log in with the phone number as `+92…`).
- From the Android emulator: `http://10.0.2.2:8000/api/v1/`.

**Server:** Ubuntu with nginx, gunicorn and systemd, no Docker. The configuration files and step-by-step guide are
in [`deploy/`](deploy/DEPLOY_UBUNTU.md).

**Tests:**
- `pytest` runs every test, the API ones with SQLite and an in-memory knowledge base, so no PostgreSQL is needed.
- With `NAZRIA_TEST_DATABASE_URL` set to a disposable database, the PostgreSQL tests run as well.

**Batch jobs stay in the CLI** (`python -m nazria_kb build|load|verify|review|evaluate|export-training`).

## Using the data directly

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
