"""Django admin registration for the offers app (§13).

Read-heavy on purpose. The snapshot, the decision stamp, and the resolution
stamp are all read-only here: they are written by the service layer, which is
also what appends the audit event. An admin edit that bypassed the service
would change the record and leave no trace of who did it.
"""

from django.contrib import admin

from offers.models import Offer, OfferCondition

_SNAPSHOT_FIELDS = (
    "institution_name",
    "campus_name",
    "program_title",
    "country_name",
    "qualification_level",
    "intake_label",
    "reference_source",
)


class OfferConditionInline(admin.TabularInline):
    model = OfferCondition
    extra = 0
    fields = ("condition_type", "description", "status", "due_date", "resolved_at", "resolved_by")
    readonly_fields = ("resolved_at", "resolved_by")


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        "program_title",
        "institution_name",
        "intake_label",
        "status",
        "offer_type",
        "response_deadline",
        "created_at",
    )
    list_filter = ("status", "offer_type", "reference_source", "qualification_level")
    search_fields = ("institution_name", "program_title", "offer_reference", "intake_label")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "decided_at",
        "decided_by",
        *_SNAPSHOT_FIELDS,
    )
    autocomplete_fields = ("journey",)
    inlines = [OfferConditionInline]
    date_hierarchy = "created_at"


@admin.register(OfferCondition)
class OfferConditionAdmin(admin.ModelAdmin):
    list_display = ("condition_type", "offer", "status", "due_date", "resolved_at")
    list_filter = ("status", "condition_type")
    search_fields = ("description", "offer__program_title", "offer__institution_name")
    readonly_fields = ("id", "created_at", "updated_at", "resolved_at", "resolved_by")
