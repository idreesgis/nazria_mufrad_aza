-- Example queries for the Hakeem conversational app.  SET search_path = nazria;

-- 1) RAG retrieval: top passages for a patient's message (keyword / full-text).
--    Normalise the query the same way as search_text (nazria_kb.normalize.search_key) in the app.
SELECT chunk_id, context_path, role, pages, tehreek_code,
       ts_rank(tsv, q) AS score, content
FROM nazria.knowledge_chunks, plainto_tsquery('simple', 'نزلہ زکام علاج') AS q
WHERE tsv @@ q
ORDER BY score DESC, quality_score DESC
LIMIT 5;

-- 2) Everything about one condition (structured), e.g. for a "disease card" in the UI.
SELECT d.name, d.tehreek_code, t.mizaj_ur, d.definition, d.causes, d.symptoms, d.treatment, d.pages
FROM nazria.diseases d LEFT JOIN nazria.tehreek t ON t.code = d.tehreek_code
WHERE d.name_key LIKE '%' || 'کھانسی' || '%';

-- 3) Remedies for a tehreek, with ingredients.
SELECT r.name, r.dosage_form, r.dosage_text,
       string_agg(i.ingredient_name || ' ' || coalesce(i.quantity_text, ''), '، ' ORDER BY i.ordinal) AS ingredients
FROM nazria.remedies r JOIN nazria.remedy_ingredients i USING (remedy_id)
WHERE r.tehreek_code = 'عضلاتی غدی'
GROUP BY r.remedy_id
ORDER BY r.name;

-- 4) Expert review workflow (survives reloads; keyed by the stable uid).
INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer, notes, reviewed_at)
VALUES ('00000000-0000-0000-0000-000000000000', 'approved', 'Hakeem <name>', 'checked against p. 535', now())
ON CONFLICT (conversation_uid) DO UPDATE
SET review_status = EXCLUDED.review_status, reviewer = EXCLUDED.reviewer,
    notes = EXCLUDED.notes, reviewed_at = EXCLUDED.reviewed_at;

-- 5) Fine-tuning export: approved conversations as chat JSON (one record per line).
--    psql -At -c "SELECT record FROM nazria.v_training_messages WHERE review_status='approved'" > train.jsonl
SELECT record FROM nazria.v_training_messages WHERE review_status = 'approved' LIMIT 3;

-- 6) Provenance of an answer: which book pages a Hakeem turn came from.
SELECT ct.turn_index, ct.role, k.context_path, k.pages
FROM nazria.conversation_turns ct
CROSS JOIN LATERAL unnest(ct.source_chunk_ids) AS cid
JOIN nazria.knowledge_chunks k ON k.chunk_id = cid
WHERE ct.conversation_id = 1;

-- 7) Pages that need re-OCR.
SELECT book_id, page_no, quality_flags FROM nazria.source_pages
WHERE 'ocr_failed' = ANY (quality_flags) ORDER BY 1, 2;
