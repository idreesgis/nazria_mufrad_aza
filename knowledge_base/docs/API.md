# Nazria REST API (for the Android app)

The Android app only collects the patient's answers. The server does everything else: the emergency check,
scoring, choosing the book chapter, the safety filters (hazardous recipes, vulnerable patients) and, optionally,
the AI explanation. It then returns a structured result.

The server reuses `nazria_kb` unchanged. A consultation sent to the API gives exactly the same result and Urdu text
as the same answers typed into `python -m nazria_kb consult`; the tests check this.

- Base URL: `https://<your-host>/api/v1/`
- Format: JSON, UTF-8, Urdu text as-is.
- Machine-readable contract: [`openapi.yaml`](openapi.yaml). It is also served live at `/api/schema/`, with Swagger UI
  at `/api/docs/` when `NAZRIA_API_DOCS=true`. You can generate the Android client from it, for example with
  OpenAPI Generator `kotlin` and Retrofit.

## Authentication

Every endpoint except `/health/` needs an app API key:

```
Authorization: Api-Key nzr_3f9a1c2b7d4e_…
```

`X-Api-Key: nzr_…` is also accepted.

- **Creating a key:** run `python manage.py create_api_client android-app`. The key is printed once and only its
  hash is stored. You can also create a key in the admin under "API clients", where it is shown once after saving.
- **Revoking a key:** untick "active" in the admin.

There are no patient accounts. Each consultation instead gets its own random `access_token`, returned only when
it is created. The app stores it and sends it as `X-Consultation-Token` to read, explain or delete that
consultation. Without the right token the server answers `404`, so it never reveals whether a consultation exists.

## The app flow

```
1. GET  /questionnaire/                    → questions to show (cache by "version")
2. ask the red-flag question
   POST /triage/ {"red_flags": [...]}      → emergency? show "message" and STOP
3. ask the complaint
   POST /triage/ {"red_flags": [...], "complaint": "..."}   (the complaint text is screened too)
4. ask the remaining questions (skip a question when its skip_if matches)
5. POST /consultations/ {"answers": {...}} → result + id + access_token (store both on the phone)
6. optional: POST /consultations/{id}/explanation/  → AI explanation (may take 10–30 s; show a spinner)
7. later:    GET /consultations/{id}/  ·  DELETE /consultations/{id}/
```

## Endpoints

### `GET /health/` (no key)

```json
{"status": "ok", "database": "ok", "explanation_enabled": false, "api_version": 1}
```

Returns `503` with `"database": "unavailable"` when the database cannot be reached.

### `GET /questionnaire/`

```json
{
  "version": "3c46bade16781308",
  "disclaimer": "یہ سوالنامہ کتاب «کلیات تحقیقات صابر ملتانی» کی بنیاد پر صرف رہنمائی کے لیے ہے…",
  "questions": [
    {"id": "red_flags", "kind": "multi", "stage": "triage", "text": "پہلے یہ بتائیں: …",
     "options": [{"key": "chest_pain", "label": "سینے میں شدید درد یا دباؤ"}, …, {"key": "none", "label": "ان میں سے کوئی نہیں"}],
     "skip_if": null, "emergency_unless": ["none"], "min_length": null, "max_length": null},
    {"id": "complaint", "kind": "text", …, "min_length": 2, "max_length": 1000},
    {"id": "pregnancy", "kind": "single", …, "skip_if": {"question_id": "age_group", "equals": "child"}},
    …
  ]
}
```

| Field | Meaning |
|---|---|
| `kind` | `single` (send one key), `multi` (send a list of keys) or `text` (send a string). |
| `skip_if` | Don't ask this question when the named question has that answer. |
| `emergency_unless` | Choosing any other option is an emergency: call `/triage/`. |
| `version` | Changes when a Hakeem edits the questions in the database. Refresh your cached copy when it changes. |

The scoring weights and page numbers stay on the server.

### `POST /triage/`

Request:

```json
{"red_flags": ["none"], "complaint": "میرے سینے میں شدید درد ہے"}
```

Response:

```json
{"emergency": true, "flags": ["chest_pain"], "flag_labels": ["سینے میں شدید درد یا دباؤ"],
 "message": "آپ نے جو علامت بتائی ہے وہ ہنگامی نوعیت کی ہو سکتی ہے۔ برائے مہربانی فوراً قریبی ہسپتال…"}
```

When `emergency` is true, show `message` and end the consultation.

### `POST /consultations/` → `201`

The request maps each question id to its answer:

```json
{"answers": {
  "red_flags": ["none"], "complaint": "مجھے پرانی قبض کی شکایت ہے", "duration": "chronic",
  "age_group": "adult", "pregnancy": "na", "urine_color": "red", "bowel": "constipation", "body": "dry",
  "abdomen": "gas", "taste": "sour", "heart": "yes", "burning_urine": "no", "catarrh": "no", "phlegm": "none"}}
```

Which answers are required:
- Every question is required except one removed by `skip_if`.
- After an emergency answer (red flags, or a complaint describing an emergency) nothing else is needed, and the
  result has `"status": "emergency"`.

The response (shortened):

