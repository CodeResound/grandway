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
    list_display = ("full_name_np", "full_name_en", "status", "creation_source", "created_by", "created_at")
    list_filter = ("status", "creation_source", "gender")
    search_fields = ("full_name_np", "full_name_en", "full_name_romanized", "email")
    readonly_fields = (
        "id",
        "full_name_romanized",
        "creation_source",
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
