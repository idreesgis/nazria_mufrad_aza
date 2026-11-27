# Nazria REST API: guide for the Android app

This is the single backend for the app. It provides:
- accounts (phone + password, or Sign in with Google), each with **many patients** (self, children, parents…);
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

## Sign in with Google

Show the Google button only when `GET /health/` says `"google_login_enabled": true`.

```
App: Credential Manager (GetGoogleIdOption / GetSignInWithGoogleOption, serverClientId = the server's WEB client ID)
     → Google ID token (a JWT string)
POST /auth/google/ {"id_token"}                       → 200 tokens, "created": false   (known account: logged in)
                                                      → 400 consent_required          (new: show the disclaimer …)
POST /auth/google/ {"id_token","consent": true,
                    "full_name"?,"gender"?,"birth_year"?} → 201 tokens, "created": true  (… new patient account)
```

- **The response is the same `tokens` object as phone login,** plus `created`. Refresh and logout work the same way.
- **The ID token** is checked on the server with Google's public keys: signature, expiry, issuer and that it was
  issued for this app (`aud` = the Web client ID). It is never stored or logged. Get a fresh ID token for every
  sign-in: they expire after an hour.
- **A Google-only account** has `user.phone = null`, `user.has_password = false`, `user.email` set and
  `user.linked_providers = ["google"]`. Make `phone` nullable in the Kotlin model.
  - It can add a phone number once: `PATCH /me/ {"phone"}`. After that the phone number cannot be changed by the
    patient (staff can).
  - It can set a first password without an old one: `POST /me/password/ {"new_password"}`. Then phone + password
    login also works.
- **An existing phone account can link Google:** logged in, `POST /me/google/ {"id_token"}` → the profile. From then
  on, either login method opens the same account and history. `DELETE /me/google/` unlinks it, but only when the
  account also has a phone and a password (`409 last_login_method` otherwise).
- **Accounts are matched by Google's user id, never by e-mail.** A Google account that is already linked to another
  Nazria account gives `409 google_already_linked`. Google accounts without a verified e-mail are refused.
- **Staff (Hakeem, admin) cannot use Google;** they log in with phone + password (`403 staff_password_only`).

**Google Cloud setup** (once, in the Google Cloud console, *APIs & Services → Credentials*; the OAuth consent screen
must be configured first):
1. **OAuth client ID, type "Web application".** Its client ID goes into the server's `NAZRIA_GOOGLE_CLIENT_IDS` and
   into the app as `serverClientId`. No client secret is needed anywhere.
2. **OAuth client ID, type "Android",** with the app's package name and the SHA-1 of its signing certificate
   (`./gradlew signingReport`; add the debug, release and Play App Signing SHA-1s). This one is not used in code:
   it lets Google issue tokens to the app.

## Patients: one account, many patients

The logged-in user (the **account**) diagnoses one or more **patients**: themselves, their children, parents and so
on. Every diagnosis and pulse analysis belongs to one patient.

```
GET  /patients/                          the account's patients (?search=name)
GET  /patients/intake-form/              (app key only) the general-info form to ask for a NEW patient
POST /patients/        {general info, "consent": true}      → 201 the patient
GET  /patients/{id}/   · PATCH /patients/{id}/ {fields}     · DELETE /patients/{id}/ (hides it; everything is kept)
GET  /patients/{id}/history/             every change to the general info: who, when, which fields, the info after
```

- **General info** (`intake-form` gives the Urdu labels, kinds, options and limits, in order):
  - required: `full_name`, `relation` (`self`, `spouse`, `child`, `parent`, `sibling`, `relative`, `other`),
    `gender`, `birth_year`, and `consent: true`;
  - optional: `weight_kg`, `height_cm`, `chronic_conditions` (`diabetes`, `hypertension`, `heart`, `kidney`,
    `liver`, `asthma`, `thyroid`, `epilepsy`, `other`, or `none`), `conditions_other`, `allergies`, `medications`,
    `notes`.
- **Consent:** the account holder confirms they may record this patient's data (as guardian, for a child).
- **The answer** also has `age`, `age_group`, `bmi`, `consultations`, `pulse_analyses`, `last_consultation_at` and
  `prefilled_questions`.
