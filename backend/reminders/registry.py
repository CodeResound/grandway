"""Core Policy Engine endpoint declarations for the reminders app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

One model, ``reminder``. The create endpoint deliberately declares no strict
dependency on the owner apps' read keys: a reminder needs *either* an
applicant *or* a client, and a strict dependency on both would demand access
a caller may legitimately lack for one of the two — the same reasoning as
``uploaded_files.file.upload``.
"""

from typing import Any

_APP: dict[str, Any] = {
    "app_key": "reminders",
    "app_display_name": "Reminders",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "reminder_management",
    "category_display_name": "Reminder Management",
}

_REMINDER: dict[str, Any] = {
    **_APP,
    "model_key": "reminder",
    "model_display_name": "Reminder",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_REQUIRES_REMINDER_READ = [_dep("reminders.reminder.read", "The reminder must be readable before it can be acted on.")]

_PHASE = "reminders app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. List reminders — the record panels (?applicant= / ?client=) and any
    #    due-window worklist.
    {
        **_REMINDER,
        "endpoint_key": "reminder-list",
        "permission_key": "reminders.reminder.list",
        "operation_type": "list",
        "display_name": "List Reminders",
        "description": "List follow-up reminders, filterable by owning record, status, and due window. Shared, not owner-scoped.",
        "http_method": "GET",
        "route_pattern": "/api/v1/reminders/",
        "view_import_path": "reminders.views.ReminderListCreateView",
        "risk_level": "low",
        "dependencies": [
            _dep(
                "authenticate.session.login",
                "A session must be established by login before this endpoint is usable.",
            )
        ],
        "change_summary": "Initial registration of the reminder list endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Set a reminder against one applicant or client.
    {
        **_REMINDER,
        "endpoint_key": "reminder-create",
        "permission_key": "reminders.reminder.create",
        "operation_type": "create",
        "display_name": "Set Reminder",
        "description": "Set a one-off future follow-up note against exactly one applicant or client.",
        "http_method": "POST",
        "route_pattern": "/api/v1/reminders/",
        "view_import_path": "reminders.views.ReminderListCreateView",
        "risk_level": "medium",
        "dependencies": [
            _dep("reminders.reminder.list", "Setting reminders requires the ability to list them."),
        ],
        "change_summary": "Initial registration of the reminder create endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Read one reminder — the dependency root for every per-reminder action.
    {
        **_REMINDER,
        "endpoint_key": "reminder-read",
        "permission_key": "reminders.reminder.read",
        "operation_type": "read",
        "display_name": "View Reminder",
        "description": "Retrieve one reminder with its owner reference, due date, note, and lifecycle state.",
        "http_method": "GET",
        "route_pattern": "/api/v1/reminders/<reminder_id>/",
        "view_import_path": "reminders.views.ReminderDetailView",
        "risk_level": "low",
        "dependencies": [_dep("reminders.reminder.list", "Reading a reminder requires list access.")],
        "change_summary": "Initial registration of the reminder read endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Reschedule or correct the note. Owner and lifecycle are out of reach.
    {
        **_REMINDER,
        "endpoint_key": "reminder-update",
        "permission_key": "reminders.reminder.update",
        "operation_type": "update",
        "display_name": "Reschedule Reminder",
        "description": "Move an open reminder's due date or correct its note. Owner and status are unaffected.",
        "http_method": "PATCH",
        "route_pattern": "/api/v1/reminders/<reminder_id>/",
        "view_import_path": "reminders.views.ReminderDetailView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_REMINDER_READ,
        "change_summary": "Initial registration of the reminder update endpoint.",
        "change_reason": _PHASE,
    },
    # 5. The follow-up happened.
    {
        **_REMINDER,
        "endpoint_key": "reminder-complete",
        "permission_key": "reminders.reminder.complete",
        "operation_type": "custom",
        "display_name": "Complete Reminder",
        "description": "Mark an open reminder's follow-up as done. Terminal — a reminder is never reopened.",
        "http_method": "POST",
        "route_pattern": "/api/v1/reminders/<reminder_id>/complete/",
        "view_import_path": "reminders.views.ReminderCompleteView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_REMINDER_READ,
        "change_summary": "Initial registration of the reminder complete endpoint.",
        "change_reason": _PHASE,
    },
    # 6. The follow-up is no longer relevant.
    {
        **_REMINDER,
        "endpoint_key": "reminder-dismiss",
        "permission_key": "reminders.reminder.dismiss",
        "operation_type": "custom",
        "display_name": "Dismiss Reminder",
        "description": "Drop an open reminder that is no longer relevant. Terminal — a reminder is never reopened.",
        "http_method": "POST",
        "route_pattern": "/api/v1/reminders/<reminder_id>/dismiss/",
        "view_import_path": "reminders.views.ReminderDismissView",
        "risk_level": "medium",
        "dependencies": _REQUIRES_REMINDER_READ,
        "change_summary": "Initial registration of the reminder dismiss endpoint.",
        "change_reason": _PHASE,
    },
    # 7. The reminder's history, projected from the central audit log.
    {
        **_REMINDER,
        "endpoint_key": "reminder-history",
        "permission_key": "reminders.reminder.list_history",
        "operation_type": "list",
        "display_name": "View Reminder History",
        "description": "List a reminder's chronological history — creation, reschedules, completion, or dismissal.",
        "http_method": "GET",
        "route_pattern": "/api/v1/reminders/<reminder_id>/history/",
        "view_import_path": "reminders.views.ReminderHistoryView",
        "risk_level": "low",
        "dependencies": _REQUIRES_REMINDER_READ,
        "change_summary": "Initial registration of the reminder history endpoint.",
        "change_reason": _PHASE,
    },
]
