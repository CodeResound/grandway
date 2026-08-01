# Debug History — Authenticate

## 2026-08-01 — Django admin bypassed the authority hierarchy and both audit trails

**Endpoint/module:** `authenticate.admin` (`UserAdmin`, `UserSecurityStateAdmin`)
**Problem:** An authorization probe used a Superadmin's Django admin session to promote a Lead Manager to Superadmin — setting `authority_type`, `is_staff`, and `is_superuser` in one POST — and separately to reactivate a blocked account. Both succeeded (302). Both wrote **zero** `AuthEvent` and **zero** `AuditEvent` rows. The unblock also left `User.is_active = True` while `UserSecurityState.blocked_at` stayed set, so the two rows disagreed about whether the account was blocked: anything reporting on `blocked_at` would say yes while login said no.
**Root cause:** `UserAdmin.readonly_fields` protected `password` and `id` but left `authority_type`, `is_active`, `username`, and the `PermissionsMixin` flags editable. A `ModelAdmin` form runs the model's own field validation and nothing else — not `_MANAGED_TIER` (which confines a Superadmin to managing the Admin tier), not `block_account`/`restore_account` (which write both rows and audit the change), not `normalize_unicode` (§39.2). The module docstring asserted "Admin never bypasses application validation", which was true of *field* validation and false of every business rule.
**Changed files:** `admin.py`
**Fix summary:** Every field carrying a service-layer invariant is now read-only: `username` (immutable by contract), `authority_type`/`is_staff`/`is_superuser` (set only under the authority hierarchy), `is_active` (half of a two-row block), and `groups`/`user_permissions` (the route by which a non-superuser staff account would gain model access at all). `UserSecurityState` is read-only throughout and no longer addable, since it is created by `create_account` alongside its `User`. `User` is no longer addable either — with `password` and `authority_type` read-only, the add form could only produce an account with no authority and an unusable password.
**Contract impact:** None at the API surface. Operationally, blocking, restoring, password resets, and authority changes must now go through their endpoints — which is where they were always specified to happen.
**Scope note:** This narrows what the admin can *do*. It does not change who may *reach* it, which is the larger question: `is_staff` is true for both Admin and Superadmin, and `is_superuser` is true for Superadmin, so a Superadmin still has read access to all 44 registered models — including applicants, leads, and uploaded files — that `access.py` denies it on every API route. Narrowing that is an authorization change (§28 item 5) and remains open.
**Tests added/updated:** `test_admin_hardening.py` — 8 tests covering authority escalation, flag grants, the blocked-account divergence, username immutability, add-permission on both models, and `AuthEvent` delete (which was already correctly refused).
**Notes for future AI:** In this project the Django admin is not a view onto the service layer, it is a parallel write path with none of its rules. Any field left editable there is a business rule that can be bypassed silently by whoever holds `is_superuser`. When registering a model, the default should be read-only, with editability argued for field by field.

---

## 2026-08-01 — Concurrent refresh violated the one-active-session-per-device constraint

