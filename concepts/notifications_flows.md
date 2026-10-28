# FLOWS — Notifications

**Owner app:** `notifications`
**Updated:** 2026-10-29
**Purpose:** The user-flow binding layer for this app — connects the product intent in
`concepts/notifications.txt` to the callable endpoints in `backend/notifications/docs/INTEGRATION.md`.
Authored and updated by the backend author in the same commit as any endpoint change (CLAUDE.md §36).

---

**Two things about this app that shape every flow below, and are easy to get wrong from the frontend:**

- **No notification is created by a user.** There is no compose screen, no create endpoint, and no way for
  one staff member to notify another. Alerts appear because a nightly sweep found a deadline or because
  something happened in another module (a lead converted, an applicant's status changed, a visit
  recorded…). Every inbox flow below is therefore a *reading* flow that ends by leaving this app. The one
  thing a user writes here is their own preferences — which categories they are told about.
- **A notification is not the work.** Dismissing an alert about an overdue passport scan does not
  collect the passport scan. Every flow that actually resolves something crosses into the owning app —
  which is why most steps here are tagged `(cross-app: ...)`.

---

## Flow: Work the daily inbox

- **Actor:** Admin or Lead Manager
- **Goal:** See what needs attention today and act on the most urgent item.
- **Entry point:** Notification Centre (reached from the bell badge in the global header)

**Steps:**

1. **Global header (bell badge)** — the app shell loads, or the user returns to the tab →
   `GET /api/v1/notifications/summary/` (`notifications.notification.summary`)
   - **Which number to show:** `unread`, not `active`. `unread` is what "mark all as read" drives to
     zero, so a badge showing anything else will make that button look broken. Know the trade-off:
     `unread` counts closed-but-never-read alerts too, so it can read slightly higher than the
     `?status=active` list in step 2. The backend offers no single count that is both.
   - **Requires state:** an authenticated Admin or Lead Manager session. Nothing else — a user who has
     never received an alert gets a valid all-zero summary.
   - **Side effects:** none. Reading the summary marks nothing read.
   - *Failure — `NOTIFICATIONS_ACTOR_FORBIDDEN`:* the caller is a Superadmin. Hide the bell entirely
     rather than showing an error badge — this authority has no inbox and never will.
   - **Note:** the same response carries `by_category` — per-tab counts for the flow "Browse the inbox
     by category". There is no separate unread-count endpoint.

2. **Notification Centre** — the user opens the inbox →
   `GET /api/v1/notifications/?status=active` (`notifications.notification.list`)
   - **Requires state:** as above.
   - **Side effects:** none.
   - *Failure — `VALIDATION_ERROR`:* only reachable by sending a bad filter value. Treat as a bug in
     the client, not as an empty state.
   - **Note:** send `status=active` explicitly. Omitting it returns dismissed and resolved history too,
     which is correct for an archive view and wrong for a working inbox.

3. **Notification Centre** — the user groups the list into "due now / due soon / later" →
   no additional request.
   - Every row already carries `due_bucket`. Group client-side rather than making three filtered
     requests; the three would be computed against three different clocks.

4. **Notification Centre** — the user opens an alert →
   `POST /api/v1/notifications/<id>/read/` (`notifications.notification.mark_read`)
   - **Requires state:** the notification exists and is addressed to the calling user. Any status —
     a resolved alert can still be marked read.
   - **Side effects:** sets `read_at` on this notification only. Refresh the badge, not the list —
     `status` is unchanged, so the row stays where it is.
   - *Failure — `NOTIFICATIONS_NOTIFICATION_NOT_FOUND`:* the alert was addressed to somebody else, or
     never existed. Remove the row and re-fetch; do not retry.

5. **Notification Centre** — the user clicks through to the underlying record →
   follow the row's `source_api_path` **(cross-app: `checklists` / `offers` / `applicants` /
   `uploaded_files` / `applicant_journeys` / `reminders` / `leads` / `documents`)**
   - **Requires state:** the caller must independently hold permission for the target record.
     Receiving an alert does not grant it.
   - **Side effects:** none in this app.
   - *Failure — a 403 or 404 from the other module:* show the alert's `title` and `body` as the whole
     of what the user gets, and say the record is not available to them. Do **not** treat this as a
     broken link.

6. **The owning app's screen** — the user does the actual work (completes the item, answers the offer)
   **(cross-app: owner of the source record)**
   - **Side effects in this app:** none immediately. The alert stays `active` until the next nightly
     sweep resolves it. See "Open questions" — the client cannot know when that is.
   - **UI treatment:** on returning to the inbox, the alert will still be there. Either let the user
     dismiss it, or show resolved-but-unread alerts distinctly after the sweep runs.

