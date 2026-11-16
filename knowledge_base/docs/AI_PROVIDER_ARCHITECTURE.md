# AI provider architecture

**Goal:** the Hakeem app can run on any of **OpenAI, DeepSeek, Claude, Gemini, or a locally deployed
model**, or on **no AI at all**, selected by configuration. The app, the database and the safety
rules stay the same whichever engine or provider is chosen.

**Status**

| Part | Status |
|---|---|
| Engine interface (`ConsultationEngine`, `Session`, `Reply`) | ✅ implemented (`nazria_kb/engine.py`) |
| **Questionnaire engine** (rule-based, needs no AI provider) | ✅ implemented, current default |
| Shared safety layer (red flags, hazard filter, vulnerable groups, disclaimer) | ✅ implemented (`nazria_kb/safety.py`) |
| Book retrieval (PostgreSQL full-text) | ✅ implemented (`PostgresRetriever`) |
| Provider configuration and validation (`EngineConfig`, `NAZRIA_*` env vars) | ✅ implemented |
| Consultation log with provider, model, token and latency columns | ✅ schema v2; filled by the LLM engines (v3) |
| `LLMProvider` interface + adapters: openai, deepseek, local (vLLM/Ollama/LM Studio/llama.cpp), anthropic, gemini | ✅ `nazria_kb/providers.py` |
| `llm` and `hybrid` engines (RAG, guards, fallback) | ✅ `nazria_kb/llm_engine.py` |
| External-provider data policy (setting, PII removal, notice, session flag) | ✅ `providers.py`, `privacy.py`, schema v3 |
| AI reviewer (conversations; weights report) | ✅ `nazria_kb/reviewer.py`, schema v3 |
| Provider evaluation harness | ✅ `nazria_kb/evaluate.py` |
| Semantic retrieval (pgvector embeddings) | ⏳ planned (Phase 4) |

## 1. Architecture

```
            Web / mobile app  ──►  Consultation API (planned service layer)
                                          │  Session (JSON, stateless-friendly)
                                          ▼
                              ┌──── ConsultationEngine ────┐
                              │                            │
                   QuestionnaireEngine        LLMEngine / HybridEngine
                   (book-weighted intake,           (RAG: retrieve → prompt → generate)
                    no AI provider)                        │
                              │                     LLMProvider interface
                              │            ┌───────┬───────┼────────┬──────────┐
                              │         OpenAI  DeepSeek  Local    Claude     Gemini
                              │         (OpenAI-compatible adapter)  (adapter)  (adapter)
                              ▼                            ▼
                       Safety layer  ◄──── applied to every input and every output ────►
                              ▼
                 Retriever ──► PostgreSQL `nazria` (chunks, topics, remedies, tehreek,
                                questionnaire, consultation log)
```

**Rules every engine follows:**
1. **Red-flag triage first.** Emergency symptoms end the consultation with a hospital referral, before any engine logic runs.
2. **Grounding.** Clinical content must come from retrieved book passages and carry a volume/page citation.
3. **Hazard filter on output.** A recipe containing arsenic, mercury, copper sulphate, kushta, aconite, nux vomica, opium, lead and similar is never shown to a patient. Recipes are also never shown to children, pregnant or breast-feeding women, or the elderly.
4. **A disclaimer and a referral** to a qualified Hakeem in every final answer.

## 2. Engines

| Engine | Use | Needs an AI provider |
|---|---|---|
| `questionnaire` ✅ | Structured intake: triage, complaint, profile and 9 sign questions. Signs are weighted from vol. 2 pp. 125–134, giving the dominant system or tehreek. The matching book section is then shown, with the safe recipe, dose and diet. | No |
| `llm` ✅ | Deterministic triage, age group and pregnancy questions (the safety rules depend on them), then free-text conversation: each turn retrieves passages and the model answers only from them. | Yes |
| `hybrid` ✅ (recommended once a provider is configured) | The questionnaire collects intake and the tehreek indication deterministically; the LLM then explains the result and answers follow-up questions in natural Urdu, constrained to retrieved passages. | Yes |

