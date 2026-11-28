# Nazria REST API: guide for the Android app

This is the single backend for the app. It provides:
- accounts (phone + password, or Google, Facebook, Apple, Microsoft sign-in), each with **many patients** (self, children, parents…);
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

## Languages: Urdu, English, Arabic

Every patient-facing text is available in **Urdu (`ur`, the default), English (`en`) and Arabic (`ar`)**: questions
and options, the intake form, triage and emergency messages, the result and its text, advice, diet plans, pulse
messages and the AI explanation.

- **Choosing the language:** the server uses, in this order:
  1. `?lang=en|ur|ar` on any request;
  2. the `Accept-Language` header (for example `ar-SA,ar;q=0.9`);
  3. the user's saved `language` (`PATCH /me/ {"language": "en"}`, or `language` at registration or social sign-up);
  4. Urdu.
- **Every response says which language it used:** `language` and `direction` (`rtl` for Urdu and Arabic, `ltr` for
  English), plus a `Content-Language` header. Lay the screen out by `direction`.
- **Answers are language-neutral:** option keys don't change with the language. Logic should use the codes:
  `primary_system_code` (`nervous`, `muscular`, `glandular`), `tehreek_code` (e.g. `muscular_glandular`),
  `system_code` on each evidence row, and `totals` keyed by these codes. The names next to them are for display.
- **Switching language keeps the history readable:** a result is saved in all three languages, so
  `GET /consultations/{id}/?lang=ar` returns the same result in Arabic. Results saved before this version exist in
  Urdu only.
- **The free-text complaint** may be typed in any of the three languages:
  - It is always screened for emergencies in Urdu, English and Arabic.
  - Common complaints in English or Arabic (constipation, cough, fever, …) are matched to the book's topics.
- **Book text stays in the original Urdu:** `book.description`, `book.recipe`, `book.diet` and `book.passages`
  (`book.language` is `"ur"`), because a machine-translated recipe could harm. In `text` their headings say
  "original text in Urdu".
- **The AI explanation** (`POST /consultations/{id}/explanation/?lang=en`) is written in the requested language,
  and each language's explanation is stored separately. The same safety checks apply in every language:
  hazardous ingredients, no recipes for vulnerable patients, and grounded citations (removed before display).
- **Error bodies:** `detail` stays in English for developers. Show your own text for each `error` code.

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

## Social sign-in: Google, Facebook, Apple, Microsoft

Social sign-in is handled by **django-allauth**: allauth checks each provider's token and stores the link between
the provider account and the Nazria account. Every provider is off until the server has its IDs.
`GET /health/` lists the providers that are on, in the order to show them (`social_providers`), and the public IDs
the app needs to start each one (`social_config`). Never a secret.

```
App: the provider's SDK → a token
POST /auth/social/<provider>/ {token fields}          → 200 tokens, "created": false   (known account: logged in)
                                                      → 400 consent_required + signup_token   (new: show the disclaimer …)
POST /auth/social/<provider>/ {"signup_token","consent": true,
                               "full_name"?,"gender"?,"birth_year"?,"language"?} → 201 tokens, "created": true
```

| provider | how the app signs in | token fields to send |
|---|---|---|
| `google` | Credential Manager (`GetSignInWithGoogleOption`, serverClientId = `social_config.google.client_id`) | `id_token` |
| `facebook` | Facebook Login SDK (`public_profile`, `email`) | `access_token` |
| `apple` | No Android SDK: the browser, through the server (below) | `id_token` and the raw `nonce` |
| `microsoft` | AppAuth: authorization code + PKCE, public client, redirect `org.nazria.app.oauth://microsoft` | `id_token` |

- **The answer is the same `tokens` object as phone login,** plus `created` and `provider`. Refresh and logout work
  the same way.
- **A new account needs consent.** The first answer is `400 consent_required` with a `signup_token`, a signed copy
  of the checked identity, valid for 10 minutes and only for that provider. Send it back with `consent: true`, not
  the provider token again: Google and Apple ID tokens can be used only once.
- **How each token is checked:**
  - Google: Google's keys, issuer, expiry, and `aud` = one of `NAZRIA_GOOGLE_CLIENT_IDS`. Only Google accounts with a
    verified e-mail are accepted.
  - Facebook: Graph API `debug_token` with the app secret (the token must be for our app), then `/me`.
  - Apple: Apple's keys, `aud` = one of `NAZRIA_APPLE_CLIENT_IDS`, and the SHA-256 of the raw `nonce` must equal the
    token's `nonce` claim.
  - Microsoft: Microsoft's keys, `aud` = `NAZRIA_MICROSOFT_CLIENT_ID`, issuer
    `https://login.microsoftonline.com/{tid}/v2.0`, and the tenant allowed by `NAZRIA_MICROSOFT_TENANT`.
  - Tokens are never stored or logged.
- **A social-only account** has `user.phone = null`, `user.has_password = false` and
  `user.linked_providers = ["…"]`.
  - It can add a phone number once: `PATCH /me/ {"phone"}`. After that the phone number cannot be changed by the
    patient (staff can).
  - It can set a first password without an old one: `POST /me/password/ {"new_password"}`. Then phone + password
    login also works.
  - `user.email` is the provider's e-mail. A linked account adds its e-mail only when the provider has verified it.
