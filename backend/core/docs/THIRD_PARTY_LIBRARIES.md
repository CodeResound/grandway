# Third-Party Libraries — Core

## Django

| Field | Value |
|-------|-------|
| **Name** | Django |
| **Purpose** | Web framework |
| **Package** | `Django==5.1.9` |
| **Docs** | https://docs.djangoproject.com/en/5.1/ |
| **Files used** | All |
| **Alternatives considered** | FastAPI (rejected: less mature ORM + admin ecosystem for this use case) |
| **Redundancy check** | None — foundational dependency |
| **Security concerns** | Keep up-to-date; subscribe to Django security advisories |
| **Maintenance status** | Active, LTS-adjacent (5.1 receives security patches until April 2026) |
| **Final decision** | Approved — explicitly in architecture spec |

---

## Django REST Framework

| Field | Value |
|-------|-------|
| **Name** | Django REST Framework |
| **Purpose** | API layer — serializers, views, authentication, throttling |
| **Package** | `djangorestframework==3.15.2` |
| **Docs** | https://www.django-rest-framework.org/ |
| **Files used** | `core/exceptions.py`, `core/pagination.py`, `core/responses.py`, `core/views.py`, all app views/serializers |
| **Alternatives considered** | None — standard Django API library |
| **Redundancy check** | None |
| **Security concerns** | Monitor DRF releases for security patches |
| **Maintenance status** | Active |
| **Final decision** | Approved — explicitly in architecture spec |

---

## djangorestframework-simplejwt

| Field | Value |
|-------|-------|
| **Name** | Simple JWT |
| **Purpose** | JWT authentication for DRF |
| **Package** | `djangorestframework-simplejwt==5.3.1` |
| **Docs** | https://django-rest-framework-simplejwt.readthedocs.io/ |
| **Files used** | `core/settings/base.py`, future `auth` app |
| **Alternatives considered** | `djoser` (rejected: heavier, includes user management we want to own) |
| **Redundancy check** | None |
| **Security concerns** | Use short-lived access tokens (60 min). Rotate refresh tokens. Never store tokens in localStorage. |
| **Maintenance status** | Active |
| **Final decision** | Approved — explicitly in architecture spec |

---

## psycopg (psycopg3)

| Field | Value |
|-------|-------|
| **Name** | psycopg |
| **Purpose** | PostgreSQL database adapter for Python |
| **Package** | `psycopg[binary]==3.2.13` |
| **Docs** | https://www.psycopg.org/psycopg3/docs/ |
| **Files used** | Used by Django's database backend |
| **Alternatives considered** | `psycopg2-binary` (rejected: no pre-built wheel for Python 3.14 on ARM Mac) |
| **Redundancy check** | None |
| **Security concerns** | Keep updated; use connection pooling in production |
| **Maintenance status** | Active — psycopg3 is the current maintained version |
| **Final decision** | Approved — psycopg2 was the original choice; psycopg3 is the direct successor, fully supported by Django 5.x |

---

## python-decouple

| Field | Value |
|-------|-------|
| **Name** | python-decouple |
| **Purpose** | Environment variable and `.env` file management |
| **Package** | `python-decouple==3.8` |
| **Docs** | https://github.com/HBNetwork/python-decouple |
| **Files used** | `core/settings/` |
| **Alternatives considered** | `django-environ` (comparable; decouple chosen for simplicity and no Django coupling) |
| **Redundancy check** | None |
| **Security concerns** | Never commit `.env.production`. Validate all required vars at startup. |
| **Maintenance status** | Active |
| **Final decision** | Approved |

---

## ruff

| Field | Value |
|-------|-------|
| **Name** | ruff |
| **Purpose** | Fast Python linter and formatter (dev-only) |
| **Package** | `ruff==0.4.10` (dev dependency) |
| **Docs** | https://docs.astral.sh/ruff/ |
| **Files used** | All Python files via CI and pre-commit |
| **Alternatives considered** | `black` + `flake8` + `isort` (replaced by ruff which does all three) |
| **Redundancy check** | None — replaces multiple tools |
| **Security concerns** | None (dev-only tool) |
| **Maintenance status** | Active |
| **Final decision** | Approved — explicitly required by CLAUDE.md |

---

## pytest + pytest-django

