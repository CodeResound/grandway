"""Django admin registration for the institutions app (§13).

Operations staff inspect the catalogue here when a search result looks wrong.
No model exposes a delete action beyond Django's default, and every child FK
is ``PROTECT``, so the app-wide "nothing is deleted" rule holds in the admin
too.
"""

from django.contrib import admin

from institutions.models import Campus, Country, Field, Institution, Program


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ["name_en", "code", "is_active", "display_order", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "name_en", "name_np"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name_en", "code", "availability_status", "display_order", "updated_at"]
    list_filter = ["availability_status"]
    search_fields = ["code", "name_en", "name_np"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ["name_en", "country", "institution_type", "availability_status", "updated_at"]
    list_filter = ["availability_status", "institution_type", "country"]
    search_fields = ["name_en", "name_np", "common_name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["country"]


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ["name_en", "institution", "city", "availability_status", "updated_at"]
    list_filter = ["availability_status"]
    search_fields = ["name_en", "city", "institution__name_en"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["institution"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "institution",
        "campus",
        "qualification_level",
        "field",
        "availability_status",
        "updated_at",
    ]
    list_filter = ["availability_status", "qualification_level", "scholarship_available", "field"]
    search_fields = ["title", "institution__name_en"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["institution", "campus", "field"]
