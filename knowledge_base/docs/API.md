# Nazria REST API: guide for the Android app

This is the single backend for the app. It provides:
- patient accounts (phone + password);
- the book-based symptom questionnaire and assessment;
- pulse (نبض) video analysis;
- an optional AI explanation;
- staff access to every patient's history;
- a complete audit log.

**Basics**
- Base URL: `http://<server IP>/api/v1/` for now (plain HTTP; HTTPS later, see `deploy/DEPLOY_UBUNTU.md`).
- Format: JSON, UTF-8, Urdu as-is. Pulse uploads are `multipart/form-data`.
- Contract: [`openapi.yaml`](openapi.yaml), served live at `/api/schema/` with Swagger UI at `/api/docs/` when
  `NAZRIA_API_DOCS=true`. You can generate the Retrofit or Kotlin client from it.
- Lists are paginated: `{"count", "next", "previous", "results": [...]}`, 20 items per page, `?page=2`.
- Every response has an `X-Request-ID` header. It matches the audit log entry, so quote it when reporting a
  problem.

## Headers

| Header | When |
|---|---|
| `X-Api-Key: nzr_…` | **Every** request except `/health/`. It identifies the app: `python manage.py create_api_client android-app`. |
| `Authorization: Bearer <access>` | Every patient or staff endpoint, after logging in. |

Android 9 and newer blocks plain HTTP. While the server has no HTTPS, the app needs a `network_security_config.xml`
that allows cleartext traffic to the server's IP.

## Login flow

```
POST /auth/register/  {"phone","password","full_name"?,"gender"?,"birth_year"?,"consent": true}  → 201 tokens
POST /auth/login/     {"phone","password"}                                                       → 200 tokens
tokens = {"access": "...", "refresh": "...", "user": {"id","phone","full_name","gender","birth_year","role",...}}
```

- **Phone numbers:** any common format is accepted (`0300-1234567`, `+92 300 1234567`, Urdu digits). They are
  stored as `+923001234567`.
- **Access token:** valid 30 minutes. When a call returns `401`, call `POST /auth/refresh/ {"refresh"}` and retry.
- **Refresh token:** valid 30 days. Each refresh returns a **new** refresh token, and the old one stops working.
  Store the new one every time.
- **Logout:** `POST /auth/logout/ {"refresh"}`.
- **Profile:** `GET /me/` reads it. `PATCH /me/ {"full_name","gender","birth_year"}` changes it.
- **Password:** `POST /me/password/ {"old_password","new_password"}`. A forgotten password is reset by staff in the
  admin; there is no SMS yet.
- **Consent:** `consent: true` records that the patient accepted the disclaimer: guidance, not a diagnosis.

## Consultation flow

```
1. GET  /questionnaire/                 (app key only) questions to show; cache by "version"
2. red-flag question → POST /triage/ {"red_flags":[...]}            (app key only) emergency? show "message", STOP
3. complaint        → POST /triage/ {"red_flags":[...],"complaint"}  (the text is screened too)
4. remaining questions (skip a question when its skip_if matches)
5. POST /consultations/ {"answers": {...}}             → the result, saved in the patient's history
6. optional: POST /consultations/{id}/explanation/     → AI explanation (10–30 s)
7. optional: POST /pulse/analyses/ (video, consultation={id}) → pulse analysis linked to the consultation
```

Triage and the questionnaire need no login: an emergency must never wait for one.

## Endpoints

| Method and path | Who | What |
|---|---|---|
| `GET /health/` | anyone | `{"status","database","explanation_enabled","api_version"}`; `503` if the database is down. |
| `GET /questionnaire/` | app | Questions and options (no weights). See *Questionnaire* below. |
| `POST /triage/` | app | `{"emergency","flags","flag_labels","message"}` |
| `POST /auth/register/`, `/auth/login/`, `/auth/refresh/` | app | Tokens. Limited to 10 per minute per IP. |
| `POST /auth/logout/` · `GET`/`PATCH /me/` · `POST /me/password/` | user | Account. |
| `GET /me/activity/` | user | The patient's own audit trail, newest first. |
| `GET /consultations/` | user | History: `[{"id","status","created_at","primary_system","explanation_status","complaint","deleted"}]` |
| `POST /consultations/` | user | All answers in → the full result (`201`). |
| `GET /consultations/{id}/` | owner, staff | The full result again, with linked `pulse_analyses` and any `explanation`. |
| `DELETE /consultations/{id}/` | owner, staff | Hides it from the patient's history. **Everything is kept** on the server, and staff still see it. |
| `POST /consultations/{id}/explanation/` | owner, staff | AI explanation (`status`: `shown`, `not_covered`, `rejected`, `unavailable` or `disabled`). |
| `GET /pulse/analyses/` | user | The patient's pulse analyses. |
| `POST /pulse/analyses/` | user | Multipart: `video` (mp4, mov, 3gp, webm or mkv; ≤ 100 MB), `method` (`finger` or `wrist`), `consultation` (optional id), `symptoms` (optional JSON list). Analysed immediately (`201`). |
| `GET /pulse/analyses/{id}/` · `DELETE …` | owner, staff | One analysis. DELETE hides it; the video is kept. |
| `GET /pulse/symptom-suggestions/` | user | Free-text symptom lists (English). |
| `GET /staff/patients/?search=` | staff | Patients with consultation and pulse counts. |
| `GET /staff/patients/{id}/` | staff | A patient's complete history: profile, every consultation and pulse analysis, hidden ones included. |
| `GET /staff/audit/?user=&action=&object_id=&since=&until=` | staff | The complete audit log. `action` can be a prefix ending in `.`, for example `auth.`. |

