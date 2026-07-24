"""Django admin registration for the applicant_journeys app.

Lifecycle state is read-only: it is set by the service layer, and admin must
never bypass it (§13).
"""

from __future__ import annotations

from django.contrib import admin

from applicant_journeys.models import ApplicantJourney


@admin.register(ApplicantJourney)
class ApplicantJourneyAdmin(admin.ModelAdmin):
    list_display = (
        "applicant",
        "target_country_ref",
        "target_country",
        "study_level",
        "preferred_intake",
        "stage",
        "outcome",
    )
    list_filter = ("stage", "outcome", "study_level", "creation_source", "target_country_ref")
    list_select_related = ("applicant", "target_country_ref")
    search_fields = (
        "applicant__full_name",
        "target_country",
        "target_country_ref__name",
        "target_institution_name",
        "field_of_study",
    )
    readonly_fields = (
        "id",
        "applicant",
        "creation_source",
        "created_by",
        "outcome",
        "closure_reason",
        "closed_at",
        "closed_by",
        "deferred_at",
        "deferred_to_intake",
        "deferment_reason",
        "deferred_by",
        "stage_before_terminal",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
