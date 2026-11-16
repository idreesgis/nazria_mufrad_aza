-- =====================================================================
-- Nazria Mufrad Aza knowledge base  —  PostgreSQL schema (v1)
-- Source: «کلیات تحقیقات صابر ملتانی» (جلد اول + جلد دوم), OCR export
-- All objects live in schema `nazria`. Idempotent: safe to re-run.
-- Requires PostgreSQL >= 12 (generated columns). No extensions required.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS nazria;
SET search_path = nazria, public;

CREATE TABLE IF NOT EXISTS schema_version (
    version      int         PRIMARY KEY,
    applied_at   timestamptz NOT NULL DEFAULT now(),
    description  text        NOT NULL
);
INSERT INTO schema_version (version, description)
VALUES (1, 'initial knowledge base + conversation dataset schema')
ON CONFLICT (version) DO NOTHING;

-- ------------------------------------------------------------------ lineage
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_version  text        NOT NULL,
    source_file       text        NOT NULL,
    source_sha256     char(64)    NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    stats             jsonb       NOT NULL DEFAULT '{}'::jsonb
);

-- ------------------------------------------------------------------ reference
CREATE TABLE IF NOT EXISTS books (
    book_id      smallint PRIMARY KEY,
    volume_no    smallint NOT NULL UNIQUE,
    title        text     NOT NULL,
    volume_name  text     NOT NULL,
    author       text     NOT NULL,
    publisher    text,
    page_count   int      NOT NULL
);

-- The six Mufrad Aza tehreekat (organ-system combinations).
-- mizaj wording is taken from the book (most frequent co-occurrence in the text).
CREATE TABLE IF NOT EXISTS tehreek (
    code             text PRIMARY KEY,           -- e.g. 'عضلاتی غدی'
    code_en          text NOT NULL UNIQUE,       -- e.g. 'muscular-glandular'
    primary_system   text NOT NULL,              -- اعصابی / عضلاتی / غدی
    secondary_system text NOT NULL,
    primary_organs   text NOT NULL,
    mizaj_ur         text NOT NULL,              -- e.g. 'خشک گرم'
    mizaj_en         text NOT NULL
);

CREATE TABLE IF NOT EXISTS treatises (
    treatise_id    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id        smallint NOT NULL REFERENCES books(book_id),
    ordinal        int      NOT NULL,
    title          text     NOT NULL,
    title_variants text[]   NOT NULL DEFAULT '{}',   -- OCR spellings of the running header
    start_page     int      NOT NULL,
    end_page       int      NOT NULL,
    page_count     int      NOT NULL,
    UNIQUE (book_id, ordinal)
);

-- ------------------------------------------------------------------ source (audit layer)
CREATE TABLE IF NOT EXISTS source_pages (
    page_id            int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id            smallint NOT NULL REFERENCES books(book_id),
    page_no            int      NOT NULL,            -- scan / image page number
    printed_page_no    int,                          -- number printed on the page (from header)
    treatise_id        int      REFERENCES treatises(treatise_id),
    legacy_id          int      NOT NULL,            -- id in the OCR tool export
    page_key           int      NOT NULL,            -- volume*1000 + page
    image_file         text     NOT NULL,
    source_section_id  smallint,
    raw_ocr_text       text     NOT NULL,
    raw_html           text,
    corrected_text     text,
    clean_text         text     NOT NULL,
    ocr_status         text,
    review_status      text,
    is_corrected       boolean  NOT NULL DEFAULT false,
    ocr_completed_at   timestamptz,
    reviewed_at        timestamptz,
    quality_score      numeric(3,2) NOT NULL,
    quality_flags      text[]   NOT NULL DEFAULT '{}',
    unclear_count      int      NOT NULL DEFAULT 0,
    raw_char_count     int      NOT NULL,
    clean_char_count   int      NOT NULL,
    audio_status       text,
    audio_file         text,
    audio_duration_s   numeric,
    UNIQUE (book_id, page_no)
);
CREATE INDEX IF NOT EXISTS ix_source_pages_treatise ON source_pages (treatise_id);
CREATE INDEX IF NOT EXISTS ix_source_pages_flags ON source_pages USING gin (quality_flags);