**Fallback.** If the provider cannot be built (policy off, key missing, SDK missing) `build_engine` returns the
questionnaire engine and logs why. If a call fails during a consultation (after the retries), `llm` continues the
same session with the questionnaire (answers already given are kept) and `hybrid` keeps the questionnaire result
and answers follow-ups with deterministic book excerpts. Unexpected exceptions are caught the same way: the
engines never raise to the app and never leave the patient without an answer.

## 3. Provider adapters

```python
class LLMProvider(Protocol):
    name: str; model: str; external: bool
    def complete(self, messages, *, max_tokens, temperature) -> Completion  # text, model, prompt/completion tokens, latency_ms
    def stream(self, messages, *, max_tokens, temperature) -> Iterator[str]  # text deltas
```

| `NAZRIA_LLM_PROVIDER` | Adapter | SDK (as tested) | Notes |
|---|---|---|---|
| `local` | `OpenAICompatibleProvider` | `openai` 3.51 | `NAZRIA_LOCAL_STACK`: `vllm` → `http://localhost:8000/v1`, `ollama` → `:11434/v1`, `lmstudio` → `:1234/v1`, `llamacpp` → `:8080/v1`; `NAZRIA_LLM_BASE_URL` overrides. No key needed (optional `NAZRIA_LOCAL_API_KEY`). Patient data stays on-premises. |
| `deepseek` | `OpenAICompatibleProvider` | `openai` | base URL `https://api.deepseek.com` (from DeepSeek's docs) |
| `openai` | `OpenAICompatibleProvider` | `openai` | sends `max_completion_tokens` (OpenAI deprecated `max_tokens`); compatible servers get `max_tokens` |
| `anthropic` | `AnthropicProvider` | `anthropic` 2.8 | system prompt as the `system` parameter; consecutive same-role turns merged. **The current Messages API has no `temperature` parameter**, so none is sent and runs are not guaranteed deterministic. The base URL is always passed explicitly so an unrelated `ANTHROPIC_BASE_URL` in the environment is ignored. |
| `gemini` | `GeminiProvider` | `google-genai` 3.3 | `assistant` → `model` role; system → `system_instruction`; timeout passed in milliseconds |

Shared behaviour: model name only from `NAZRIA_LLM_MODEL`; SDK retries disabled and one policy applied
(`NAZRIA_LLM_MAX_RETRIES`, exponential backoff with jitter, on timeouts, connection errors, 408/409/425/429 and 5xx);
`NAZRIA_LLM_TIMEOUT_S` per request; every failure becomes a `ProviderError(kind=…)` with a message that names the
fix (variable, base URL, model) and never contains the key. The current SDKs use `httpx2` as their HTTP client.

## 4. Configuration

| Variable | Example | Meaning |
|---|---|---|
| `NAZRIA_ENGINE` | `questionnaire` (default) \| `llm` \| `hybrid` | which engine |
| `NAZRIA_LLM_PROVIDER` | `local` | one of the providers above |
| `NAZRIA_LLM_MODEL` | name of your deployed model | required for `llm` / `hybrid` |
| `NAZRIA_LOCAL_STACK` | `vllm` \| `ollama` \| `lmstudio` \| `llamacpp` | local preset (default URL) |
| `NAZRIA_LLM_BASE_URL` | `http://gpu-box:8000/v1` | overrides the preset / provider URL |
| `NAZRIA_LLM_API_KEY_ENV` | `OPENAI_API_KEY` | the **name** of the env var that holds the key (defaults per provider) |
| `NAZRIA_ALLOW_EXTERNAL_PROVIDERS` | `false` (default) | must be `true` for openai, deepseek, anthropic, gemini |
| `NAZRIA_LLM_TEMPERATURE` / `NAZRIA_LLM_MAX_TOKENS` | `0.2` / `1024` | generation limits |
| `NAZRIA_LLM_TIMEOUT_S` / `NAZRIA_LLM_MAX_RETRIES` | `60` / `3` | per-request timeout, retries after the first attempt |
| `NAZRIA_RAG_TOP_K` | `4` | passages retrieved per turn |
| `NAZRIA_TRAINING_REVIEW_MODE` | `human_or_ai` (now) \| `human_only` (later) | default of `export-training` |

See `.env.example`. API keys live only in environment variables or a secret manager: never in the database, in git, or in logs.

## 5. RAG prompt contract (implemented in `RagResponder`)

- **System prompt:** the Hakeem persona already defined in `dialogues.SYSTEM_PROMPT`, plus the rules "answer only from the passages below", "cite جلد/صفحہ", "if the passages don't cover it, say so and refer to a Hakeem" and "never prescribe hazardous recipes".
- **Context:** the top-k `knowledge_chunks`, each carrying `context_path` and pages, plus the questionnaire result when using `hybrid`.
- **Before the model:** `detect_red_flags()` on every patient message (emergency → hospital referral, the model is not called);
  no passages retrieved → "not covered" + referral without a model call. Passages that contain a hazardous recipe are
  marked "do not repeat" in the prompt. Vulnerable patients (child, elderly, pregnant/breast-feeding — from intake or
  mentioned in free text) get an extra "no recipe, no dose" rule.
- **Post-checks:**
  - `[NOT_COVERED]` → fixed "not covered, see a Hakeem" message.
  - `guard_answer()`: paragraphs with a hazardous ingredient are removed and replaced by the practitioner-only notice;
    for vulnerable patients every recipe-like paragraph is removed and the no-recipe notice added.
  - Citations are checked against the retrieved pages; invalid ones are removed. With no valid citation left the answer
    is treated as ungrounded and replaced by deterministic book excerpts (also safety-checked).
  - A `ماخذ:` line (cited passages) and the disclaimer with the referral are appended to every answer.
- **Logged per answer** in `consultation_messages`: provider, model, prompt/completion tokens, latency, `source_chunk_ids`.

## 6. External-provider data policy

Owner's decision: external providers **are allowed, behind a setting**.

1. `NAZRIA_ALLOW_EXTERNAL_PROVIDERS` (default `false`). `openai`, `deepseek`, `anthropic` and `gemini` refuse to run
   unless it is `true`; `local` always runs. With the setting off, a configured external provider makes the app fall
   back to the questionnaire (the reason is logged).
2. Before any patient text is sent off-premises, `privacy.redact_pii()` removes phone numbers, CNIC/civil-ID and other
   long ID numbers, e-mail addresses, names the patient introduces (`میرا نام … ہے`, `نام: …`, "my name is …") and later
   occurrences of those names. Book passages and the system prompt are not patient data and are sent as they are.
   Ages, durations and doses are kept (they matter clinically and do not identify anyone). This is a best-effort filter.
3. The patient is told **once per session**, in the first message, that an external AI service is used and asked not
   to type personal details.
4. The provider and model are stored on the session (`consultation_sessions.provider`, `.model`) together with
   `external_provider = true`.
5. Retention: consultation tables hold health information; set a retention period and delete old sessions
   (`DELETE FROM nazria.consultation_sessions WHERE started_at < now() - interval '…'` cascades to messages).

## 6a. Review and evaluation

- **AI reviewer** (`python -m nazria_kb review`): LLM-as-judge on the generated conversations, hazard-flagged first,
  resumable, temperature 0 (not available on Claude). Stored in `conversation_reviews` with `reviewer_type = 'ai'` and
  `reviewer = 'ai:<provider>/<model>'`. A human review always overrides it and is never overwritten (selection,
  upsert condition and a table trigger). The questionnaire weights get a report only. Hand-over: `docs/REVIEW_GUIDE.md`.
- **Training export**: `training_messages('human_only')` (future default) or `training_messages('human_or_ai')` (now);
  hazard-flagged conversations excluded unless asked; reviewer edits applied.
- **Evaluation** (`python -m nazria_kb evaluate --provider local,openai:<model>`): fixed question set (clinical,
  hazardous requests, red flags, vulnerable patient, out-of-scope). Measures safety handling, groundedness (lexical
  proxy, plus an LLM-judge score with `--judge-provider`), citation accuracy, Urdu fluency, latency, tokens and cost
  (from `NAZRIA_PRICE_<PROVIDER>_IN/OUT_PER_MTOK`). Writes `output/EVALUATION_REPORT.md` and `.json`.

## 7. Roadmap

| Phase | Deliverable |
|---|---|
| 1 ✅ | Questionnaire engine, safety layer, provider config seam, consultation log, CLI (`python -m nazria_kb consult`) |
| 2 ✅ | `LLMProvider` interface + OpenAI-compatible adapter (local, DeepSeek, OpenAI) + `llm` engine with RAG + tests using a fake provider and a mock server |
| 3 ✅ | Claude and Gemini adapters; `hybrid` engine; data policy; AI reviewer; provider evaluation harness |
| 4 | pgvector embeddings for semantic retrieval (local embedding model) |
| 5 | HTTP API service (e.g. FastAPI) exposing start/reply, with Session JSON and auth |
| 6 | Optional LLM-generated dialogue augmentation of the training set, gated by expert review |

## 8. Decisions

1. Local serving stack — **all four have presets**; the model is configuration (`NAZRIA_LLM_MODEL`). Still open: which model you deploy.
2. External providers — **allowed behind `NAZRIA_ALLOW_EXTERNAL_PROVIDERS`** (section 6).
3. Reviewer — **AI reviewer now, a specialist Hakeem later** (section 6a, `docs/REVIEW_GUIDE.md`).
4. Default engine — stays `questionnaire` until the owner switches to `hybrid`.


## 9. Implementation plan — Phases 2–3 (done)

Decisions from the owner: external providers are **allowed behind a setting** (`NAZRIA_ALLOW_EXTERNAL_PROVIDERS`,
default off); an **AI reviewer** reviews for now and a human Hakeem takes over later; all four local stacks get presets.

| Step | Module | Content |
|---|---|---|
| P1 | `nazria_kb/providers.py` | `LLMProvider` protocol, `Completion`, `ProviderError`; `OpenAICompatibleProvider` (openai, deepseek, local presets vLLM/Ollama/LM Studio/llama.cpp), `AnthropicProvider`, `GeminiProvider`; retries with exponential backoff + jitter, timeouts, SDK retries disabled (one retry policy); streaming; `FakeProvider` for tests; external-provider gate |
| P2 | `nazria_kb/privacy.py` | removes phone, CNIC/civil-ID and long ID numbers, e-mails and self-introduced names before text leaves the premises |
| P3 | `nazria_kb/llm_engine.py` | `LLMEngine` (triage + age/pregnancy intake, then free-text RAG) and `HybridEngine` (questionnaire intake → LLM explanation and follow-ups); shared `RagResponder`: retrieve → prompt → generate → guard (hazards, vulnerable groups, citation validation against retrieved pages, `[NOT_COVERED]` → referral) → disclaimer; any failure falls back to the questionnaire / deterministic passages |
| P4 | `sql/schema.sql` v3 | additive: `conversation_reviews.reviewer_type`, `ai_details`, human-override trigger; `consultation_sessions.external_provider`; `training_messages(mode)` function; edited turns applied in the training export |
| P5 | `nazria_kb/reviewer.py` | `review` CLI: LLM-as-judge over conversations (hazard-flagged first, resumable, `--limit`, temperature 0) + questionnaire-weights report (never writes weights) |
| P6 | `nazria_kb/evaluate.py` | `evaluate` CLI: fixed question set, deterministic metrics (+ optional judge), markdown report |
| P7 | tests, docs | fake provider + mock OpenAI-compatible HTTP server + httpx mock transports for the Claude/Gemini SDKs; no real API calls; `.env.example`, `docs/REVIEW_GUIDE.md` |
