"""URL routes for the leads app (mounted at /api/v1/leads/)."""

from django.urls import path

from leads.views import (
    LeadConvertView,
    LeadDetailView,
    LeadFollowUpView,
    LeadHistoryView,
    LeadListCreateView,
    LeadMarkLostView,
    LeadNoteListCreateView,
    LeadReopenView,
    LeadSourceDetailView,
    LeadSourceListCreateView,
    LeadStageView,
    LossReasonDetailView,
    LossReasonListCreateView,
)

app_name = "leads"

urlpatterns = [
    # Reference configuration — declared before the lead detail routes so the
    # literal prefixes are unambiguous to a reader (the uuid converter already
    # keeps them from colliding).
    path("sources/", LeadSourceListCreateView.as_view(), name="source-list"),
    path("sources/<uuid:source_id>/", LeadSourceDetailView.as_view(), name="source-detail"),
    path("loss-reasons/", LossReasonListCreateView.as_view(), name="loss-reason-list"),
    path("loss-reasons/<uuid:reason_id>/", LossReasonDetailView.as_view(), name="loss-reason-detail"),
    # Leads
    path("", LeadListCreateView.as_view(), name="lead-list"),
    path("<uuid:lead_id>/", LeadDetailView.as_view(), name="lead-detail"),
    path("<uuid:lead_id>/stage/", LeadStageView.as_view(), name="lead-stage"),
    path("<uuid:lead_id>/follow-up/", LeadFollowUpView.as_view(), name="lead-follow-up"),
    path("<uuid:lead_id>/lost/", LeadMarkLostView.as_view(), name="lead-lost"),
    path("<uuid:lead_id>/reopen/", LeadReopenView.as_view(), name="lead-reopen"),
    path("<uuid:lead_id>/convert/", LeadConvertView.as_view(), name="lead-convert"),
    path("<uuid:lead_id>/notes/", LeadNoteListCreateView.as_view(), name="lead-note-list"),
    path("<uuid:lead_id>/history/", LeadHistoryView.as_view(), name="lead-history"),
]