**Endpoint/module:** `authenticate.services.refresh_session`, `authenticate.selectors`
**Problem:** Two refresh requests carrying the same token, arriving concurrently, both succeeded past the "is this session active" check and both inserted a replacement session. The second insert violated `uniq_active_session_per_device` and surfaced to the client as an unhandled `IntegrityError` — a 500 — while the original token had already been rotated away, so the user was also logged out. Reproduced deterministically in a probe that reads the row twice before either write.
**Root cause:** `refresh_session` read the active session with the unlocked `get_active_session_by_refresh_hash`, then entered `transaction.atomic()` to rotate it. The transaction made the two writes atomic but did nothing to stop a second reader from observing the same pre-rotation state — a classic read-then-write race. `issue_session` in the same module already used `select_for_update()`; the rotation path simply never did. Invisible to the suite because it runs on SQLite, where `select_for_update` compiles to nothing, so neither the bug nor the fix is observable there.
**Changed files:** `selectors.py` (`get_active_session_by_refresh_hash_for_update`), `services.py` (`refresh_session` restructured into `_handle_missing_active_session` + `_rotate_locked_session`)
**Fix summary:** The rotation now reads under `select_for_update(of=("self",))` inside the transaction, so the second request blocks until the first commits and then correctly finds no active session — which the existing reuse-detection path already handles. `of=("self",)` is required, not decorative: `select_related` pulls `user__security_state` through a LEFT OUTER JOIN, and PostgreSQL refuses `FOR UPDATE` against the nullable side of an outer join, so an unqualified lock would have failed on the production engine while passing on SQLite. The audit write and token build were moved outside the locked block so a row lock is not held across an `AuthEvent` insert.
**Contract impact:** None. No request or response shape changed; a race that returned 500 now returns the documented `REFRESH_REUSED` / `REFRESH_INVALID` 401.
**Tests added/updated:** `test_session_hardening.RefreshRotationLockTests` — asserts `FOR UPDATE` reaches the compiled SQL (skipped on backends without it, rather than passing vacuously), that the locking selector still resolves the active session, and that a second rotation of one token is refused as reuse.
**Notes for future AI:** A read-then-write across `transaction.atomic()` is not made safe by the transaction. If the decision to write depends on a row's current state, lock that row. And when a lock is added to a `select_related` queryset, check whether any of the joins are nullable — `of=("self",)` is usually the answer, and the failure without it appears only on PostgreSQL.

---

## 2026-08-01 — MFA was silently skipped for any TOTP device not named `default`

**Endpoint/module:** `authenticate.selectors` (TOTP lookups), `authenticate.services.login`
**Problem:** A confirmed `TOTPDevice` under any name other than `"default"` was invisible to login: `has_confirmed_mfa` returned `False`, no code was demanded, and the account authenticated on password alone. The user could see the device in the Django admin and reasonably believe MFA was protecting the account.
**Root cause:** Detection was name-scoped (`filter(user=user, name=TOTP_DEVICE_NAME, confirmed=True)`) while removal was not (`reset_mfa`/`disable_mfa` delete `filter(user=user)` across all names). The two halves disagreed, and they disagreed in the fail-open direction. `django_otp.plugins.otp_totp` is in `INSTALLED_APPS` and registers `TOTPDevice` in the admin, so a differently-named device is reachable in practice, not hypothetical.
**Changed files:** `selectors.py` (`get_confirmed_totp_devices` added; `get_confirmed_totp_device` and `has_confirmed_mfa` no longer name-scoped), `services.py` (`verify_totp_code` added; `login` and `disable_mfa` use it)
**Fix summary:** Any confirmed device now counts as enrollment, and `verify_totp_code` accepts a code from any of them — so a user holding two confirmed devices can authenticate with either. `get_unconfirmed_totp_device` stays name-scoped deliberately: it addresses the enrollment *this app* started, and widening it would let `mfa/verify/` confirm a secret the user never scanned here.
**Contract impact:** None at the API surface. Behavioural: an account with a differently-named confirmed device now requires a code at login where it previously did not.
**Tests added/updated:** `test_session_hardening.MfaDeviceNamingTests` — a differently-named device counts as enrolled, forces `MfaRequiredError` at login, and its code verifies; an unconfirmed device still does not count.
**Notes for future AI:** When one query decides "does this protection exist" and another decides "remove this protection", they must share a predicate. Extract it (here, `get_confirmed_totp_devices`) rather than repeating the filter — a divergence between the two is invisible until it is exploited.

---

## 2026-08-01 — `last_used_at` held the session's creation time

