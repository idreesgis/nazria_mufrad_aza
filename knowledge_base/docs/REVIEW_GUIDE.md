# Reviewer guide — conversations and questionnaire weights

For the specialist Hakeem who takes over from the AI reviewer. Everything happens in the PostgreSQL schema
`nazria` with plain SQL (any client: psql, DBeaver, pgAdmin). Nothing here needs Python.

## 1. Principles

| Rule | How the database enforces it |
|---|---|
| **A human review always wins.** | `reviewer_type` is set from the reviewer name: a name starting with `ai:` is an AI review; **any other name is a human review**. A trigger (`trg_guard_conversation_review`) blocks an AI write from replacing a human decision. |
| The AI's opinion is never lost. | The AI verdict stays in `conversation_reviews.ai_details` (status, scores, notes, model) after you override it. |
| Reloading the book never touches reviews or the question bank. | `conversation_reviews`, `questionnaire_*` are not truncated; reviews re-attach through the stable `conversation_uid`. |
| Hazard-flagged conversations are not exported for training unless asked. | `nazria.training_messages(mode, include_hazardous => false)`. |

Always write **your own name** in `reviewer` (e.g. `'Hakeem Ahmad'`) and set `reviewed_at = now()`.

## 2. Conversations

Statuses: `approved` (use for training as is) · `needs_edit` (fixable; edit or send back) · `rejected` (never use) ·
`pending_review` (not reviewed).

### 2.1 Your queue

```sql
-- AI-reviewed, not yet seen by a human: hazard-flagged and AI-rejected first
SELECT c.conversation_uid, c.conv_type, c.title, c.pages, c.hazard_flags,
       r.review_status AS ai_status, r.notes AS ai_notes,
       r.ai_details -> 'judge' ->> 'groundedness' AS groundedness
FROM nazria.conversations c
JOIN nazria.conversation_reviews r USING (conversation_uid)
WHERE r.reviewer_type = 'ai'
ORDER BY cardinality(c.hazard_flags) > 0 DESC,
         array_position(ARRAY['rejected','needs_edit','approved'], r.review_status), c.conversation_id
LIMIT 50;

-- read one conversation with its turns
SELECT t.turn_index, t.role, t.content, t.source_chunk_ids
FROM nazria.conversation_turns t JOIN nazria.conversations c USING (conversation_id)
WHERE c.conversation_uid = '<uid>' ORDER BY t.turn_index;

-- the book passages the Hakeem turns were built from
SELECT k.chunk_id, k.context_path, k.pages, k.content
FROM nazria.knowledge_chunks k
WHERE k.chunk_id IN (SELECT unnest(t.source_chunk_ids) FROM nazria.conversation_turns t
                     JOIN nazria.conversations c USING (conversation_id) WHERE c.conversation_uid = '<uid>');
```

Check each conversation for: **groundedness** (every Hakeem statement is in the passages), **citations**
(جلد/صفحہ match the passages), **safety** (no hazardous recipe — سنکھیا، پارہ/شنگرف، کشتہ، کچلہ، افیون، بھنگ،
دھتورا …; ends with a referral to a Hakeem/doctor), **Urdu quality**.

### 2.2 Approve / reject / needs edit

```sql
INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer, notes, reviewed_at)
VALUES ('<uid>', 'approved', 'Hakeem Ahmad', 'checked against vol 2 p.127', now())
ON CONFLICT (conversation_uid) DO UPDATE
SET review_status = EXCLUDED.review_status, reviewer = EXCLUDED.reviewer,
    notes = EXCLUDED.notes, reviewed_at = now();
```

Use `'rejected'` or `'needs_edit'` the same way. (`reviewer_type` becomes `'human'` automatically.)

### 2.3 Edit turns

Write the corrected text of one or more turns into `edited_turns`; the generated text stays untouched for audit,
and the training export uses your version.

```sql
INSERT INTO nazria.conversation_reviews (conversation_uid, review_status, reviewer, edited_turns, notes, reviewed_at)
VALUES ('<uid>', 'approved', 'Hakeem Ahmad',
        '[{"turn_index": 3, "content": "درست شدہ جواب … (جلد دوم، صفحہ 127)"}]', 'removed kushta recipe', now())
ON CONFLICT (conversation_uid) DO UPDATE
SET review_status = EXCLUDED.review_status, reviewer = EXCLUDED.reviewer, edited_turns = EXCLUDED.edited_turns,
    notes = EXCLUDED.notes, reviewed_at = now();
```

### 2.4 Bulk decisions (after spot checks)

```sql
-- accept the AI's 'approved' verdicts of non-hazardous qa conversations you sampled and agree with
UPDATE nazria.conversation_reviews r SET reviewer = 'Hakeem Ahmad', notes = coalesce(notes,'') || ' [human: bulk accepted]',
       reviewed_at = now()
FROM nazria.conversations c
WHERE c.conversation_uid = r.conversation_uid AND r.reviewer_type = 'ai' AND r.review_status = 'approved'
  AND c.conv_type = 'qa' AND cardinality(c.hazard_flags) = 0;
```

### 2.5 Progress

```sql
SELECT reviewer_type, review_status, count(*) FROM nazria.v_conversations GROUP BY 1, 2 ORDER BY 1, 2;
```

## 3. Questionnaire weights

The AI writes a **report only**: `output/QUESTIONNAIRE_WEIGHTS_REVIEW.md` (`python -m nazria_kb review --weights-only`).
Rows marked ⚠️ need your decision. You change the bank directly; reloads never overwrite your edits.

```sql
-- current bank
SELECT q.ordinal, q.question_id, q.stage, q.active, o.ordinal, o.option_key, o.label_ur, o.weights, o.source_pages
FROM nazria.questionnaire_questions q JOIN nazria.questionnaire_options o USING (question_id)
ORDER BY q.ordinal, o.ordinal;

-- change a weight (systems: اعصابی / عضلاتی / غدی) and its page citation
UPDATE nazria.questionnaire_options
SET weights = '{"اعصابی": 1}', source_pages = '{126}'
WHERE question_id = 'taste' AND option_key = 'sweet';

-- change wording
UPDATE nazria.questionnaire_options SET label_ur = 'میٹھا یا پھیکا' WHERE question_id = 'taste' AND option_key = 'sweet';

-- switch a whole question off (do not DELETE: a reload would re-insert missing rows)
UPDATE nazria.questionnaire_questions SET active = false WHERE question_id = 'abdomen';

-- neutralise one option (keeps the answer choice, scores nothing)
UPDATE nazria.questionnaire_options SET weights = '{}' WHERE question_id = 'abdomen' AND option_key = 'gas';
```

Every option that carries a weight must cite at least one page (`source_pages`); `python -m nazria_kb verify` checks this.
Option order (`ordinal`) is the number the patient types — change it only together with the app.

## 4. Training export

```bash
python -m nazria_kb export-training --mode human_only  --out output/train.jsonl   # human-approved only (future default)
python -m nazria_kb export-training --mode human_or_ai --out output/train.jsonl   # + AI-approved where no human yet (now)
```

or in SQL: `SELECT record FROM nazria.training_messages('human_only');`
When you have reviewed enough conversations, set `NAZRIA_TRAINING_REVIEW_MODE=human_only` so that becomes the default.

## 5. Re-running the AI reviewer

`python -m nazria_kb review --provider <p> --limit N` only picks conversations with no review (or a blank
`pending_review` row). It never re-reviews or overwrites your decisions.