- **Linking:** logged in, `POST /me/social/<provider>/ {token fields}` → the profile. From then on, every linked
  method opens the same account and history. `DELETE /me/social/<provider>/` unlinks it, but only when another way
  to log in remains: phone + password, or another linked provider (`409 last_login_method` otherwise).
- **Accounts are matched by the provider's user id, never by e-mail.** The same person signing in with Google and
  then Microsoft gets two accounts unless they link the second one while logged in. A provider account that is
  already linked to another Nazria account gives `409 social_already_linked`.
- **Staff (Hakeem, admin) cannot use social sign-in;** they log in with phone + password (`403 staff_password_only`).
- **Older routes:** `POST /auth/google/` and `POST`/`DELETE /me/google/` work as before, the same as
  `provider = google`, with their old error codes (`invalid_google_token`, `google_unavailable`,
  `google_login_disabled`, `google_email_unverified`, `google_already_linked`).

### Sign in with Apple on Android

Apple has no Android SDK, so the app uses a browser tab and the server passes the result back:

1. The app makes a random `nonce` and `state` and keeps them. It opens
   `social_config.apple.start_url?nonce=<sha256(nonce), hex>&state=<state>` in a Custom Tab.
2. The server sends the browser to Apple. Apple posts the result to `/api/v1/auth/apple/callback/`.
3. The server opens `org.nazria.app://auth/apple?state=…&id_token=…&name=…`. `name` is sent on the first sign-in
   only, so use it as `full_name`. If the patient cancels, the server opens it with `error=…` instead of
   `id_token`.
4. The app checks `state`, then posts `{"id_token", "nonce": <raw nonce>}` to `/auth/social/apple/`.

Another app that catches the redirect cannot use the ID token, because it does not know the raw nonce. Apple needs
an HTTPS address, so `start_url` is `null` until `NAZRIA_PUBLIC_URL` is an `https://` address.

### Provider setup (once per provider)

| Provider | Where | What to create | Server settings | App build settings |
|---|---|---|---|---|
| Google | Google Cloud console → APIs & Services → Credentials (configure the OAuth consent screen first) | An OAuth client of type **Web application**. An OAuth client of type **Android**, with package `org.nazria.app` and the SHA-1 of each signing key (`./gradlew signingReport`: debug, release, Play App Signing). | `NAZRIA_GOOGLE_CLIENT_IDS` = the Web client ID | none (the ID comes from `/health/`) |
| Facebook | developers.facebook.com → My Apps → Create app (Consumer) → Facebook Login | Add an Android platform with package `org.nazria.app`, class `org.nazria.app.MainActivity` and the key hashes. Meta must review the app before people outside your test users can sign in. | `NAZRIA_FACEBOOK_APP_ID`. **`NAZRIA_FACEBOOK_APP_SECRET`: a secret, only in `/etc/nazria/nazria.env`.** | `nazria.facebookAppId`, `nazria.facebookClientToken` |
| Apple | developer.apple.com → Certificates, IDs & Profiles (paid Apple Developer account) | An App ID with Sign in with Apple. A **Services ID**, with the website domain and the return URL `https://<your domain>/api/v1/auth/apple/callback/`. | `NAZRIA_APPLE_CLIENT_IDS` = the Services ID (then iOS bundle IDs, comma-separated). `NAZRIA_PUBLIC_URL=https://<your domain>`. | none |
| Microsoft | Microsoft Entra admin center → App registrations → New registration | Supported accounts: personal and work/school, or as you need. Platform **Mobile and desktop applications**, redirect URI `org.nazria.app.oauth://microsoft`. No secret. | `NAZRIA_MICROSOFT_CLIENT_ID` = the Application (client) ID. `NAZRIA_MICROSOFT_TENANT` = `common` (default), `consumers`, `organizations` or a tenant ID. | none |

The server must reach these hosts over HTTPS: `www.googleapis.com` (Google), `graph.facebook.com` (Facebook),
`appleid.apple.com` (Apple) and `login.microsoftonline.com` (Microsoft).

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
| `GET /health/` | anyone | `{"status","database","explanation_enabled","google_login_enabled","social_providers","social_config","api_version"}`; `503` if the database is down. |
| `GET /questionnaire/` | app | Questions and options (no weights). See *Questionnaire* below. |
| `POST /triage/` | app | `{"emergency","flags","flag_labels","message"}` |
| `POST /auth/register/`, `/auth/login/`, `/auth/refresh/`, `/auth/social/<provider>/`, `/auth/google/` | app | Tokens. Limited to 10 per minute per IP. |
| `POST /auth/logout/` · `GET`/`PATCH /me/` · `POST /me/password/` | user | Account. |
| `POST`/`DELETE /me/social/<provider>/` (and `/me/google/`) | patient | Link or unlink a Google, Facebook, Apple or Microsoft account. |
| `GET /auth/apple/start/`, `POST /auth/apple/callback/` | browser | Sign in with Apple through the browser (above). No app key. |
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
- **Sign questions:** there are 17 of them, from both volumes of the book. Every one has a neutral last option
  ("معمول کے مطابق" / "ان میں سے کوئی نہیں"); for a `multi` question send `["none"]`.
  - Each label already names the book's term, e.g. «(نقرس)».
  - Render the questions from `GET /questionnaire/`; don't hard-code them. Staff can add, edit or switch off
    questions in the database, and `version` changes when they do.
