"""Core Policy Engine endpoint declarations for the dashboards app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**Every endpoint here declares a forward dependency on the list permission it
links into**, and that is the substantive part of this file rather than
boilerplate. A dashboard section is a set of links: a blocked-item count that a
user cannot open is exactly what ``concepts/dashboards.txt`` asks this app not
to build. Encoding the dependency means the policy engine knows that granting
someone the blockers section without ``checklists.checklist.list`` produces a
screen of dead ends, and §9's dependency enforcement will say so when the
permissions app is eventually wired into the request path.

``model_key`` names the *section*, not a table. This app owns no tables at all;
the sections are the resources it exposes, and ``app.model.action`` needs each
to be addressable.
"""

from typing import Any

_BASE: dict[str, Any] = {
    "app_key": "dashboards",
    "app_display_name": "Dashboards",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "operations_dashboard",
    "category_display_name": "Operations Dashboard",
    "http_method": "GET",
    "operation_type": "read",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_LOGIN = _dep("authenticate.session.login", "A session must be established by login before this endpoint is usable.")

_PHASE = "dashboards app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # 1. The alert strip. Every figure here is duplicated in a fuller section
    #    below, so it depends on nothing beyond a session — a user who can see
    #    only this sees counts they cannot open, which is a degraded but honest
    #    view rather than a broken one.
    {
        **_BASE,
        "model_key": "summary",
        "model_display_name": "Dashboard Summary",
        "endpoint_key": "dashboard-summary",
        "permission_key": "dashboards.summary.read",
        "display_name": "View Dashboard Summary",
        "description": (
            "Top-line alert counts and volumes across leads, applicants, journeys, offers, "
            "checklists, and files. The strip a user reads first."
        ),
        "route_pattern": "/api/v1/dashboard/summary/",
        "view_import_path": "dashboards.views.DashboardSummaryView",
        "risk_level": "low",
        "dependencies": [_LOGIN],
        "change_summary": "Initial registration of the dashboard summary endpoint.",
        "change_reason": _PHASE,
    },
    # 2. Today's work — the section the app exists for. Depends on every list it
    #    hands a user off to, because every row is a link.
    {
        **_BASE,
        "model_key": "today",
        "model_display_name": "Today's Work",
        "endpoint_key": "dashboard-today",
        "permission_key": "dashboards.today.read",
        "display_name": "View Today's Work",
        "description": (
            "Overdue and due-soon work: checklist items, offers awaiting a response, files "
            "awaiting verification, stalled documents, and leads nobody has followed up."
        ),
        "route_pattern": "/api/v1/dashboard/today/",
        "view_import_path": "dashboards.views.DashboardTodayView",
        "risk_level": "low",
        "dependencies": [
            _LOGIN,
            _dep("checklists.checklist.list", "Every overdue and due-soon row opens the applicant's checklist."),
            _dep("offers.offer.list", "Offers awaiting a response open the offer record."),
            _dep("uploaded_files.file.list", "Files awaiting verification open the file ledger."),
            _dep("leads.lead.list", "Stale leads open the lead record, and the counts are owner-scoped by it."),
        ],
        "change_summary": "Initial registration of the today's-work endpoint.",
        "change_reason": _PHASE,
    },
    # 3. Pipeline health. Each count links into the owning app's list, filtered
    #    to the same stage.
    {
        **_BASE,
        "model_key": "pipeline",
        "model_display_name": "Pipeline Health",
        "endpoint_key": "dashboard-pipeline",
        "permission_key": "dashboards.pipeline.read",
        "display_name": "View Pipeline Health",
        "description": (
            "Stage and status counts across leads, applicants, journeys, offers, checklists, "
            "documents, and file verification. Every bucket is zero-filled."
        ),
        "route_pattern": "/api/v1/dashboard/pipeline/",
        "view_import_path": "dashboards.views.DashboardPipelineView",
        "risk_level": "low",
        "dependencies": [
            _LOGIN,
            _dep("leads.lead.list", "The lead funnel counts are owner-scoped through the lead list."),
            _dep("applicants.applicant.list", "Applicant status counts drill into the applicant list."),
            _dep("applicant_journeys.journey.list", "Journey stage counts drill into the journey list."),
            _dep("offers.offer.list", "Offer status counts drill into the offer list."),
            _dep("checklists.checklist.list", "Checklist status counts drill into the checklist list."),
        ],
        "change_summary": "Initial registration of the pipeline-health endpoint.",
        "change_reason": _PHASE,
    },
    # 4. Blockers. Medium risk, not low: it names specific applicants who are
    #    stuck, which is a sharper disclosure than an aggregate count.
    {
        **_BASE,
        "model_key": "blockers",
        "model_display_name": "Blockers and Risk",
        "endpoint_key": "dashboard-blockers",
        "permission_key": "dashboards.blockers.read",
        "display_name": "View Blockers and Risk",
        "description": (
            "Work that is stuck: blocked checklist items, journeys whose destination has no "
            "authored requirements, expiring passports, offers past their deadline, and rejected files."
        ),
        "route_pattern": "/api/v1/dashboard/blockers/",
        "view_import_path": "dashboards.views.DashboardBlockersView",
        "risk_level": "medium",
        "dependencies": [
            _LOGIN,
            _dep("checklists.checklist.list", "Blocked items and unserved journeys open the checklist workspace."),
            _dep(
                "checklists.template.list", "A journey with no checklist is fixed by authoring the country template."
            ),
            _dep("applicants.applicant.read", "An expiring passport row opens the applicant's file."),
            _dep("offers.offer.list", "Overdue offers open the offer record."),
            _dep("uploaded_files.file.list", "Rejected files open the file ledger."),
        ],
        "change_summary": "Initial registration of the blockers endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Workload. Medium risk: it discloses how much work each named staff
    #    member is carrying, which is about people rather than records.
    {
        **_BASE,
        "model_key": "workload",
        "model_display_name": "Workload by Owner",
        "endpoint_key": "dashboard-workload",
        "permission_key": "dashboards.workload.read",
        "display_name": "View Workload by Owner",
        "description": (
            "Open leads, checklist items, and offers awaiting a response, per staff member. "
            "A Lead Manager sees only their own row for leads; an Admin sees the distribution."
        ),
        "route_pattern": "/api/v1/dashboard/workload/",
        "view_import_path": "dashboards.views.DashboardWorkloadView",
        "risk_level": "medium",
        "dependencies": [
            _LOGIN,
            _dep("leads.lead.list", "The lead workload rows are owner-scoped through the lead list."),
            _dep("checklists.checklist.list", "A workload row opens that person's assigned checklist items."),
            _dep("offers.offer.list", "A workload row opens the offers that person recorded."),
        ],
        "change_summary": "Initial registration of the workload endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Conversion. Medium risk: intake performance by channel is commercially
    #    sensitive in a way a stage count is not.
    {
        **_BASE,
        "model_key": "conversion",
        "model_display_name": "Source and Conversion",
        "endpoint_key": "dashboard-conversion",
        "permission_key": "dashboards.conversion.read",
        "display_name": "View Source and Conversion",
        "description": (
            "Intake mix by lead source, and the lead-to-applicant, applicant-to-journey, "
            "journey-to-offer, and offer-acceptance rates for the window."
        ),
        "route_pattern": "/api/v1/dashboard/conversion/",
        "view_import_path": "dashboards.views.DashboardConversionView",
        "risk_level": "medium",
        "dependencies": [
            _LOGIN,
            _dep("leads.lead.list", "Source mix and the lead-to-applicant rate are owner-scoped through the leads."),
            _dep("leads.source.list", "The source breakdown is meaningless without the source catalogue."),
            _dep("applicants.applicant.list", "The applicant-to-journey rate counts applicants."),
            _dep("applicant_journeys.journey.list", "The journey-to-offer rate counts journeys."),
            _dep("offers.offer.list", "The acceptance rate counts decided offers."),
        ],
        "change_summary": "Initial registration of the conversion endpoint.",
        "change_reason": _PHASE,
    },
    # 7. Final outcomes.
    {
        **_BASE,
        "model_key": "outcomes",
        "model_display_name": "Final Outcomes",
        "endpoint_key": "dashboard-outcomes",
        "permission_key": "dashboards.outcomes.read",
        "display_name": "View Final Outcomes",
        "description": (
            "How work ended over the window: journey outcomes, offer decisions, and archived "
            "or closed volumes. Windowed on when each thing ended, not when it started."
        ),
        "route_pattern": "/api/v1/dashboard/outcomes/",
        "view_import_path": "dashboards.views.DashboardOutcomesView",
        "risk_level": "low",
        "dependencies": [
            _LOGIN,
            _dep("applicant_journeys.journey.list", "Journey outcomes drill into the journey list."),
            _dep("offers.offer.list", "Offer decisions drill into the offer list."),
        ],
        "change_summary": "Initial registration of the outcomes endpoint.",
        "change_reason": _PHASE,
    },
    # 8. Recent activity — a paginated projection of the central audit log,
    #    which is why this is the one ``list`` operation in the app.
    {
        **_BASE,
        "model_key": "activity",
        "model_display_name": "Recent Activity",
        "endpoint_key": "dashboard-activity",
        "permission_key": "dashboards.activity.list",
        "operation_type": "list",
        "display_name": "View Recent Activity",
        "description": (
            "The recent-activity feed, projected from the central audit log. Paginated, newest first, "
            "and not narrowed by the caller's authority — the audit log is not owner-scoped."
        ),
        "route_pattern": "/api/v1/dashboard/activity/",
        "view_import_path": "dashboards.views.DashboardActivityView",
        "risk_level": "low",
        "dependencies": [
            _LOGIN,
            _dep("audit.event.list", "This feed is a projection of the audit event log and nothing else."),
        ],
        "change_summary": "Initial registration of the recent-activity endpoint.",
        "change_reason": _PHASE,
    },
]