**Roles:** `user.role` is `patient`, `hakeem` or `admin`. Staff accounts are created on the server with
`python manage.py create_staff`.

### Questionnaire

```json
{"version": "3c46…", "disclaimer": "…", "questions": [
  {"id": "red_flags", "kind": "multi", "stage": "triage", "text": "…", "options": [{"key": "chest_pain", "label": "…"}, …],
   "skip_if": null, "emergency_unless": ["none"]},
  {"id": "complaint", "kind": "text", "min_length": 2, "max_length": 1000, …},
  {"id": "pregnancy", "kind": "single", "skip_if": {"question_id": "age_group", "equals": "child"}, …}, …]}
```

- **How to answer each kind:** `single` takes one option key, `multi` a list of keys, `text` a string.
- **Required answers:** every question is required except one removed by `skip_if`. After an emergency answer,
  nothing else is needed.

### Consultation result (`POST /consultations/`)

```json
{"id": "6f0c…", "patient": 12, "status": "completed", "created_at": "…", "emergency": null,
 "assessment": {"conclusive": true, "primary_system": "عضلاتی", "primary_organs": "قلب و عضلات", "tehreek": null,
                "mizaj": null, "confidence": 1.0, "totals": {"اعصابی": 0, "عضلاتی": 8, "غدی": 0}, "vulnerable": false,
                "evidence": [{"question_id": "urine_color", "option_key": "red", "answer": "سرخ یا سرخی مائل",
                              "system": "عضلاتی", "citation": {"volume": 2, "pages": [125, 127, 133],
                                                              "text": "جلد دوم، صفحات 125، 127، 133"}}, …]},
 "book": {"topic": {"id": 1603, "title": "عضلاتی قبض", "citation": {"text": "جلد دوم، صفحہ 127", …}},
          "description": "…", "recipe": {"status": "shown", "text": "…", "dosage": null, "hazards": [], "message": null},
          "diet": null, "passages": []},
 "advice": ["…"], "disclaimer": "…", "text": "<the whole result as Urdu text>",
 "explanation": null, "explanation_available": false, "pulse_analyses": [], "deleted": false}
```

| `recipe.status` | Meaning |
|---|---|
| `shown` | `text` (and `dosage`, if the book gives one) can be shown. |
| `withheld_vulnerable` | Child, elderly or pregnant patient: show `message` instead. |
| `withheld_hazard` | The recipe contains سنکھیا, پارہ, کشتہ or similar: show `message`. `hazards` lists what was found. |

An emergency result has `"status": "emergency"` and `"emergency": {"flags", "flag_labels", "message"}`;
`assessment` and `book` are null.

### Pulse analysis (`POST /pulse/analyses/`)

```json
{"id": "…", "patient": 12, "consultation": "6f0c…", "method": "finger", "status": "completed",
 "result": {"average_heart_rate_bpm": 74.9, "resting_heart_rate_bpm": 69.9, "heart_rate_variability_ms": 227.4,
            "pulse_characteristics": {"rhythm": "…", "strength": "…", "volume": "…", "tension": "…"},
            "waveform_analysis": {…}, "signal_quality": "moderate", "total_beats_detected": 25, …},
 "error": "", "symptoms": [], "created_at": "…", "processed_at": "…",
 "disclaimer": "Pulse analysis from a phone camera is experimental … تشخیص نہیں۔"}
```

`status: "failed"` comes with a short `error` the app can show, for example "too few heartbeats were detected;
keep the finger still on the lens". Always show the `disclaimer`. The analysis is experimental.

## History and audit

- **Nothing is deleted automatically.** A patient's "delete" only hides an item from their own history.
- **Every API and admin request is written to the audit log:**
  - who: the user, their role and the app key;
  - what: the action and the object id;
  - when, from which IP, and the result: status code and duration.
- **Never written to the log:** passwords, tokens, request bodies or symptom text.
- **The log can't be changed or deleted:** the database refuses UPDATE, DELETE and TRUNCATE on it.

## Errors

Every error has the same shape: `{"error": "<code>", "detail": "<message>", "fields": {…}?}`.

| HTTP | `error` | Meaning |
|---|---|---|
| 400 | `invalid_answers`, `invalid_request` | Validation failed. `fields` lists each problem. |
| 401 | `not_authenticated`, `token_not_valid`, `invalid_credentials`, `invalid_token` | Log in, or refresh the token. |
| 403 | `app_key_invalid`, `permission_denied` | The app key is missing or wrong, or the endpoint is for staff only. |
| 404 | `not_found` | Unknown id, or not the patient's own. |
| 409 | `not_explainable` | An explanation was requested for an emergency result. |
| 429 | `throttled` | Rate limit reached. Wait the number of seconds in `Retry-After`. |
| 503 | `database_unavailable` | Try again later. |