- **Required answers:** every question is required except one removed by `skip_if`. After an emergency answer,
  nothing else is needed.

### Consultation result (`POST /consultations/`)

```json
{"id": "6f0c…", "language": "en", "direction": "ltr", "account": 12, "rediagnosis_of": null, "status": "completed", "created_at": "…", "emergency": null,
 "patient": {"id": "a41e…", "full_name": "…", "relation": "child", "gender": "female", "birth_year": 2019, "age": 7,
             "age_group": "child", "weight_kg": 18.5, "height_cm": null, "bmi": null, "chronic_conditions": [],
             "conditions_other": "", "allergies": "", "medications": ""},
 "prefilled_answers": {"age_group": "child", "pregnancy": "na"},
 "assessment": {"conclusive": true, "primary_system": "Muscular", "primary_system_code": "muscular",
                "primary_organs": "heart and muscles", "tehreek": null, "tehreek_code": null,
                "mizaj": null, "confidence": 1.0, "totals": {"nervous": 0, "muscular": 8, "glandular": 0}, "vulnerable": false,
                "evidence": [{"question_id": "urine_color", "option_key": "red", "question": "…",
                              "answer": "Red or reddish", "system": "Muscular", "system_code": "muscular"}, …]},
 "book": {"language": "ur", "topic": {"id": 1603, "title": "عضلاتی قبض"},
          "description": "…", "recipe": {"status": "shown", "text": "…", "dosage": null, "hazards": [], "message": null},
          "diet": null, "passages": []},
 "diet_plans": [{"tehreek": "Muscular-Nervous", "tehreek_code": "muscular_nervous", "mizaj": "cold and dry",
                 "choose_if": "If you feel dryness with cold",
                 "breakfast": ["…"], "lunch": ["…"], "dinner": ["…"], "fruits": ["…"], "dry_fruits": ["…"],
                 "qehwa": {"name": "cinnamon and clove qehwa", "ingredients": ["…"], "how": "…"},
                 "rules": ["…"], "notes": []}, {"tehreek": "Muscular-Glandular", …}],
 "advice": ["…"], "disclaimer": "…", "text": "<the whole result as Urdu text>",
 "explanation": null, "explanation_available": false, "pulse_analyses": [], "deleted": false}
```

**What the patient sees.**
- The result shows the **system findings only**: the dominant system (`primary_system`), the tehreek and mizaj, and
  each symptom with the system it points to (`evidence`).
- No book name, author, volume or page reference, and no "حکیم", appears anywhere in the result, the text, the
  diet plan or the AI explanation. Referrals say «مستند معالج».
- The page references stay in the server's question bank, for the review tools only.

**Diet plan (`diet_plans`).** It is built from the diagnosed tehreek, using the corrective food group for that
tehreek:
- `breakfast`, `lunch` and `dinner` (foods of that one group, not mixed with others), `fruits`, `dry_fruits` and a
  `qehwa` with ingredients and how to make it, plus general eating `rules`.
- `notes` come from the patient's info, for example less sweet food with diabetes, less salt with high blood
  pressure, or allergies and medicines.
- **One plan** when the tehreek is known.
- **Two plans** when only the dominant system is clear. Each has `choose_if`, for example "اگر جسم میں خشکی کے
  ساتھ سردی محسوس ہو", so the patient picks the one that fits; show both with their `choose_if`.
- **No plan** (`[]`) for an emergency or an inconclusive result.
- An empty `fruits` or `dry_fruits` means they are not advised in that state; the text says so.

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

Each analysis also has `summary` (heart rate, rhythm, strength, volume, tension, rate pattern in the response
language), and `error_en` (the error in English, for logs). `status: "failed"` comes with a short `error` in the
response language that the app can show, for example "too few heartbeats were detected;
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
| 400 | `consent_required`, `email_unverified` | Social sign-in: show the disclaimer and send `signup_token` with `consent: true`; or use another Google account. |
| 401 | `not_authenticated`, `token_not_valid`, `invalid_credentials`, `invalid_token`, `invalid_social_token` | Log in, or refresh the token; for social sign-in, sign in with the provider again. |
| 403 | `app_key_invalid`, `permission_denied`, `staff_password_only`, `account_disabled` | The app key is missing or wrong, the endpoint is for staff only, or the account cannot sign in this way. |
| 404 | `not_found` | Unknown id, or not the patient's own. |
| 409 | `not_explainable`, `social_already_linked`, `last_login_method`, `retry` | An explanation was requested for an emergency result; or a social link conflict. |
| 429 | `throttled` | Rate limit reached. Wait the number of seconds in `Retry-After`. |
| 503 | `database_unavailable`, `provider_unavailable`, `provider_disabled` | Try again later; or that sign-in is not set up on the server. |