-- ------------------------------------------------------------------ structured knowledge
CREATE TABLE IF NOT EXISTS topics (
    topic_id        int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id         smallint NOT NULL REFERENCES books(book_id),
    treatise_id     int      NOT NULL REFERENCES treatises(treatise_id),
    ordinal         int      NOT NULL,              -- reading order within the whole dataset
    title           text     NOT NULL,
    title_key       text     NOT NULL,              -- normalised (no diacritics) for lookup
    topic_type      text     NOT NULL CHECK (topic_type IN ('disease', 'remedy', 'single_drug', 'concept')),
    tehreek_code    text     REFERENCES tehreek(code),
    tehreek_counts  jsonb    NOT NULL DEFAULT '{}'::jsonb,
    roles           text[]   NOT NULL DEFAULT '{}',
    pages           int[]    NOT NULL,
    start_page      int      NOT NULL,
    end_page        int      NOT NULL,
    full_text       text     NOT NULL,
    char_count      int      NOT NULL,
    UNIQUE (ordinal)
);
CREATE INDEX IF NOT EXISTS ix_topics_type ON topics (topic_type);
CREATE INDEX IF NOT EXISTS ix_topics_title_key ON topics (title_key);
CREATE INDEX IF NOT EXISTS ix_topics_treatise ON topics (treatise_id);

CREATE TABLE IF NOT EXISTS topic_sections (
    section_id  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id    int  NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    ordinal     int  NOT NULL,
    role        text NOT NULL CHECK (role IN ('overview','definition','causes','symptoms','diagnosis','treatment',
                                              'recipe','dosage','diet','properties','note')),
    heading     text,
    content     text NOT NULL,
    pages       int[] NOT NULL,
    UNIQUE (topic_id, ordinal)
);
CREATE INDEX IF NOT EXISTS ix_topic_sections_role ON topic_sections (role);

-- RAG retrieval units. `search_text` is diacritic-free normalised Urdu; `tsv` uses the
-- language-agnostic 'simple' config (PostgreSQL has no Urdu stemmer).
-- For semantic search add pgvector and:  ALTER TABLE nazria.knowledge_chunks ADD COLUMN embedding vector(<dim>);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id      int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id       smallint NOT NULL REFERENCES books(book_id),
    treatise_id   int      NOT NULL REFERENCES treatises(treatise_id),
    topic_id      int      NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    section_id    int      NOT NULL REFERENCES topic_sections(section_id) ON DELETE CASCADE,
    ordinal       int      NOT NULL,                 -- order within the section
    role          text     NOT NULL,
    context_path  text     NOT NULL,                 -- treatise › topic › heading
    content       text     NOT NULL,
    search_text   text     NOT NULL,
    char_count    int      NOT NULL,
    word_count    int      NOT NULL,
    pages         int[]    NOT NULL,
    start_page    int      NOT NULL,
    end_page      int      NOT NULL,
    tehreek_code  text     REFERENCES tehreek(code),
    quality_score numeric(3,2) NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', context_path || ' ' || search_text)) STORED,
    UNIQUE (section_id, ordinal)
);
CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON knowledge_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS ix_chunks_topic ON knowledge_chunks (topic_id);
CREATE INDEX IF NOT EXISTS ix_chunks_role ON knowledge_chunks (role);