- **Info used by the diagnosis:**
  - `age_group` comes from `birth_year`.
  - `pregnancy` is `"na"` for male patients and children.
  - These questions are in `prefilled_questions`: don't ask them. If the app sends them anyway, the patient's info
    wins.
  - Kidney, liver or heart disease: no book recipe is shown (`recipe.status = "withheld_condition"`).
  - Medicines or allergies add a caution to `advice`.
- **History is never overwritten:**
  - Each diagnosis stores the patient's info as it was at that time (`patient` in the result).
  - Each change to the info is kept in `/history/`.

## Consultation flow

```
0. choose the patient: an existing one (GET /patients/), or a NEW one → ask the intake form first
1. GET  /questionnaire/                 (app key only) questions to show; cache by "version"
2. red-flag question → POST /triage/ {"red_flags":[...]}            (app key only) emergency? show "message", STOP
3. complaint        → POST /triage/ {"red_flags":[...],"complaint"}  (the text is screened too)
4. remaining questions (skip a question when its skip_if matches, and the patient's prefilled_questions)
5. POST /consultations/ {"answers": {...}, "patient_id": "…"}        existing patient
   POST /consultations/ {"answers": {...}, "new_patient": {intake}}  new patient, created with this diagnosis
                                                       → the result, saved in the patient's history
6. optional: POST /consultations/{id}/explanation/     → AI explanation (10–30 s)
7. optional: POST /pulse/analyses/ (video, patient={id} or consultation={id}) → pulse analysis of that patient
```

- **No login for triage and the questionnaire:** an emergency must never wait for one. An emergency result is also
  stored without a patient.
- **A completed diagnosis needs a patient:** without one the answer is `400 patient_required`.

**Re-diagnosis.** Two ways:
- **A new diagnosis of an existing patient:** `POST /consultations/ {"answers", "patient_id"}`.
- **Repeat an earlier diagnosis:** `POST /consultations/{id}/rediagnose/ {"answers": {only the changed answers}}`
  → `201`. It works like this:
  - The earlier answers are reused, and the patient's **current** info and the current book are applied.
  - A new diagnosis is stored with `rediagnosis_of = {id}`; the earlier one stays unchanged.
  - Send `{}` to run it again unchanged, for example after a Hakeem edited the questions, or the patient's info
    changed.
  - If the earlier diagnosis was an emergency without a patient, add `"patient_id"`.

## Endpoints