| Field | Value |
|-------|-------|
| **Name** | pytest / pytest-django |
| **Purpose** | Test runner (dev-only) |
| **Package** | `pytest==8.2.2`, `pytest-django==4.8.0` (dev dependency) |
| **Docs** | https://docs.pytest.org / https://pytest-django.readthedocs.io/ |
| **Files used** | All test files |
| **Alternatives considered** | Django's built-in test runner (pytest-django extends it, no conflict) |
| **Redundancy check** | None |
| **Security concerns** | None (dev-only) |
| **Maintenance status** | Active |
| **Final decision** | Approved |

---

## gunicorn

| Field | Value |
|-------|-------|
| **Name** | gunicorn |
| **Purpose** | Production WSGI server (production-only) |
| **Package** | `gunicorn==22.0.0` (prod dependency) |
| **Docs** | https://gunicorn.org/ |
| **Files used** | `core/wsgi.py` (via deployment config) |
| **Alternatives considered** | `uvicorn` (async; preferred if ASGI is adopted later) |
| **Redundancy check** | None |
| **Security concerns** | Run behind a reverse proxy (nginx). Do not expose directly. |
| **Maintenance status** | Active |
| **Final decision** | Approved |

---

## argon2-cffi

| Field | Value |
|-------|-------|
| **Name** | argon2-cffi |
| **Purpose** | Enables Django's `Argon2PasswordHasher` — a memory-hard password hashing algorithm, used as the primary hasher for the `authenticate` app's ministry-grade security target |
| **Package** | `argon2-cffi==25.1.0` |
| **Docs** | https://argon2-cffi.readthedocs.io/ |
| **Files used** | `core/settings/base.py` (`PASSWORD_HASHERS`) |
| **Alternatives considered** | PBKDF2 alone (rejected as primary — not memory-hard, weaker against GPU/ASIC cracking); bcrypt alone (rejected as primary — Argon2 is the current OWASP-recommended default). Both are kept in `PASSWORD_HASHERS` as fallback/legacy verification hashers. |
| **Redundancy check** | None — Django has no built-in Argon2 support without this binding |
| **Security concerns** | Tune memory/time cost parameters for production hardware; monitor CVEs in the `cffi` binding layer |
| **Maintenance status** | Active |
| **Final decision** | Approved — human-approved for the `authenticate` app build (2026-06-22) |

---

## django-axes

| Field | Value |
|-------|-------|
| **Name** | django-axes |
| **Purpose** | Failed-login attempt tracking and automatic brute-force lockout at the Django authentication-backend layer — the sole engine for this in the project, covering every `django.contrib.auth.authenticate()` entry point including `/admin/login/`, which the `authenticate` app's own service-layer login flow does not pass through |
| **Package** | `django-axes==8.3.1` |
| **Docs** | https://django-axes.readthedocs.io/ |
| **Files used** | `core/settings/base.py` (`INSTALLED_APPS`, `AUTHENTICATION_BACKENDS`, `MIDDLEWARE`, `AXES_*` settings); `authenticate/services.py` (calls `django.contrib.auth.authenticate()` so axes can observe the attempt) |
| **Alternatives considered** | A custom counter on `authenticate.UserSecurityState` (rejected — does not cover `/admin/login/`, and would duplicate counting logic axes already does correctly) |
| **Redundancy check** | Deliberately the *only* failed-attempt counter in the system. `authenticate.UserSecurityState` does not store a parallel `failed_login_count`/auto-lockout state — see `authenticate/docs/SECURITY.md` |
| **Security concerns** | `AxesMiddleware` must be the last entry in `MIDDLEWARE`; `AXES_LOCKOUT_PARAMETERS` set to `["username", "ip_address"]` (balances DoS-lockout risk against distributed credential stuffing) |
| **Maintenance status** | Active |
| **Final decision** | Approved — human-approved for the `authenticate` app build (2026-06-22) |

---

## django-cors-headers