## Flow: Clear an alert that needs no action

- **Actor:** Admin or Lead Manager
- **Goal:** Remove an alert the user has judged irrelevant, permanently.
- **Entry point:** Notification Centre

**Steps:**

1. **Notification Centre** — the user chooses "dismiss" on a row →
   `POST /api/v1/notifications/<id>/dismiss/` (`notifications.notification.dismiss`)
   - **Requires state:** the notification exists, is addressed to the calling user, and is `active`.
   - **Side effects:** the alert becomes `dismissed` and leaves the `?status=active` feed. It is
     **not deleted** by dismissing and still appears in an unfiltered list (event alerts are purged
     after 90 days like any other; dismissed deadline alerts are kept). An audit event is written
     **(cross-app: `audit`)**. Most importantly: **no later sweep will raise this condition again.**
     Refresh both the list and the badge.
   - *Failure — `NOTIFICATIONS_ALREADY_TERMINAL` (409):* another session already closed it. Re-fetch
     the single row with `notifications.notification.read` and show its current state — do not retry
     and do not show a generic error.
   - *Failure — `NOTIFICATIONS_NOTIFICATION_NOT_FOUND`:* as in the flow above.
   - **UI treatment — this one matters.** Present dismissal as a decision, not as "hide for now".
     There is no snooze and no un-dismiss in this version. A confirmation step is warranted on
     `high` and `urgent` rows.

2. **Notification Centre** — the user regrets it →
   no endpoint exists.
   - The only way the condition returns is **escalation**: an item dismissed while merely due-soon
     will alert again if it later becomes overdue, because that is a different alert type. Nothing
     the client can call reverses a dismissal.

## Flow: Clear the badge without deciding anything

- **Actor:** Admin or Lead Manager
- **Goal:** Get the unread count to zero after skimming the inbox.
- **Entry point:** Notification Centre

**Steps:**

1. **Notification Centre** — the user clicks "mark all as read" →
   `POST /api/v1/notifications/read-all/` (`notifications.notification.mark_all_read`)
   - **Requires state:** an authenticated Admin or Lead Manager session. Succeeds with
     `marked_read: 0` when nothing is unread — no need to disable the button.
   - **Side effects:** every unread notification on the caller's feed becomes read, **including
     dismissed and resolved ones**. Nothing is dismissed or resolved. No other user is affected.
   - *Failure:* none beyond the global auth failures.

2. **Global header (bell badge)** — reconcile →
   `GET /api/v1/notifications/summary/` (`notifications.notification.summary`)
   - **Note:** `unread` drops to `0` and `active` does **not** change. If the badge is driven by
     `active` rather than `unread`, this button will appear broken — drive it from `unread`.

## Flow: Review the alert history for one record

- **Actor:** Admin or Lead Manager
- **Goal:** From an applicant, checklist, or offer screen, see what alerts this record has produced.
- **Entry point:** any source-record detail screen (owned by another app)

**Steps:**

1. **Source record detail screen** — the user opens an "alerts" panel →
   on an applicant: `GET /api/v1/notifications/?applicant_id=<applicant id>`; on any other record:
   `GET /api/v1/notifications/?source_entity_id=<record id>` (`notifications.notification.list`)
   - **Requires state:** the record id, taken from whichever app's screen the user is on.
   - **Side effects:** none.
   - **Note:** omit `status` here — the point of this panel is the history, including resolved and
     dismissed alerts. `?applicant_id=` gathers everything about the applicant (status, assignment,
     visit notes, journeys, passport and test expiry, reminders) but misses alerts raised before
     2026-10-29, and nothing older than the 90-day retention window survives for event alerts.
   - **UI treatment — do not mislabel this panel.** It returns only alerts **the calling user
     received**. Alerts about the same record sent to other staff are invisible. Title it
     "Your alerts for this record", never "All alerts". If a complete cross-user history is what the
     screen needs, this app cannot provide it — `audit` is the module that can.

## Flow: Browse the inbox by category

- **Actor:** Admin or Lead Manager
- **Goal:** Work one kind of alert at a time — leads, applicant status, documents… — with a badge per tab.
- **Entry point:** Notification Centre (category tabs)

**Steps:**

