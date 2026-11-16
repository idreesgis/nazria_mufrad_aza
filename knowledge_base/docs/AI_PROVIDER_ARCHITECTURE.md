# AI provider architecture — plan

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
| Consultation log with provider, model, token and latency columns | ✅ schema v2 |
| LLM engine and provider adapters | ⏳ planned (Phase 2–3 below) |
| Semantic retrieval (pgvector embeddings) | ⏳ planned (Phase 4) |

## 1. Architecture

```
            Web / mobile app  ──►  Consultation API (planned service layer)
                                          │  Session (JSON, stateless-friendly)
                                          ▼
                              ┌──── ConsultationEngine ────┐
                              │                            │
                   QuestionnaireEngine              LLMEngine (planned)
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
| `llm` ⏳ | Free-text conversation. Each turn retrieves passages, then the model answers only from them. | Yes |
| `hybrid` ⏳ (recommended end state) | The questionnaire collects intake and the tehreek indication deterministically; the LLM then explains and answers follow-up questions in natural Urdu, constrained to retrieved passages. | Yes |

## 3. Provider adapters (planned)

One small interface; each provider is one adapter of about 50 lines:

```python
class LLMProvider(Protocol):
    name: str
    def complete(self, messages: list[dict], *, max_tokens: int, temperature: float) -> Completion: ...
    # Completion(text, model, prompt_tokens, completion_tokens, latency_ms)
```

| `NAZRIA_LLM_PROVIDER` | Adapter | Notes |
|---|---|---|
| `openai` | OpenAI-compatible (Chat Completions) | official `openai` SDK |
| `deepseek` | OpenAI-compatible | same adapter with DeepSeek's `base_url` |
| `local` | OpenAI-compatible | vLLM, Ollama, LM Studio or llama.cpp server on your machine. **Recommended first target**, since you plan to deploy locally. Patient data stays on-premises. |
| `anthropic` | Claude Messages API | official `anthropic` SDK; system prompt passed separately |
| `gemini` | Google Gemini API | official `google-genai` SDK; role mapping `assistant` → `model` |

Three providers (OpenAI, DeepSeek, local) share one adapter, so the planned work is three adapters in total.

## 4. Configuration

| Variable | Example | Meaning |
|---|---|---|
| `NAZRIA_ENGINE` | `questionnaire` (default) \| `llm` | which engine |
| `NAZRIA_LLM_PROVIDER` | `local` | one of the providers above |
| `NAZRIA_LLM_MODEL` | name of your deployed model | required for `llm` |
| `NAZRIA_LLM_BASE_URL` | `http://localhost:8000/v1` | required for `local` and `deepseek` |
| `NAZRIA_LLM_API_KEY_ENV` | `OPENAI_API_KEY` | the **name** of the env var that holds the key |
| `NAZRIA_LLM_TEMPERATURE` / `NAZRIA_LLM_MAX_TOKENS` | `0.2` / `1024` | generation limits |

API keys live only in environment variables or a secret manager: never in the database, in git, or in logs.

## 5. RAG prompt contract (for the LLM engine)

- **System prompt:** the Hakeem persona already defined in `dialogues.SYSTEM_PROMPT`, plus the rules "answer only from the passages below", "cite جلد/صفحہ", "if the passages don't cover it, say so and refer to a Hakeem" and "never prescribe hazardous recipes".
- **Context:** the top-k `knowledge_chunks`, each carrying `context_path` and pages, plus the questionnaire result when using `hybrid`.
- **Post-checks:**
  - Run `hazard_flags()` on the answer and replace any hazardous recipe with the practitioner-only notice.
  - Require at least one citation.
  - Re-run red-flag detection on every patient message.

## 6. Logging, evaluation, privacy

- **Logging:** `consultation_sessions` and `consultation_messages` already store engine, provider, model, tokens, latency and `source_chunk_ids`.
- **Evaluation:** build a golden set from expert-approved conversations (`conversation_reviews`). Score each provider on:
  - groundedness (is the answer supported by the cited chunk?)
  - citation accuracy
  - safety (hazard and red-flag handling)
  - Urdu fluency, latency and cost

  Choose providers on these scores.
- **Privacy:** consultations contain health information. No names are collected. Set a retention period. For data residency, prefer the `local` provider; external APIs send patient text off-premises.

## 7. Roadmap

| Phase | Deliverable |
|---|---|
| 1 ✅ | Questionnaire engine, safety layer, provider config seam, consultation log, CLI (`python -m nazria_kb consult`) |
| 2 | `LLMProvider` interface + OpenAI-compatible adapter (local first, then DeepSeek and OpenAI) + `llm` engine with RAG + tests using a fake provider |
| 3 | Claude and Gemini adapters; `hybrid` engine; provider evaluation harness |
| 4 | pgvector embeddings for semantic retrieval (local embedding model) |
| 5 | HTTP API service (e.g. FastAPI) exposing start/reply, with Session JSON and auth |
| 6 | Optional LLM-generated dialogue augmentation of the training set, gated by expert review |

## 8. Decisions needed before Phase 2

1. Which local serving stack (vLLM, Ollama, LM Studio or llama.cpp) and which model.
2. Whether any external provider may receive patient text (data-protection policy).
3. Who reviews and approves conversations and questionnaire weights (Hakeem reviewer role).