```json
{
  "id": "6f0c…", "access_token": "Qm9…", "status": "completed", "created_at": "2026-11-27T10:25:25+00:00",
  "emergency": null,
  "assessment": {
    "conclusive": true, "primary_system": "عضلاتی", "primary_organs": "قلب و عضلات",
    "secondary_system": null, "tehreek": null, "mizaj": null, "confidence": 1.0,
    "totals": {"اعصابی": 0, "عضلاتی": 8, "غدی": 0}, "vulnerable": false,
    "evidence": [{"question_id": "urine_color", "option_key": "red", "question": "آپ کے پیشاب…",
                  "answer": "سرخ یا سرخی مائل", "system": "عضلاتی",
                  "citation": {"volume": 2, "volume_name": "جلد دوم", "pages": [125, 127, 133],
                               "text": "جلد دوم، صفحات 125، 127، 133"}}, …]
  },
  "book": {
    "topic": {"id": 1603, "title": "عضلاتی قبض", "citation": {"volume": 2, "pages": [127], "text": "جلد دوم، صفحہ 127", …}},
    "description": "عضلاتی قبض اکثر شدید ہوتی ہے…",
    "recipe": {"status": "shown", "text": "نسخہ: سناکی، تیز پات…", "dosage": null, "hazards": [], "message": null},
    "diet": null, "passages": []
  },
  "advice": ["چونکہ تکلیف پرانی ہے، کسی مستند حکیم سے باقاعدہ معائنہ ضرور کروائیں۔"],
  "disclaimer": "…", "text": "شکریہ۔ آپ کے جوابات کی بنیاد پر: …",
  "explanation": null, "explanation_available": false
}
```

**Recipe safety:** `book.recipe.status` tells you whether the recipe can be shown:

| Status | When | What the API returns |
|---|---|---|
| `shown` | Safe to show. | `text`, and `dosage` when the book gives one. |
| `withheld_vulnerable` | Child, elderly or pregnant patient. | No `text`; show `message`. |
| `withheld_hazard` | The recipe contains سنکھیا, پارہ, کشتہ or similar. | No `text`; show `message`. `hazards` lists what was found. |

**When no chapter matches:** `book.topic` is null and `book.passages` holds up to two safe book excerpts.

**Simple display:** `text` is the whole result as one Urdu text, the same as the CLI.

### `GET /consultations/{id}/` and `DELETE /consultations/{id}/`

Both need the `X-Consultation-Token` header.

- **GET** returns the stored result, including the explanation if one was made. The `access_token` is not repeated.
- **DELETE** removes the consultation and its transcript from the server and returns `204`.

### `POST /consultations/{id}/explanation/`

Needs `X-Consultation-Token`. There is no request body. This call is limited to `NAZRIA_API_EXPLAIN_RATE`
requests per client (default 10 per minute).

```json
{"status": "shown", "text": "کتاب کے مطابق عضلاتی قبض اکثر شدید اور دائمی ہوتی ہے (جلد دوم، صفحہ 127)۔ …",
 "sources": [{"context": "تحقیقات المجربات › عضلاتی قبض", "citation": {"text": "جلد دوم، صفحہ 127", …}}],
 "provider": "gemini", "model": "gemini-3.5-flash", "external_provider": true,
 "notice": "اطلاع: آپ کے سوالات کے جواب کے لیے ایک بیرونی AI سروس (gemini) استعمال ہو رہی ہے…"}
```

| Status | Meaning, and what the app shows |
|---|---|
| `shown` | Show `text`, `sources`, and `notice` when it is set. Later calls return the stored explanation without asking the AI again. |
| `not_covered` | The book passages don't answer this. Show the result without an explanation. |
| `rejected` | The AI answer failed a check: no valid citation, wrong script, or unusable output. It is never shown. |
| `unavailable` | The provider failed: `reason` is `quota`, `rate_limit`, `auth`, `policy` and so on. When `retryable` is true, try again later. |
| `disabled` | The server runs with `NAZRIA_ENGINE=questionnaire`, the default. Hide the explanation button whenever `explanation_available` is false. |

Before the AI is called, names, phone numbers, CNIC numbers and e-mail addresses are removed from the complaint.
Emergency consultations return `409` because they cannot be explained.

## Errors

Every error has the same shape:

```json
{"error": "invalid_answers", "detail": "some answers are missing or invalid",
 "fields": {"heart": "required", "urine_color": "one option key: ['red', 'yellow', 'white', 'unknown']"}}
```

| HTTP | `error` | When |
|---|---|---|
| 400 | `invalid_answers`, `invalid_request` | Missing or unknown answers, a wrong option key, or a malformed body. Each field is listed. |
| 401 | `not_authenticated`, `authentication_failed` | The API key is missing, wrong or revoked. |
| 404 | `not_found` | Unknown consultation, or a missing or wrong `X-Consultation-Token`. |
| 409 | `not_explainable` | An explanation was requested for an emergency result. |
| 429 | `throttled` | Rate limit reached. Wait the number of seconds in the `Retry-After` header. |
| 503 | `database_unavailable` | The database can't be reached. Connection details are never included. |