1. **Notification Centre (tab bar)** — the inbox opens →
   `GET /api/v1/notifications/summary/` (`notifications.notification.summary`)
   - **Requires state:** an authenticated Admin or Lead Manager session.
   - **Side effects:** none.
   - **UI treatment:** one tab per category, badged from `by_category`; the "All" tab from `unread`
     (always the sum of the tabs). Every category key is present, zero-filled — render empty tabs as
     quiet rather than hiding them, or the tab bar reflows as counts change.

2. **Notification Centre (a tab)** — the user selects a tab →
   `GET /api/v1/notifications/?category=<category>&status=active` (`notifications.notification.list`)
   - **Requires state:** as above.
   - **Side effects:** none.
   - **Note:** a combined tab can send several categories comma-separated (`?category=lead,notes`).
   - *Failure — `VALIDATION_ERROR` (400, `category`):* the client sent a category the server does not
     know — a client bug, not an empty tab.

3. **Notification Centre (a tab)** — the user clicks "mark all read" on this tab →
   `POST /api/v1/notifications/read-all/` with `{ "category": "<category>" }`
   (`notifications.notification.mark_all_read`)
   - **Requires state:** as above. Succeeds with `marked_read: 0` when the tab has nothing unread.
   - **Side effects:** only that category's unread notifications become read. Nothing is dismissed.
     Re-fetch the summary — that tab's count drops to 0, the others do not move.
   - **Note:** one category per call. A combined tab issues one call per category it covers.
   - *Failure — `VALIDATION_ERROR` (400, `category`):* unknown category; a client bug.

## Flow: Set my notification preferences

- **Actor:** Admin or Lead Manager
- **Goal:** Stop being told about a kind of alert, or only hear about applicants assigned to me.
- **Entry point:** Notification settings (reached from the Notification Centre)

**Steps:**

1. **Notification settings** — the screen opens →
   `GET /api/v1/notifications/preferences/` (`notifications.preference.read`)
   - **Requires state:** an authenticated Admin or Lead Manager session. Nothing saved is needed — a
     new user gets every category on and "only my applicants" off.
   - **Side effects:** none.
   - *Failure — `NOTIFICATIONS_ACTOR_FORBIDDEN`:* Superadmin; do not offer this screen.

2. **Notification settings** — the user flips a category switch or the "only my applicants" toggle →
   `PATCH /api/v1/notifications/preferences/` (`notifications.preference.update`)
   - **Send only what changed** — e.g. `{ "categories": { "lead": { "in_app": false } } }` or
     `{ "assigned_only": true }`. Re-render from the response, which is always the full set.
   - **Requires state:** as above.
   - **Side effects:** changes which alerts are **created** for this user from now on. Nothing already in
     the feed is hidden, deleted, or restored, and the badge does not change on the spot.
   - *Failure — `VALIDATION_ERROR` (400, `categories`):* an unknown category key — a client bug.
   - **UI treatment — say this on the screen.** "Applies to new notifications." Turning a category back
     on does not bring back alerts that were skipped while it was off. "Only my applicants" affects only
     alerts about an applicant; lead, offer, and checklist alerts without an applicant still arrive.

---

## Endpoint coverage

| `permission_key` | `METHOD /path` | Used by flow(s) | Notes |
|------------------|----------------|-----------------|-------|
| `notifications.notification.list` | `GET /api/v1/notifications/` | Work the daily inbox; Review the alert history for one record; Browse the inbox by category | Three call sites with different filters (`status`, `applicant_id`/`source_entity_id`, `category`) |
| `notifications.notification.summary` | `GET /api/v1/notifications/summary/` | Work the daily inbox; Clear the badge without deciding anything; Browse the inbox by category | The only endpoint the app shell polls; `by_category` feeds the tab badges |
| `notifications.notification.read` | `GET /api/v1/notifications/<id>/` | Clear an alert that needs no action (409 recovery) | No flow opens a notification detail *screen* — the feed row is the whole resource, so this is a re-fetch call, not a navigation target |
| `notifications.notification.mark_read` | `POST /api/v1/notifications/<id>/read/` | Work the daily inbox | |
| `notifications.notification.mark_unread` | `POST /api/v1/notifications/<id>/unread/` | — | `unused by flow — the "put it back" affordance. Deliberately available and deliberately not part of a named journey: it exists so opening a row is a safe act, not because any flow depends on it` |
| `notifications.notification.mark_all_read` | `POST /api/v1/notifications/read-all/` | Clear the badge without deciding anything; Browse the inbox by category | No body clears all; `{ category }` clears one tab |
| `notifications.notification.dismiss` | `POST /api/v1/notifications/<id>/dismiss/` | Clear an alert that needs no action | The only irreversible action in this app |
| `notifications.preference.read` | `GET /api/v1/notifications/preferences/` | Set my notification preferences | Always the caller's own |
| `notifications.preference.update` | `PATCH /api/v1/notifications/preferences/` | Set my notification preferences | Partial update; affects new alerts only |