| Method and path | Who | What |
|---|---|---|
| `GET /health/` | anyone | `{"status","database","explanation_enabled","google_login_enabled","api_version"}`; `503` if the database is down. |
| `GET /questionnaire/` | app | Questions and options (no weights). See *Questionnaire* below. |
| `POST /triage/` | app | `{"emergency","flags","flag_labels","message"}` |
| `POST /auth/register/`, `/auth/login/`, `/auth/refresh/`, `/auth/google/` | app | Tokens. Limited to 10 per minute per IP. |
| `POST /auth/logout/` · `GET`/`PATCH /me/` · `POST /me/password/` | user | Account. |
| `POST`/`DELETE /me/google/` | patient | Link or unlink a Google account. |
| `GET /me/activity/` | user | The patient's own audit trail, newest first. |
| `GET`/`POST /patients/` · `GET`/`PATCH`/`DELETE /patients/{id}/` · `GET /patients/{id}/history/` | user | The account's patients and their general info (see *Patients*). |
| `GET /patients/intake-form/` | app | The general-info form for a new patient. |
| `GET /consultations/?patient=` | user | History: `[{"id","status","created_at","patient":{"id","full_name","relation"},"rediagnosis_of","primary_system","explanation_status","complaint","deleted"}]` |
| `POST /consultations/` | user | All answers and `patient_id` or `new_patient` → the full result (`201`). |
| `POST /consultations/{id}/rediagnose/` | owner, staff | Re-diagnose with the changed answers → a new result (`201`). |
| `GET /consultations/{id}/` | owner, staff | The full result again, with linked `pulse_analyses` and any `explanation`. |
| `DELETE /consultations/{id}/` | owner, staff | Hides it from the patient's history. **Everything is kept** on the server, and staff still see it. |
| `POST /consultations/{id}/explanation/` | owner, staff | AI explanation (`status`: `shown`, `not_covered`, `rejected`, `unavailable` or `disabled`). |
| `GET /pulse/analyses/?patient=` | user | The account's pulse analyses. |
| `POST /pulse/analyses/` | user | Multipart: `video` (mp4, mov, 3gp, webm or mkv; ≤ 100 MB), `method` (`finger` or `wrist`), `patient` (id; or `consultation`, whose patient is used), `symptoms` (optional JSON list). Analysed immediately (`201`). |
| `GET /pulse/analyses/{id}/` · `DELETE …` | owner, staff | One analysis. DELETE hides it; the video is kept. |
| `GET /pulse/symptom-suggestions/` | user | Free-text symptom lists (English). |
| `GET /staff/accounts/?search=` | staff | Accounts with patient, consultation and pulse counts (search by phone, name or e-mail). |
| `GET /staff/accounts/{id}/` | staff | An account's complete history: profile, its patients, every consultation and pulse analysis, hidden ones included. |
| `GET /staff/patients/?search=` | staff | All patients (search by patient name or the account's phone, name or e-mail). |
| `GET /staff/patients/{id}/` | staff | A patient's complete history: info, every change to it, every diagnosis and pulse analysis, hidden ones included. |
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
{"id": "6f0c…", "account": 12, "rediagnosis_of": null, "status": "completed", "created_at": "…", "emergency": null,
 "patient": {"id": "a41e…", "full_name": "…", "relation": "child", "gender": "female", "birth_year": 2019, "age": 7,
             "age_group": "child", "weight_kg": 18.5, "height_cm": null, "bmi": null, "chronic_conditions": [],
             "conditions_other": "", "allergies": "", "medications": ""},
 "prefilled_answers": {"age_group": "child", "pregnancy": "na"},
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
| `withheld_condition` | The patient has kidney, liver or heart disease (general info): show `message`. |
| `withheld_hazard` | The recipe contains سنکھیا, پارہ, کشتہ or similar: show `message`. `hazards` lists what was found. |

An emergency result has `"status": "emergency"` and `"emergency": {"flags", "flag_labels", "message"}`;
`assessment` and `book` are null.

### Pulse analysis (`POST /pulse/analyses/`)

```json
{"id": "…", "account": 12, "patient": "a41e…", "consultation": "6f0c…", "method": "finger", "status": "completed",
 "result": {"average_heart_rate_bpm": 74.9, "resting_heart_rate_bpm": 69.9, "heart_rate_variability_ms": 227.4,
            "pulse_characteristics": {"rhythm": "…", "strength": "…", "volume": "…", "tension": "…"},
            "waveform_analysis": {…}, "signal_quality": "moderate", "total_beats_detected": 25, …},
 "error": "", "symptoms": [], "created_at": "…", "processed_at": "…",
 "disclaimer": "Pulse analysis from a phone camera is experimental … تشخیص نہیں۔"}
```

`status: "failed"` comes with a short `error` the app can show, for example "too few heartbeats were detected;
keep the finger still on the lens". Always show the `disclaimer`. The analysis is experimental.

## History and audit

- **Nothing is deleted automatically.** "Delete" only hides an item (a patient, a diagnosis, a pulse analysis) from
  the account; staff still see it.
- **Patient info history:** every change to a patient's general info is kept (`/patients/{id}/history/`), and each
  diagnosis keeps the info it was made with.
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
| 400 | `patient_required`, `invalid_patient` | Choose a patient or add one; `invalid_patient`: `fields` names the `new_patient.*` problems. |
| 400 | `consent_required`, `google_email_unverified` | Google sign-in: show the disclaimer and resend with `consent: true`; or use another Google account. |
| 401 | `not_authenticated`, `token_not_valid`, `invalid_credentials`, `invalid_token`, `invalid_google_token` | Log in, or refresh the token; for Google, get a new ID token. |
| 403 | `app_key_invalid`, `permission_denied`, `staff_password_only`, `account_disabled` | The app key is missing or wrong, the endpoint is for staff only, or the account cannot sign in this way. |
| 404 | `not_found` | Unknown id, or not the patient's own. |
| 409 | `not_explainable`, `google_already_linked`, `last_login_method`, `retry` | An explanation was requested for an emergency result; or a Google link conflict. |
| 429 | `throttled` | Rate limit reached. Wait the number of seconds in `Retry-After`. |
| 503 | `database_unavailable`, `google_unavailable`, `google_login_disabled` | Try again later; or Google sign-in is not set up on the server. |
