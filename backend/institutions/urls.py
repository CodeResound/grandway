"""URL routes for the institutions app (mounted at /api/v1/catalogue/).

Mounted at ``catalogue/`` rather than ``institutions/`` because the app owns
five resources and "institutions" is only one of them — ``/api/v1/
institutions/institutions/`` would be the alternative. The app name stays
``institutions``, which is what ``concepts/project_overview.txt`` calls it.
"""

from django.urls import path

from institutions.views import (
    CampusDetailView,
    CampusListCreateView,
    CountryDetailView,
    CountryListCreateView,
    FieldDetailView,
    FieldListCreateView,
    InstitutionDetailView,
    InstitutionListCreateView,
    ProgramDetailView,
    ProgramListCreateView,
)

app_name = "institutions"

urlpatterns = [
    path("fields/", FieldListCreateView.as_view(), name="field-list"),
    path("fields/<uuid:field_id>/", FieldDetailView.as_view(), name="field-detail"),
    path("countries/", CountryListCreateView.as_view(), name="country-list"),
    path("countries/<uuid:country_id>/", CountryDetailView.as_view(), name="country-detail"),
    path("institutions/", InstitutionListCreateView.as_view(), name="institution-list"),
    path("institutions/<uuid:institution_id>/", InstitutionDetailView.as_view(), name="institution-detail"),
    path(
        "institutions/<uuid:institution_id>/campuses/",
        CampusListCreateView.as_view(),
        name="campus-list",
    ),
    path("campuses/<uuid:campus_id>/", CampusDetailView.as_view(), name="campus-detail"),
    path("programs/", ProgramListCreateView.as_view(), name="program-list"),
    path("programs/<uuid:program_id>/", ProgramDetailView.as_view(), name="program-detail"),
]
