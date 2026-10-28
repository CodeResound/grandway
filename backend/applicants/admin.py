"""Django admin registration for the applicants app.

Creation provenance and the derived romanized name are read-only: they are set
by the service layer, and admin must never bypass it (§13).
"""

from __future__ import annotations

from django.contrib import admin

from applicants.models import (
    Applicant,
    ApplicantAddress,
    ApplicantContactNumber,
    ApplicantNote,
    EmergencyContact,
    FamilyMember,
    PassportDetail,
)


class ApplicantContactNumberInline(admin.TabularInline):
    model = ApplicantContactNumber
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


class ApplicantAddressInline(admin.StackedInline):
    model = ApplicantAddress
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


class PassportDetailInline(admin.StackedInline):
    model = PassportDetail
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


class FamilyMemberInline(admin.TabularInline):
    model = FamilyMember
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "status", "creation_source", "created_by", "created_at")
    list_filter = ("status", "creation_source", "gender")
    search_fields = ("full_name", "email")
    readonly_fields = (
        "id",
        "creation_source",
        "status_before_archive",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = [
        ApplicantContactNumberInline,
        ApplicantAddressInline,
        PassportDetailInline,
        FamilyMemberInline,
        EmergencyContactInline,
    ]
    ordering = ("-created_at",)


@admin.register(ApplicantNote)
class ApplicantNoteAdmin(admin.ModelAdmin):
    """Read-only here: notes are edited and soft-deleted through the API, which audits it."""

    list_display = ("applicant", "category", "author", "noted_at", "deleted_at")
    list_filter = ("category",)
    search_fields = ("applicant__full_name", "body")
    readonly_fields = (
        "id",
        "applicant",
        "category",
        "body",
        "noted_at",
        "author",
        "updated_by",
        "deleted_at",
        "deleted_by",
        "source_lead_id",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object | None = None) -> bool:
        return False
