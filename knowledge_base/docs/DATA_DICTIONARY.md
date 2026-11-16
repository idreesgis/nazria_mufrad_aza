# Data dictionary

## 1. Source file (`urdu_book.csv`)

No header row; 1,879 records × 20 fields; UTF-8. **Dialect:** `quotechar='"'`, `doublequote=False`,
`escapechar="'"` (so `'"` is a literal `"` and `''` a literal `'`). Embedded newlines inside quoted fields.

| # | field | meaning | observed values |
|---|---|---|---|
| 0 | legacy_id | id in the OCR tool | 1416–3447, unique |
| 1 | page_key | volume × 1000 + page | 1001–1949, 2001–2930 |
| 2 | image_file | scan image | `page_<n>.png` |
| 3 | ocr_text | raw OCR (Markdown-ish) | median 2.7k chars; 8 pages > 10k (repetition loops) |
| 4 | ocr_status | | `completed` (all) |
| 5 | ocr_error | | always empty |
| 6 | ocr_completed_at | timestamp | Oct–Nov 2025 |
| 7 | review_status | | `pending` 1,866 / `in_progress` 13 |
| 8 | corrected_text | manual correction | 4 pages |
| 9 | is_corrected | | `1` on 11 pages |
| 10 | reviewed_at | timestamp | 12 pages |
| 11 | reviewer_note | | always empty |
| 12 | reviewer | | `None`/empty |
| 13 | html_text | HTML rendering of field 3 | |
| 14 | source_section_id | OCR batch id (1–5) | **not** a reliable chapter id; treatises come from running headers |
| 15 | volume_no | 1 = جلد اول (949 pages), 2 = جلد دوم (930 pages) | |
| 16–19 | audio_* | TTS duration / file / time / status | 1 page `ready` |

## 2. Database (schema `nazria`)

| table | grain | key columns |
|---|---|---|
| `books` | volume | `book_id` (= volume_no), title, volume_name, author, publisher |
| `tehreek` | Mufrad Aza tehreek (6) | `code` (e.g. «عضلاتی غدی»), primary/secondary system, organs, `mizaj_ur` |
| `treatises` | sub-book (running header), 25 | `book_id`, `ordinal`, title, title_variants (OCR spellings), page range |
| `source_pages` | scanned page, 1,879 | raw OCR + HTML + corrected text (audit), `clean_text`, `printed_page_no`, `quality_score` 0–1, `quality_flags[]` |
| `topics` | heading-delimited subject | `topic_type` ∈ disease / remedy / single_drug / concept, `tehreek_code`, `roles[]`, `pages[]`, `full_text` |
| `topic_sections` | role section of a topic | `role` ∈ overview, definition, causes, symptoms, diagnosis, treatment, recipe, dosage, diet, properties, note |
| `knowledge_chunks` | RAG unit (≤ ~1,400 chars, sentence-aligned) | `context_path` (treatise › topic › heading), `content`, `search_text` (normalised), `tsv` (generated), `pages[]` |
| `diseases` | disease topic | definition, causes, symptoms, diagnosis, treatment |
| `remedies` | named remedy or a disease's recipe | dosage_form, composition, preparation, dosage, actions, caution, indication |
| `remedy_ingredients` | ingredient line | name, quantity_text, quantity_value, unit |
| `diet_guidelines` | diet section | kind ∈ recommended / avoid / general, items[] |
| `conversations` | generated dialogue | `conversation_uid` (deterministic UUIDv5), conv_type, template_id, seed, system_prompt, quality_score |
| `conversation_turns` | one utterance | role ∈ patient / hakeem, content, `source_section_ids[]`, `source_chunk_ids[]` |
| `conversation_reviews` | expert review (persistent) | review_status ∈ pending_review / approved / needs_edit / rejected, reviewer, notes, edited_turns |
| `ingest_runs` | each load | pipeline_version, source_sha256, status, stats (jsonb) |

**Schema v2 (questionnaire and safety)**

| table / column | grain | key columns |
|---|---|---|
| `remedies.hazard_flags`, `conversations.hazard_flags` | text[] | arsenic, mercury, copper_sulphate, lead, aconite, strychnine, datura, opium, cannabis, henbane, croton, kushta |
| `questionnaire_questions` | question | question_id, ordinal, kind (single/multi/text), stage (triage/profile/signs), text_ur, active |
| `questionnaire_options` | answer option | label_ur, `weights` jsonb (e.g. {"عضلاتی": 2}), source_book_id, `source_pages[]` (no FK, so reloads never cascade) |
| `consultation_sessions` | one consultation | session_uid, engine, provider, model, status (in_progress/completed/emergency/abandoned), answers, result |
| `consultation_messages` | one message | role, content, question_id, prompt/completion tokens, latency_ms, source_chunk_ids (reserved for LLM engines) |

`questionnaire_*`, `consultation_*`, `conversation_reviews` and `ingest_runs` are never truncated by a reload.

Views: `v_remedies_patient_safe` (no hazard flags), `v_conversations` (with review state), `v_training_messages` (chat JSON for fine-tuning), `v_dataset_summary`.

### Page quality flags

| flag | meaning | effect |
|---|---|---|
| `ocr_failed` | only garbage after removing loops | excluded from KB; re-OCR needed |
| `table_of_contents` | index / contents page | excluded from KB |
| `degenerate_output` | OCR repetition loop removed | kept |
| `hallucinated_text` | invented English / code removed | kept |
| `llm_preamble` | "Here is the extracted text…" removed | kept |
| `near_empty` | < 80 chars (title / blank pages) | kept |
| `two_column_layout` | reading order may be imperfect | kept |
| `high_latin_ratio` | mostly English text | kept |

`quality_score` = 1 − penalties (unclear markers 0.05 each up to 0.3, plus per-flag penalties).

## 3. JSONL exports

| file | record |
|---|---|
| `conversations.jsonl` | `{"messages":[{"role":"system"|"user"|"assistant","content":…}], "meta":{uid,type,title,volume,pages,template,quality_score,review_status}}` |
| `knowledge_chunks.jsonl` | `{id, volume, treatise, topic, role, context, text, pages, tehreek}` |
| `topics.jsonl` | `{index, volume, treatise, title, type, tehreek, pages, sections:[{role,heading,text,pages}]}` |
| `remedies.jsonl` | `{name, dosage_form, indication, tehreek, composition, preparation, dosage, actions, caution, pages, ingredients:[…]}` |
| `stats.json`, `QUALITY_REPORT.md` | run statistics and quality report |