## Cross-app dependencies

- **This app references (outbound):** no other app's `permission_key` is called by a fixed route in
  any flow above. The click-through in "Work the daily inbox" step 5 follows the `source_api_path`
  the alert itself carries, which resolves into `checklists`, `offers`, `applicants`,
  `uploaded_files`, `applicant_journeys`, `reminders`, `leads`, or `documents` depending on the alert type — so the outbound edge is
  **data-driven, not hard-coded**. A client should route on `source_app` + `source_entity_type`
  rather than parsing the path.
- **Referenced by other apps (inbound):** `concepts/reminders_flows.md` — its "Act on a due reminder
  alert" flow enters from this app's feed (`notifications.notification.list`) and clears the alert by
  closing the *reminder*, relying on the sweep's auto-resolve rather than a dismiss call here. The natural future inbound reference is an "alerts" panel on the applicant, checklist,
  and offer detail screens — the fourth flow above — which those apps' flow files may want to
  reference once those panels are designed.

When an endpoint here is added, changed, or deprecated, grep `concepts/*_flows.md` for its
`permission_key` and update every referencing flow in the same commit (the CLAUDE.md §36 ripple rule) —
not just this file.

## Open questions

- **Polling interval for the badge is undefined, and push was declined.** There is no push channel — no
  websocket, no SSE (requested in updates.md §4 and declined), no long-poll. The frontend must choose an
  interval for `notifications.notification.summary`, and the backend has no opinion recorded yet. There
  is no conditional-request support either (no `ETag`, no `Last-Modified`), so every poll is a full
  response against the shared authenticated rate limit. Pausing on `document.hidden` and re-fetching on
  focus is the obvious mitigation and is the client's call to make. Event alerts are written as soon as
  the triggering change commits (in-process, not via a queue), so the next poll sees them.
- **Other updates.md §4 asks that were declined:** cursor pagination (the feed stays page-number), a
  dedicated `unread-count/` endpoint (`summary/` carries `unread` and `by_category`), and a
  `case_journey` category (no "case" concept here — use `journey`).
- **The feed cannot be sorted, and the Notification Centre wireframe should not assume it can.** There
  is no `ordering` parameter: rows come back newest-created first, always. An urgent alert from last
  week sits below a low-priority one from this morning, and sorting a page client-side does not fix
  it because the rows that belong at the top may be on page three. Today the only real remedy is to
  build the sections from separate filtered requests (`?priority=urgent`, then `?due_bucket=overdue`)
  rather than one list the user re-sorts. Adding `?ordering=` is the fix and it is not built.
- **The sweep's run time is not exposed.** Alerts resolve when the nightly job runs, and no endpoint
  reports when that is or when it last ran. A client cannot tell a user "this will clear overnight"
  with any accuracy.
- **No snooze and no un-dismiss.** Per-category mute and "only my applicants" are built (Set my
  notification preferences); snooze is still an open question in `concepts/notifications.txt` and is
  not built. If the Notification Centre wireframe shows a snooze control, it has no endpoint behind it.
- **History older than 90 days is deleted for most alerts.** The nightly sweep purges event alerts and
  resolved deadline alerts past the retention window (an operator setting). An "alerts" panel or an
  archive view must not promise complete history.
- **Older alerts lack the new fields.** Alerts raised before 2026-10-29 have `applicant_id: null` and an
  empty `payload`, so `?applicant_id=` and "only my applicants" do not see them.
- **Two alert types are declared but never produced** — `missing_information` and
  `appointment_reminder`. Render them if they ever arrive, but do not design a screen around them: the
  first has no source definition anywhere in the project, and the second waits on an `appointments`
  app.
- **Recipient routing is invisible to the client.** Who receives which alert is decided server-side
  (summarised in `backend/notifications/docs/INTEGRATION.md` §5), and no endpoint reports or influences
  it beyond the caller's own preferences. A UI cannot show "this was also sent to X". Two quirks worth
  knowing: assigning a checklist item to yourself still alerts you, and a previous assignee with "only
  my applicants" on does not get the "no longer assigned to you" alert.
