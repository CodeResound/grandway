"""URL routes for the applicant_journeys app (mounted at /api/v1/journeys/)."""

from django.urls import path

from applicant_journeys.views import (
    JourneyCloseView,
    JourneyDeferView,
    JourneyDetailView,
    JourneyHistoryView,
    JourneyListCreateView,
    JourneyReopenView,
    JourneyStageView,
)

app_name = "applicant_journeys"

urlpatterns = [
    path("", JourneyListCreateView.as_view(), name="journey-list"),
    path("<uuid:journey_id>/", JourneyDetailView.as_view(), name="journey-detail"),
    path("<uuid:journey_id>/stage/", JourneyStageView.as_view(), name="journey-stage"),
    path("<uuid:journey_id>/defer/", JourneyDeferView.as_view(), name="journey-defer"),
    path("<uuid:journey_id>/close/", JourneyCloseView.as_view(), name="journey-close"),
    path("<uuid:journey_id>/reopen/", JourneyReopenView.as_view(), name="journey-reopen"),
    path("<uuid:journey_id>/history/", JourneyHistoryView.as_view(), name="journey-history"),
]
