"""Thin views for the institutions app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

The access split is the app's defining shape and is applied by the base
classes below: **every Admin and Lead Manager may read; only an Admin may
write.** See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from institutions import services
from institutions.access import require_admin, require_catalogue_reader
from institutions.constants import ErrorCode
from institutions.exceptions import (
    ActorNotPermittedError,
    AvailabilityNoteRequiredError,
    CampusInstitutionMismatchError,
    TuitionIncompleteError,
)
from institutions.selectors import (
    filter_campuses,
    filter_countries,
    filter_fields,
    filter_institutions,
    filter_programs,
    get_campus_by_id,
    get_campuses_for_institution,
    get_countries,
    get_country_by_id,
    get_field_by_id,
    get_fields,
    get_institution_by_id,
    get_institutions,
    get_program_by_id,
    get_programs,
)
from institutions.serializers import (
    CampusCreateSerializer,
    CampusSearchSerializer,
    CampusSerializer,
    CampusUpdateSerializer,
    CountryCreateSerializer,
    CountrySearchSerializer,
    CountrySerializer,
    CountryUpdateSerializer,
    FieldCreateSerializer,
    FieldSearchSerializer,
    FieldSerializer,
    FieldUpdateSerializer,
    InstitutionCreateSerializer,
    InstitutionSearchSerializer,
    InstitutionSerializer,
    InstitutionUpdateSerializer,
    ProgramCreateSerializer,
    ProgramDetailSerializer,
    ProgramListSerializer,
    ProgramSearchSerializer,
    ProgramUpdateSerializer,
)


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden(message: str = "Your authority level may not perform this action.") -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        message,
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_404_NOT_FOUND)


def _conflict(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_409_CONFLICT)


def _bad_request(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_400_BAD_REQUEST)


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


def _validated_filters(serializer_class: Any, request: Request) -> dict[str, Any]:
    """Validate the query string, or raise DRF's ``ValidationError``.

    Rejecting an unparseable filter is deliberate: silently ignoring
    ``?tuition_max=cheap`` would return the whole catalogue and read as a
    result set rather than a mistake.
    """
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class CatalogueView(APIView):
    """Base for every catalogue view: reads are shared, writes are Admin-only."""

    permission_classes = [IsAuthenticated]

    def check_read(self, request: Request) -> Response | None:
        try:
            require_catalogue_reader(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))
        return None

    def check_write(self, request: Request) -> Response | None:
        try:
            require_admin(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))
        return None


def _translate_domain_error(exc: Exception) -> Response | None:
    """Map a service's domain exception onto the standard error envelope."""
    if isinstance(exc, AvailabilityNoteRequiredError):
        return _bad_request(ErrorCode.AVAILABILITY_NOTE_REQUIRED, str(exc))
    if isinstance(exc, CampusInstitutionMismatchError):
        return _bad_request(ErrorCode.CAMPUS_INSTITUTION_MISMATCH, str(exc))
    if isinstance(exc, TuitionIncompleteError):
        return _bad_request(ErrorCode.TUITION_INCOMPLETE, str(exc))
    return None


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