| Field | Value |
|-------|-------|
| **Name** | django-cors-headers |
| **Purpose** | Adds CORS (Cross-Origin Resource Sharing) response headers and preflight (`OPTIONS`) handling, so a frontend served from a different origin/port than the Django API can call it from a browser |
| **Package** | `django-cors-headers==4.9.0` |
| **Docs** | https://github.com/adamchainz/django-cors-headers |
| **Files used** | `core/settings/base.py` (`INSTALLED_APPS`, `MIDDLEWARE`), `core/settings/development.py` (`CORS_ALLOW_ALL_ORIGINS`) |
| **Alternatives considered** | Hand-rolled middleware adding `Access-Control-Allow-*` headers manually (rejected — reinvents preflight/credentials/Vary-header handling that this library already gets right; would be the only hand-rolled security-relevant middleware in the project) |
| **Redundancy check** | None — no existing CORS handling anywhere in the project |
| **Security concerns** | `CorsMiddleware` must sit high in `MIDDLEWARE` (before `CommonMiddleware`). `CORS_ALLOW_ALL_ORIGINS=True` is set **only** in `core/settings/development.py` — staging/production inherit no override, so they default to allowing zero cross-origin requests until an explicit `CORS_ALLOWED_ORIGINS` allowlist is configured for those environments. Never set `CORS_ALLOW_ALL_ORIGINS=True` together with `CORS_ALLOW_CREDENTIALS=True` (the library itself rejects this combination). |
| **Maintenance status** | Active |
| **Final decision** | Approved — human-approved for the development-environment CORS fix (2026-06-29) |

---

## django-otp

| Field | Value |
|-------|-------|
| **Name** | django-otp |
| **Purpose** | TOTP-based multi-factor authentication (`otp_totp.TOTPDevice`) for the `authenticate` app's MFA endpoints. Recovery/backup codes are intentionally NOT used (the concept file locks "recovery codes are not planned"; MFA loss is resolved via the reset hierarchy), so `otp_static` is not installed |
| **Package** | `django-otp==1.7.0` |
| **Docs** | https://django-otp-official.readthedocs.io/ |
| **Files used** | `core/settings/base.py` (`INSTALLED_APPS`); `authenticate/services.py` and `authenticate/selectors.py` (`TOTPDevice` calls) |
| **Alternatives considered** | A custom TOTP/OTP implementation — rejected; the project rulebook explicitly forbids inventing custom OTP generation |
| **Redundancy check** | No custom `MFADevice` model was created — django-otp's `TOTPDevice` is the single source of truth for the MFA secret. MFA-enrolled state is deliberately *not* stored on `authenticate`'s own models; it is derived live from `TOTPDevice.confirmed` to avoid drift |
| **Security concerns** | The TOTP secret is stored by django-otp's own model (DB-level protection); never log the secret or codes, and never return the secret after enrollment confirmation. No app-level field encryption is added — the concept's "or otherwise strongly protected at rest" is met by database protection |
| **Maintenance status** | Active, long-established |
| **Final decision** | Approved — human-approved for the `authenticate` app build (2026-06-22) |

---

## nepali

| Field | Value |
|-------|-------|
| **Name** | nepali |
| **Purpose** | Bikram Sambat (BS) ↔ Gregorian date conversion. Nepal's official calendar is BS; all date display and input in the system uses BS while storage stays Gregorian UTC. |
| **Package** | `nepali==1.2.0` |
| **Docs** | https://github.com/opensource-nepal/py-nepali |
| **Files used** | `core/nepal/calendar.py` |
| **Alternatives considered** | `nepali-datetime` (older, archived); hand-rolled lookup table (rejected — BS month lengths vary year-to-year by traditional rules; maintaining the table is error-prone and this package is actively maintained by opensource-nepal) |
| **Redundancy check** | No existing BS/AD conversion anywhere in the project |
| **Security concerns** | No network calls; pure date arithmetic against a bundled lookup table. No secrets or PII processed. |
| **Maintenance status** | Active (opensource-nepal organization) |
| **Final decision** | Approved — human-approved as part of Nepal localization foundation (2026-07-02) |

---

## indic-transliteration

| Field | Value |
|-------|-------|
| **Name** | indic-transliteration |
| **Purpose** | Devanagari → romanized ASCII transliteration used to auto-populate `name_romanized` fields, enabling Roman-script users to find Devanagari-primary records via PostgreSQL trigram search. |
| **Package** | `indic-transliteration==2.3.82` |
| **Docs** | https://indic-transliteration.readthedocs.io/ |
| **Files used** | `core/nepal/text.py` |
| **Alternatives considered** | Custom character-map table (rejected — incomplete, hard to maintain, misses conjunct consonant clusters); `aksharamukha` (heavier, web-service oriented); `transliterate` (generic, no Indic-specific handling) |
| **Redundancy check** | No other transliteration library in the project |
| **Security concerns** | No network calls; pure string transformation. No secrets or PII stored. |
| **Maintenance status** | Active (Dr. Vishvas Vasuki, widely used in Indic NLP) |
| **Final decision** | Approved — human-approved as part of Nepal localization foundation (2026-07-02) |
