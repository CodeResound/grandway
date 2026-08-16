# Debug History — Checklists

## 2026-08-01 — A failing audit write could abort unrelated post-commit work

**Endpoint/module:** `checklists.signals.inherit_country_checklist`
**Problem:** The module docstring promises that nothing propagates out of this receiver — it runs from `transaction.on_commit`, after the journey is safely saved, and a failure to generate a checklist must never be reported to a client who is no longer waiting. The `inherit_for_journey` call honoured that. The `record_event` call that reports the failure sat *outside* the `try`, so an audit write that failed while recording an inheritance failure would raise out of the callback — and an exception in an `on_commit` callback propagates out of the commit and stops every callback queued behind it, including `notifications`' journey alert for the same save.
**Root cause:** The error path was written to log *and* audit the failure, and only the work being guarded was placed inside the guard. The reporting itself was assumed not to fail.
**Changed files:** `signals.py`
**Fix summary:** The `record_event` call is wrapped in its own `try`, logging if it fails. The original failure has already reached the log by that point, so losing its audit row is the lesser loss — and unrelated post-commit work is no longer collateral.
**Contract impact:** None.
**Tests added/updated:** None specific; existing signal tests still pass.
**Notes for future AI:** In an `on_commit` callback, the error handler is as much a hazard as the operation. Anything that can raise there takes down every callback queued behind it, which is work belonging to other apps entirely.