class FieldListCreateView(CatalogueView):
    """GET/POST /api/v1/catalogue/fields/ — the study-area reference table."""

    def get(self, request: Request) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        filters = _validated_filters(FieldSearchSerializer, request)
        queryset = filter_fields(get_fields(), filters)
        return _paginated(request, queryset, FieldSerializer, "Study fields retrieved.")

    def post(self, request: Request) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        serializer = FieldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            field = services.create_field(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except IntegrityError:
            return _conflict(ErrorCode.CODE_DUPLICATE, "A study field with this code already exists.")
        return success_response(
            data=FieldSerializer(field).data,
            message="Study field created.",
            http_status=status.HTTP_201_CREATED,
        )


class FieldDetailView(CatalogueView):
    """GET/PATCH /api/v1/catalogue/fields/<field_id>/."""

    def get(self, request: Request, field_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        field = get_field_by_id(field_id)
        if field is None:
            return _not_found(ErrorCode.FIELD_NOT_FOUND, "Study field not found.")
        return success_response(data=FieldSerializer(field).data, message="Study field retrieved.")

    def patch(self, request: Request, field_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        field = get_field_by_id(field_id)
        if field is None:
            return _not_found(ErrorCode.FIELD_NOT_FOUND, "Study field not found.")
        serializer = FieldUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        field = services.update_field(
            actor=request.user,
            field=field,
            fields=serializer.validated_data,
            ip_address=_client_ip(request),
        )
        return success_response(data=FieldSerializer(field).data, message="Study field updated.")


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------


class CountryListCreateView(CatalogueView):
    """GET/POST /api/v1/catalogue/countries/."""

    def get(self, request: Request) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        filters = _validated_filters(CountrySearchSerializer, request)
        queryset = filter_countries(get_countries(), filters)
        return _paginated(request, queryset, CountrySerializer, "Countries retrieved.")

    def post(self, request: Request) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        serializer = CountryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            country = services.create_country(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        except IntegrityError:
            return _conflict(ErrorCode.CODE_DUPLICATE, "A country with this code already exists.")
        return success_response(
            data=CountrySerializer(country).data,
            message="Country created.",
            http_status=status.HTTP_201_CREATED,
        )


class CountryDetailView(CatalogueView):
    """GET/PATCH /api/v1/catalogue/countries/<country_id>/."""

    def get(self, request: Request, country_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        country = get_country_by_id(country_id)
        if country is None:
            return _not_found(ErrorCode.COUNTRY_NOT_FOUND, "Country not found.")
        return success_response(data=CountrySerializer(country).data, message="Country retrieved.")

    def patch(self, request: Request, country_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        country = get_country_by_id(country_id)
        if country is None:
            return _not_found(ErrorCode.COUNTRY_NOT_FOUND, "Country not found.")
        serializer = CountryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            country = services.update_country(
                actor=request.user,
                country=country,
                fields=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        return success_response(data=CountrySerializer(country).data, message="Country updated.")


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


class InstitutionListCreateView(CatalogueView):
    """GET/POST /api/v1/catalogue/institutions/."""

    def get(self, request: Request) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        filters = _validated_filters(InstitutionSearchSerializer, request)
        queryset = filter_institutions(get_institutions(), filters)
        return _paginated(request, queryset, InstitutionSerializer, "Institutions retrieved.")

    def post(self, request: Request) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        serializer = InstitutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            institution = services.create_institution(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        return success_response(
            data=InstitutionSerializer(institution).data,
            message="Institution created.",
            http_status=status.HTTP_201_CREATED,
        )


class InstitutionDetailView(CatalogueView):
    """GET/PATCH /api/v1/catalogue/institutions/<institution_id>/."""

    def get(self, request: Request, institution_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        institution = get_institution_by_id(institution_id)
        if institution is None:
            return _not_found(ErrorCode.INSTITUTION_NOT_FOUND, "Institution not found.")
        return success_response(data=InstitutionSerializer(institution).data, message="Institution retrieved.")

    def patch(self, request: Request, institution_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        institution = get_institution_by_id(institution_id)
        if institution is None:
            return _not_found(ErrorCode.INSTITUTION_NOT_FOUND, "Institution not found.")
        serializer = InstitutionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            institution = services.update_institution(
                actor=request.user,
                institution=institution,
                fields=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        return success_response(data=InstitutionSerializer(institution).data, message="Institution updated.")


# ---------------------------------------------------------------------------
# Campus
# ---------------------------------------------------------------------------


class CampusListCreateView(CatalogueView):
    """GET/POST /api/v1/catalogue/institutions/<institution_id>/campuses/.

    Nested under the institution because a campus is created *under* a
    provider and never moves between providers — the parent belongs in the
    URL, not the body.
    """

    def get(self, request: Request, institution_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        if get_institution_by_id(institution_id) is None:
            return _not_found(ErrorCode.INSTITUTION_NOT_FOUND, "Institution not found.")
        filters = _validated_filters(CampusSearchSerializer, request)
        queryset = filter_campuses(get_campuses_for_institution(institution_id), filters)
        return _paginated(request, queryset, CampusSerializer, "Campuses retrieved.")

    def post(self, request: Request, institution_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        institution = get_institution_by_id(institution_id)
        if institution is None:
            return _not_found(ErrorCode.INSTITUTION_NOT_FOUND, "Institution not found.")
        serializer = CampusCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            campus = services.create_campus(
                actor=request.user,
                institution=institution,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        except IntegrityError:
            return _conflict(
                ErrorCode.CAMPUS_DUPLICATE,
                "This institution already has a campus with that name.",
            )
        return success_response(
            data=CampusSerializer(campus).data,
            message="Campus created.",
            http_status=status.HTTP_201_CREATED,
        )


class CampusDetailView(CatalogueView):
    """GET/PATCH /api/v1/catalogue/campuses/<campus_id>/.

    Addressed directly rather than under its institution: the institution is
    immutable, so the nesting would carry no information a client does not
    already have from the campus id.
    """

    def get(self, request: Request, campus_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        campus = get_campus_by_id(campus_id)
        if campus is None:
            return _not_found(ErrorCode.CAMPUS_NOT_FOUND, "Campus not found.")
        return success_response(data=CampusSerializer(campus).data, message="Campus retrieved.")

    def patch(self, request: Request, campus_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        campus = get_campus_by_id(campus_id)
        if campus is None:
            return _not_found(ErrorCode.CAMPUS_NOT_FOUND, "Campus not found.")
        serializer = CampusUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            campus = services.update_campus(
                actor=request.user,
                campus=campus,
                fields=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except AvailabilityNoteRequiredError as exc:
            return _translate_domain_error(exc)
        except IntegrityError:
            return _conflict(
                ErrorCode.CAMPUS_DUPLICATE,
                "This institution already has a campus with that name.",
            )
        return success_response(data=CampusSerializer(campus).data, message="Campus updated.")


# ---------------------------------------------------------------------------
# Program — the shortlisting search
# ---------------------------------------------------------------------------


class ProgramListCreateView(CatalogueView):
    """GET/POST /api/v1/catalogue/programs/.

    The GET is the concept's "Program Search / Shortlist" screen. It defaults
    to usable records only — a search that silently offers a withdrawn program
    is worse than one that returns nothing.
    """

    def get(self, request: Request) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        filters = _validated_filters(ProgramSearchSerializer, request)
        queryset = filter_programs(get_programs(), filters)
        return _paginated(request, queryset, ProgramListSerializer, "Programs retrieved.")

    def post(self, request: Request) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        serializer = ProgramCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            program = services.create_program(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except (
            AvailabilityNoteRequiredError,
            CampusInstitutionMismatchError,
            TuitionIncompleteError,
        ) as exc:
            return _translate_domain_error(exc)
        return success_response(
            data=ProgramDetailSerializer(program).data,
            message="Program created.",
            http_status=status.HTTP_201_CREATED,
        )


class ProgramDetailView(CatalogueView):
    """GET/PATCH /api/v1/catalogue/programs/<program_id>/."""

    def get(self, request: Request, program_id: str) -> Response:
        denied = self.check_read(request)
        if denied:
            return denied
        program = get_program_by_id(program_id)
        if program is None:
            return _not_found(ErrorCode.PROGRAM_NOT_FOUND, "Program not found.")
        return success_response(data=ProgramDetailSerializer(program).data, message="Program retrieved.")

    def patch(self, request: Request, program_id: str) -> Response:
        denied = self.check_write(request)
        if denied:
            return denied
        program = get_program_by_id(program_id)
        if program is None:
            return _not_found(ErrorCode.PROGRAM_NOT_FOUND, "Program not found.")
        serializer = ProgramUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            program = services.update_program(
                actor=request.user,
                program=program,
                fields=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except (
            AvailabilityNoteRequiredError,
            CampusInstitutionMismatchError,
            TuitionIncompleteError,
        ) as exc:
            return _translate_domain_error(exc)
        return success_response(data=ProgramDetailSerializer(program).data, message="Program updated.")
