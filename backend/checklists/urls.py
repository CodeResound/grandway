"""URL routes for the checklists app (mounted at /api/v1/checklists/).

Two resources under one mount. Templates sit at ``templates/`` rather than in
their own app-level namespace because a template is not independently
meaningful — it exists to become somebody's checklist, and a client that reads
one is on its way to reading the other.

The per-applicant panel is this list filtered, not a nested route:
``GET /api/v1/checklists/?applicant=<id>`` rather than
``/api/v1/applicants/<id>/checklists/``. Nesting would put a checklists route
inside another app's URL namespace and make that app appear to own checklist
access.
"""

from django.urls import path

from checklists.views import (
    ChecklistActivateView,
    ChecklistArchiveView,
    ChecklistCompleteView,
    ChecklistDetailView,
    ChecklistItemCreateView,
    ChecklistItemDetailView,
    ChecklistItemStatusView,
    ChecklistListCreateView,
    ChecklistReopenView,
    ChecklistRestoreView,
    TemplateDetailView,
    TemplateItemCreateView,
    TemplateItemDetailView,
    TemplateListCreateView,
)

app_name = "checklists"

urlpatterns = [
    # Templates — the country requirement lists (Admin authors, both read).
    path("templates/", TemplateListCreateView.as_view(), name="template-list"),
    path("templates/<uuid:template_id>/", TemplateDetailView.as_view(), name="template-detail"),
    path("templates/<uuid:template_id>/items/", TemplateItemCreateView.as_view(), name="template-item-create"),
    path(
        "templates/<uuid:template_id>/items/<uuid:item_id>/",
        TemplateItemDetailView.as_view(),
        name="template-item-detail",
    ),
    # Checklists — one applicant's copy.
    path("", ChecklistListCreateView.as_view(), name="checklist-list"),
    path("<uuid:checklist_id>/", ChecklistDetailView.as_view(), name="checklist-detail"),
    path("<uuid:checklist_id>/activate/", ChecklistActivateView.as_view(), name="checklist-activate"),
    path("<uuid:checklist_id>/complete/", ChecklistCompleteView.as_view(), name="checklist-complete"),
    path("<uuid:checklist_id>/reopen/", ChecklistReopenView.as_view(), name="checklist-reopen"),
    path("<uuid:checklist_id>/archive/", ChecklistArchiveView.as_view(), name="checklist-archive"),
    path("<uuid:checklist_id>/restore/", ChecklistRestoreView.as_view(), name="checklist-restore"),
    path("<uuid:checklist_id>/items/", ChecklistItemCreateView.as_view(), name="checklist-item-create"),
    path(
        "<uuid:checklist_id>/items/<uuid:item_id>/",
        ChecklistItemDetailView.as_view(),
        name="checklist-item-detail",
    ),
    path(
        "<uuid:checklist_id>/items/<uuid:item_id>/status/",
        ChecklistItemStatusView.as_view(),
        name="checklist-item-status",
    ),
]