CREATE TABLE IF NOT EXISTS diseases (
    disease_id    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id      int  NOT NULL UNIQUE REFERENCES topics(topic_id) ON DELETE CASCADE,
    name          text NOT NULL,
    name_key      text NOT NULL,
    tehreek_code  text REFERENCES tehreek(code),
    definition    text,
    causes        text,
    symptoms      text,
    diagnosis     text,
    treatment     text,
    pages         int[] NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_diseases_name_key ON diseases (name_key);

CREATE TABLE IF NOT EXISTS remedies (
    remedy_id         int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id          int  NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    disease_id        int  REFERENCES diseases(disease_id) ON DELETE SET NULL,
    name              text NOT NULL,
    name_key          text NOT NULL,
    dosage_form       text,               -- سفوف، حب، معجون، شربت، کشتہ، روغن ...
    composition_text  text NOT NULL,
    preparation_text  text,
    dosage_text       text,
    actions_text      text,               -- افعال و اثرات / فوائد
    caution_text      text,
    indication        text,
    tehreek_code      text REFERENCES tehreek(code),
    pages             int[] NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_remedies_name_key ON remedies (name_key);

CREATE TABLE IF NOT EXISTS remedy_ingredients (
    ingredient_id   int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    remedy_id       int  NOT NULL REFERENCES remedies(remedy_id) ON DELETE CASCADE,
    ordinal         int  NOT NULL,
    ingredient_name text NOT NULL,
    quantity_text   text,
    quantity_value  numeric,
    unit            text,                 -- تولہ، ماشہ، رتی، حصہ، سیر ...
    UNIQUE (remedy_id, ordinal)
);
CREATE INDEX IF NOT EXISTS ix_ingredients_name ON remedy_ingredients (ingredient_name);

CREATE TABLE IF NOT EXISTS diet_guidelines (
    diet_id     int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id    int  NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    disease_id  int  REFERENCES diseases(disease_id) ON DELETE SET NULL,
    kind        text NOT NULL CHECK (kind IN ('recommended', 'avoid', 'general')),
    content     text NOT NULL,
    items       text[] NOT NULL DEFAULT '{}',
    pages       int[]  NOT NULL
);

-- ------------------------------------------------------------------ conversation dataset
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id   int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_uid  uuid  NOT NULL UNIQUE,      -- deterministic: stable across reloads
    conv_type         text  NOT NULL CHECK (conv_type IN ('consultation', 'remedy_inquiry', 'qa')),
    title             text  NOT NULL,
    topic_id          int   NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    book_id           smallint NOT NULL REFERENCES books(book_id),
    template_id       text  NOT NULL,
    generator         text  NOT NULL,
    seed              bigint NOT NULL,
    language          text  NOT NULL DEFAULT 'ur',
    system_prompt     text  NOT NULL,
    turn_count        int   NOT NULL,
    pages             int[] NOT NULL,
    quality_score     numeric(4,3) NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_type ON conversations (conv_type);
CREATE INDEX IF NOT EXISTS ix_conversations_topic ON conversations (topic_id);

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id    int   NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    turn_index         int   NOT NULL,
    role               text  NOT NULL CHECK (role IN ('patient', 'hakeem')),
    content            text  NOT NULL,
    source_section_ids int[] NOT NULL DEFAULT '{}',
    source_chunk_ids   int[] NOT NULL DEFAULT '{}',
    UNIQUE (conversation_id, turn_index)
);

-- Expert review state is keyed by the stable uid and is NEVER truncated by reloads.
CREATE TABLE IF NOT EXISTS conversation_reviews (
    conversation_uid  uuid PRIMARY KEY,
    review_status     text NOT NULL DEFAULT 'pending_review'
                      CHECK (review_status IN ('pending_review', 'approved', 'needs_edit', 'rejected')),
    reviewer          text,
    notes             text,
    edited_turns      jsonb,             -- optional reviewer rewrite: [{"turn_index":n,"content":"..."}]
    reviewed_at       timestamptz
);

-- ------------------------------------------------------------------ v2 columns (added before views)
-- Hazardous ingredients (arsenic, mercury, copper sulphate, kushta …) found in the text.
ALTER TABLE remedies      ADD COLUMN IF NOT EXISTS hazard_flags text[] NOT NULL DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS hazard_flags text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS ix_remedies_hazards ON remedies USING gin (hazard_flags);

-- ------------------------------------------------------------------ views
-- Views are dropped and recreated so that new table columns never break CREATE OR REPLACE.
DROP VIEW IF EXISTS v_training_messages, v_conversations, v_dataset_summary, v_remedies_patient_safe CASCADE;
CREATE VIEW v_conversations AS
SELECT c.*, coalesce(r.review_status, 'pending_review') AS review_status, r.reviewer, r.reviewed_at
FROM conversations c
LEFT JOIN conversation_reviews r USING (conversation_uid);

-- OpenAI/HF-style chat records for fine-tuning (system + user/assistant turns).
CREATE VIEW v_training_messages AS
SELECT c.conversation_id,
       c.conversation_uid,
       c.conv_type,
       c.review_status,
       c.quality_score,
       jsonb_build_object(
           'messages',
           jsonb_build_array(jsonb_build_object('role', 'system', 'content', c.system_prompt)) ||
           (SELECT jsonb_agg(jsonb_build_object('role', CASE t.role WHEN 'patient' THEN 'user' ELSE 'assistant' END,
                                                'content', t.content) ORDER BY t.turn_index)
            FROM conversation_turns t WHERE t.conversation_id = c.conversation_id),
           'meta', jsonb_build_object('uid', c.conversation_uid, 'type', c.conv_type, 'title', c.title,
                                      'book_id', c.book_id, 'pages', to_jsonb(c.pages), 'template', c.template_id,
                                      'hazard_flags', to_jsonb(c.hazard_flags))
       ) AS record
FROM v_conversations c;

CREATE VIEW v_dataset_summary AS
SELECT 'source_pages' AS item, count(*)::bigint AS n FROM source_pages
UNION ALL SELECT 'treatises', count(*) FROM treatises
UNION ALL SELECT 'topics', count(*) FROM topics
UNION ALL SELECT 'topic_sections', count(*) FROM topic_sections
UNION ALL SELECT 'knowledge_chunks', count(*) FROM knowledge_chunks
UNION ALL SELECT 'diseases', count(*) FROM diseases
UNION ALL SELECT 'remedies', count(*) FROM remedies
UNION ALL SELECT 'remedy_ingredients', count(*) FROM remedy_ingredients
UNION ALL SELECT 'diet_guidelines', count(*) FROM diet_guidelines
UNION ALL SELECT 'conversations', count(*) FROM conversations
UNION ALL SELECT 'conversation_turns', count(*) FROM conversation_turns;

-- ------------------------------------------------------------------ seed reference data
INSERT INTO tehreek (code, code_en, primary_system, secondary_system, primary_organs, mizaj_ur, mizaj_en) VALUES
  ('اعصابی عضلاتی', 'nervous-muscular',   'اعصابی', 'عضلاتی', 'دماغ و اعصاب', 'سرد تر',  'cold-moist'),
  ('اعصابی غدی',    'nervous-glandular',  'اعصابی', 'غدی',    'دماغ و اعصاب', 'تر گرم',  'moist-hot'),
  ('عضلاتی اعصابی', 'muscular-nervous',   'عضلاتی', 'اعصابی', 'قلب و عضلات',  'سرد خشک', 'cold-dry'),
  ('عضلاتی غدی',    'muscular-glandular', 'عضلاتی', 'غدی',    'قلب و عضلات',  'خشک گرم', 'dry-hot'),
  ('غدی عضلاتی',    'glandular-muscular', 'غدی',    'عضلاتی', 'جگر و غدد',    'گرم خشک', 'hot-dry'),
  ('غدی اعصابی',    'glandular-nervous',  'غدی',    'اعصابی', 'جگر و غدد',    'گرم تر',  'hot-moist')
ON CONFLICT (code) DO NOTHING;

-- =====================================================================
-- v2: questionnaire consultation, consultation log, hazard flags
-- (additive and idempotent – safe on a v1 database)
-- =====================================================================
INSERT INTO schema_version (version, description)
VALUES (2, 'questionnaire engine, consultation sessions, remedy/conversation hazard flags')
ON CONFLICT (version) DO NOTHING;


-- Question bank. Seeded by the loader from nazria_kb/questionnaire.py; a Hakeem may tune
-- weights/labels here (the loader only inserts missing rows, it never overwrites edits).
CREATE TABLE IF NOT EXISTS questionnaire_questions (
    question_id  text PRIMARY KEY,
    ordinal      int  NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('single', 'multi', 'text')),
    stage        text NOT NULL CHECK (stage IN ('triage', 'profile', 'signs')),
    text_ur      text NOT NULL,
    active       boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS questionnaire_options (
    question_id    text NOT NULL REFERENCES questionnaire_questions(question_id) ON DELETE CASCADE,
    option_key     text NOT NULL,
    ordinal        int  NOT NULL,
    label_ur       text NOT NULL,
    weights        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"عضلاتی": 2}
    source_book_id smallint,                             -- no FK: must survive data reloads (TRUNCATE CASCADE)
    source_pages   int[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (question_id, option_key)
);

-- Consultation log for every engine (questionnaire now, LLM providers later).
-- Contains patient answers: apply your retention / privacy policy. No names are collected.
CREATE TABLE IF NOT EXISTS consultation_sessions (
    session_uid   uuid PRIMARY KEY,
    engine        text NOT NULL,                     -- questionnaire | llm
    provider      text,                              -- openai | deepseek | local | anthropic | gemini
    model         text,
    status        text NOT NULL CHECK (status IN ('in_progress', 'completed', 'emergency', 'abandoned')),
    answers       jsonb NOT NULL DEFAULT '{}'::jsonb,
    result        jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_consultation_sessions_status ON consultation_sessions (status, started_at);

CREATE TABLE IF NOT EXISTS consultation_messages (
    session_uid   uuid NOT NULL REFERENCES consultation_sessions(session_uid) ON DELETE CASCADE,
    message_index int  NOT NULL,
    role          text NOT NULL CHECK (role IN ('patient', 'hakeem')),
    content       text NOT NULL,
    question_id   text,
    -- reserved for LLM engines: usage / latency / retrieved chunk ids per message
    prompt_tokens     int,
    completion_tokens int,
    latency_ms        int,
    source_chunk_ids  int[] NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_uid, message_index)
);

-- Patient-safe remedies: no hazardous ingredient detected (still requires a Hakeem's advice).
CREATE VIEW v_remedies_patient_safe AS
SELECT * FROM remedies WHERE cardinality(hazard_flags) = 0;