**Endpoint/module:** `authenticate.models.AuthSession`, `authenticate.authentication`
**Problem:** `AuthSession.last_used_at` was serialized to clients and used to order the "your active sessions" list, but nothing in the project ever wrote it — so it showed when the session was *created*. On the one screen where a user decides whether a device is still theirs, a long-idle session looked as recently used as an active one.
**Root cause:** The field was declared `auto_now_add=True`, which sets it once on insert. That reads like a sensible default and is why it survived review; a grep for writers returns only the declaration, the serializer, and the ordering.
**Changed files:** `core/settings/base.py` (`AUTH_SESSION_LAST_USED_RESOLUTION`), `authentication.py` (`_touch_last_used`)
**Fix summary:** `SessionBoundJWTAuthentication.get_user` refreshes the column once its value is older than `AUTH_SESSION_LAST_USED_RESOLUTION` (default 5 minutes). Writing on every request would add an UPDATE to the hot path of every authenticated call in the project; a coarse resolution buys an honest column for roughly one write per session per interval. Uses `QuerySet.update` so it is one statement and does not trip `auto_now` on `updated_at` — session *use* is not session *modification*.
**Contract impact:** None — the field already existed and was already serialized. Its values are now correct.
**Tests added/updated:** `test_session_hardening.LastUsedAtTests` — an authenticated request advances a stale value end-to-end through the API, and a fresh value is not rewritten (the bounded-cost half).
**Notes for future AI:** `auto_now_add` on a field whose name says "last" is worth a second look. If a column is displayed to a user, something must write it on the event it claims to describe.

---

## 2026-08-01 — "Best-effort" central-audit emit could roll back its caller's transaction

**Endpoint/module:** `authenticate.services._emit_to_central_audit`
**Problem:** The federated emit to `audit.services.record_event` documents that it never breaks the triggering action, and swallows every exception to that end. But it runs inline inside five `@transaction.atomic` callers (`create_managed_account`, `update_managed_account`, `block_account`, `restore_account`, `admin_reset_password`), and `record_event` performs an INSERT. On PostgreSQL a failed statement aborts the enclosing transaction: catching the exception does not clear that state, every later statement errors, and the eventual COMMIT silently degrades to a ROLLBACK. The endpoint would answer 201 for an account that was never created.
**Root cause:** A `try/except` around a database call inside an outer atomic block controls the Python exception but not the database's transaction state. Only a savepoint does. Not caught by the suite because it runs on SQLite, whose abort semantics differ — a probe against SQLite absorbs the failure cleanly, which is exactly why this was reported as a reasoned risk rather than a reproduced one.
**Changed files:** `services.py` (`_emit_to_central_audit`)
**Fix summary:** The `record_event` call is wrapped in its own `transaction.atomic()`, so a failure rolls back only that savepoint and leaves the caller's transaction usable. The promise the docstring makes now holds on the production engine, not only on the test one.
**Contract impact:** None.
**Tests added/updated:** None that can prove it — the failure mode does not exist on SQLite, and the suite has no PostgreSQL-backed settings module. Recorded here and in the audit report as a known coverage gap.
**Notes for future AI:** `except Exception` around a query inside `@transaction.atomic` is a false promise on PostgreSQL unless a savepoint is opened. The same shape is safe in `checklists/signals.py` and `notifications/signals.py` only because those defer to `transaction.on_commit`, which runs after the transaction has ended.

---

## 2026-08-01 — Administrative MFA reset recorded no origin

**Endpoint/module:** `authenticate.services.admin_reset_mfa`, `reset_mfa`
**Problem:** `admin_reset_mfa` accepted `ip_address` and `user_agent` from the view and passed neither on, so every administrative MFA removal landed in the audit trail with a null IP — on one of the few actions that strips a security control from another user's account.
**Root cause:** `reset_mfa` had no parameters for them, and the caller's arguments were silently dropped rather than failing.
**Changed files:** `services.py` (`reset_mfa`, `admin_reset_mfa`)
**Fix summary:** `reset_mfa` accepts `ip_address`/`user_agent` and forwards them to `record_auth_event`; `admin_reset_mfa` passes through what the view gave it.
**Contract impact:** None. `AuthEvent.ip_address` is populated where it previously was null.
**Tests added/updated:** None specific; covered incidentally by existing `admin_reset_mfa` tests.
**Notes for future AI:** A function that accepts a parameter it never reads is worth treating as a bug, not dead weight — the caller is passing it because it believes it matters somewhere.
