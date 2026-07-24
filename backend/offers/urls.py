"""URL routes for the offers app (mounted at /api/v1/offers/).

Conditions are nested under their offer to list and create, then addressed flat
by their own id to update — the same shape ``institutions`` uses for campuses.
Creating a condition needs the parent in the URL; changing one does not, and
threading the offer id through would only invite the two to disagree.
"""

from django.urls import path

from offers.views import (
    ConditionDetailView,
    ConditionListCreateView,
    ConditionStatusView,
    OfferDecisionView,
    OfferDetailView,
    OfferHistoryView,
    OfferIssueView,
    OfferListCreateView,
)

app_name = "offers"

urlpatterns = [
    path("", OfferListCreateView.as_view(), name="offer-list"),
    # Declared before the ``<uuid:offer_id>/`` routes so that the literal
    # segment is never shadowed by the id pattern.
    path("conditions/<uuid:condition_id>/", ConditionDetailView.as_view(), name="condition-detail"),
    path("conditions/<uuid:condition_id>/status/", ConditionStatusView.as_view(), name="condition-status"),
    path("<uuid:offer_id>/", OfferDetailView.as_view(), name="offer-detail"),
    path("<uuid:offer_id>/issue/", OfferIssueView.as_view(), name="offer-issue"),
    path("<uuid:offer_id>/decision/", OfferDecisionView.as_view(), name="offer-decision"),
    path("<uuid:offer_id>/history/", OfferHistoryView.as_view(), name="offer-history"),
    path("<uuid:offer_id>/conditions/", ConditionListCreateView.as_view(), name="condition-list"),
]
