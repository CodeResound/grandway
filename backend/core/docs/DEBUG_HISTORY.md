# Debug History — Core

## 2026-08-01 — The standard error envelope discarded `WWW-Authenticate` and `Retry-After`

**Endpoint/module:** `core.exceptions.global_exception_handler`
**Problem:** Every 401 in the project was returned without a `WWW-Authenticate` header (RFC 7235 requires one on every 401), and every 429 without `Retry-After` — so a throttled client had no way to learn when to retry and could only guess, which is what turns a rate limit into a retry storm.
**Root cause:** The handler calls DRF's `exception_handler`, which builds those headers onto the response it returns, then discards that response entirely in favour of a freshly constructed standard-envelope one. The body was carried across; the headers were not. Easy to miss because the headers belong to the HTTP exchange rather than to the envelope this module exists to standardise.
**Changed files:** `exceptions.py` (`_protocol_headers`, `_error_response`)
**Fix summary:** `_protocol_headers` re-derives the two headers from the exception's `auth_header`/`wait` attributes — the same source DRF reads, so the two can never disagree — and `_error_response` accepts and applies them. The envelope is unchanged.
**Contract impact:** `API.md` — additive only. Responses that previously lacked these headers now carry them; no body, status code, or error code changed.
**Tests added/updated:** `core/tests/test_error_headers.py` — a throttled response carries `Retry-After` while keeping the standard envelope, a 401 with an auth scheme carries `WWW-Authenticate`, and an exception with neither adds neither.
**Notes for future AI:** When replacing a framework's response object, check what it attached besides the body. Headers, cookies, and status are all carried on the object being thrown away.

---

## 2026-08-01 — Rate limiting was bypassable and per-process; TLS redirect looped behind a proxy

**Endpoint/module:** `core.settings.base`, `core.settings.production`, `core.settings.staging`
**Problem:** Four independent configuration defects, all invisible to the suite because no test loads the deployment settings modules.
1. `REST_FRAMEWORK["NUM_PROXIES"]` was unset. At DRF's default of `None`, `SimpleRateThrottle.get_ident` falls through to using the whole client-supplied `X-Forwarded-For` header as the throttle identity, so varying it per request yields a fresh bucket every time — voiding `LoginIPThrottle` and `RefreshThrottle`, the two limits in front of credential stuffing.
2. No `CACHES` block existed, so DRF's throttle counters lived in the implicit `LocMemCache` — per-process. Under gunicorn with N workers every configured rate limit was really N×, and all counters reset on each restart.
3. `production.py` set `SECURE_SSL_REDIRECT = True` without `SECURE_PROXY_SSL_HEADER`. Behind a TLS-terminating proxy every request arrives over plain HTTP, so Django would judge all of them insecure and redirect to a URL that arrives over HTTP again — an unconditional redirect loop on the first request after deploy.
4. Neither `production.py` nor `staging.py` set `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, or `CSRF_TRUSTED_ORIGINS`; they existed only in `development.py`. django-cors-headers denies all cross-origin requests when unset, so a frontend on its own domain could neither call the API nor send the refresh cookie.
**Root cause:** Each is a Django/DRF default that is safe in development and wrong in deployment, and nothing exercises the deployment settings modules. (3) and (4) in particular only fail once a real proxy and a real browser are in front of the app.
**Changed files:** `settings/base.py` (`_NUM_PROXIES`, `CACHES`, `REST_FRAMEWORK["NUM_PROXIES"]`, `AXES_IPWARE_*`), `settings/production.py`, `settings/staging.py`, `.env.development.example`
**Fix summary:** `_NUM_PROXIES` is read once from the environment (default 0 — no proxies, `X-Forwarded-For` ignored) and feeds both DRF's throttles and django-axes' lockout, so the two can never count different identities. `CACHES` is named explicitly with a comment stating that it *is* the rate limiter's memory and that a multi-worker deployment must point it at a shared backend. `SECURE_PROXY_SSL_HEADER` is set in both deployment modules. The three origin settings are required environment values with no default, so a deployment that forgets them fails loudly at startup rather than silently denying every browser request.
**Contract impact:** Deployment-affecting. `NUM_PROXIES` must be set to the real hop count in any proxied environment, and `CORS_ALLOWED_ORIGINS`/`CSRF_TRUSTED_ORIGINS` are now mandatory in staging and production.
**Tests added/updated:** None — the settings modules are not importable under the test settings. Verified by loading `core.settings.production` and `core.settings.staging` directly with and without the required environment.
**Notes for future AI:** `AXES_IPWARE_META_PRECEDENCE_ORDER` defaults to `("REMOTE_ADDR",)`, so django-axes does *not* trust `X-Forwarded-For` out of the box — the opposite of DRF. The two subsystems had opposite defaults for the same question, which is why the value is now read once and shared.
