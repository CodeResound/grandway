"""Thin views for the document_templates app.

Views receive the request, apply the interim access check (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

**Admin only, on every route including reads** — see ``access.py`` for why a
module holding no applicant data is nonetheless the strictest kind in the
project.

Five exception classes are caught here that this app does not define:
``documents.exceptions.TemplateKeyInvalidError``, raised by the imported
key/family agreement rule, and the file ledger's four upload rejections. Every
one is re-coded under a ``DOCUMENT_TEMPLATES_*`` code, because a consumer
calling a ``/document-templates/`` route should never receive a ``DOCUMENTS_*``
or ``UPLOADED_FILES_*`` code for a route it did not call.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from documents.exceptions import TemplateKeyInvalidError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from uploaded_files.exceptions import (
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
)

from document_templates import services
from document_templates.access import require_template_actor
from document_templates.constants import ErrorCode
from document_templates.exceptions import (
    ActorNotPermittedError,
    InvalidStatusTransitionError,
    SignatureNotAnImageError,
    TemplateKeyAlreadyExistsError,
    TemplateKeyImmutableError,
)
from document_templates.models import DocumentTemplate, Signatory
from document_templates.selectors import (
    filter_signatories,
    filter_templates,
    get_signatories,
    get_signatory_by_id,
    get_template_by_id,
    get_templates,
)
from document_templates.serializers import (
    DocumentTemplateSerializer,
    SignatoryCreateSerializer,
    SignatorySearchSerializer,
    SignatorySerializer,
    SignatoryUpdateSerializer,
    SignatureUploadSerializer,
    StatusChangeSerializer,
    TemplateCreateSerializer,
    TemplateSearchSerializer,
    TemplateUpdateSerializer,
)

#: Fields a template PATCH may not carry. Rejected loudly rather than dropped:
#: a client that sent `key` and got 200 back would believe every document using
#: the old slug had been renamed along with it.
IMMUTABLE_TEMPLATE_FIELDS = frozenset({"key"})
STATUS_FIELDS = frozenset({"status", "status_note"})

#: Fields a signatory PATCH may not carry beyond the status pair. Rejected
#: loudly for a sharper reason than the others: ``signature_file`` is set only
#: by the signature action, which stores bytes and re-points the link in one
#: transaction. Accepting a bare file id here would let an Admin point a
#: signatory at any file in the system — an applicant's passport included — with
#: no ownership check and no bytes ever having been uploaded for that signer.
SIGNATURE_FIELDS = frozenset({"signature_file"})


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Admin authority is required to access document templates.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_404_NOT_FOUND)


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


class TemplateActorView(APIView):
    """Base for every view in this app — one authority check, applied everywhere."""

    permission_classes = [IsAuthenticated]

    def check_actor(self, request: Request) -> Response | None:
        try:
            require_template_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        return None


class SignatoryScopedView(TemplateActorView):
    """Base for views addressing a single signatory by id."""

    def resolve(self, request: Request, signatory_id: str) -> tuple[Signatory | None, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        signatory = get_signatory_by_id(signatory_id)
        if signatory is None:
            return None, _not_found(ErrorCode.SIGNATORY_NOT_FOUND, "Signatory not found.")
        return signatory, None


class TemplateScopedView(TemplateActorView):
    """Base for views addressing a single template by id."""

    def resolve(self, request: Request, template_id: str) -> tuple[DocumentTemplate | None, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        template = get_template_by_id(template_id)
        if template is None:
            return None, _not_found(ErrorCode.TEMPLATE_NOT_FOUND, "Template not found.")
        return template, None


# ---------------------------------------------------------------------------
# Signatories
# ---------------------------------------------------------------------------


class SignatoryListCreateView(TemplateActorView):
    """GET/POST /signatories/ — the signature library, or a new signer."""

    def get(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        search = SignatorySearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_signatories(get_signatories(), search.validated_data)
        return _paginated(request, queryset, SignatorySerializer, "Signatories retrieved.")

    def post(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        serializer = SignatoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signatory = services.create_signatory(
            actor=request.user,
            data=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(
            data=SignatorySerializer(signatory).data,
            message="Signatory created.",
            http_status=status.HTTP_201_CREATED,
        )


class SignatoryDetailView(SignatoryScopedView):
    """GET/PATCH /signatories/<id>/ — read or correct one signer."""

    def get(self, request: Request, signatory_id: str) -> Response:
        signatory, err = self.resolve(request, signatory_id)
        if err:
            return err
        return success_response(data=SignatorySerializer(signatory).data, message="Signatory retrieved.")

    def patch(self, request: Request, signatory_id: str) -> Response:
        signatory, err = self.resolve(request, signatory_id)
        if err:
            return err

        submitted = set(request.data or {})

        standing = sorted(STATUS_FIELDS & submitted)
        if standing:
            return _bad_request(
                ErrorCode.STATUS_IMMUTABLE,
                "A signatory's status is changed through the status action.",
                details={field: ["This field cannot be set directly."] for field in standing},
            )

        signature = sorted(SIGNATURE_FIELDS & submitted)
        if signature:
            return _bad_request(
                ErrorCode.SIGNATURE_FILE_IMMUTABLE,
                "A signatory's signature is set by uploading one to the signature action.",
                details={field: ["This field cannot be set directly."] for field in signature},
            )

        serializer = SignatoryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_signatory(
            actor=request.user,
            signatory=signatory,
            fields=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(data=SignatorySerializer(updated).data, message="Signatory updated.")


class SignatoryStatusView(SignatoryScopedView):
    """POST /signatories/<id>/status/ — activate or retire a signer."""

    def post(self, request: Request, signatory_id: str) -> Response:
        signatory, err = self.resolve(request, signatory_id)
        if err:
            return err

        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_signatory_status(
                actor=request.user,
                signatory=signatory,
                status=serializer.validated_data["status"],
                note=serializer.validated_data.get("note", ""),
                ip_address=_client_ip(request),
            )
        except InvalidStatusTransitionError as exc:
            return _bad_request(ErrorCode.STATUS_INVALID_TRANSITION, str(exc))

        return success_response(data=SignatorySerializer(updated).data, message="Signatory status updated.")


class SignatorySignatureView(SignatoryScopedView):
    """POST /signatories/<id>/signature/ — store or replace the signature image.

    **The app's first multipart route and its first ``parser_classes``
    declaration.** Every other handler here parses JSON; a client sending JSON to
    this one gets 415 from DRF before any handler runs. The parsers are pinned
    explicitly rather than left to the project default — the two existing upload
    views in ``uploaded_files`` both do the same, and relying on an unset global
    that a future settings edit could narrow is how this breaks silently.

    Returns the **signatory**, not the file. That is what lets a client re-render
    the row from one response, and it is where ``signature_source`` lives — the
    field that says which signature actually renders.

    Four exception types this app does not define are caught and re-coded; see
    the module docstring.
    """

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, signatory_id: str) -> Response:
        signatory, err = self.resolve(request, signatory_id)
        if err:
            return err

        serializer = SignatureUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated = services.set_signatory_signature(
                actor=request.user,
                signatory=signatory,
                upload=serializer.validated_data["file"],
                notes=serializer.validated_data.get("notes", ""),
                ip_address=_client_ip(request),
            )
        except (SignatureNotAnImageError, FileTypeNotAllowedError) as exc:
            return _bad_request(ErrorCode.SIGNATURE_NOT_AN_IMAGE, str(exc), details={"file": [str(exc)]})
        except FileEmptyError as exc:
            return _bad_request(ErrorCode.SIGNATURE_FILE_EMPTY, str(exc), details={"file": [str(exc)]})
        except FileTooLargeError as exc:
            return _bad_request(ErrorCode.SIGNATURE_FILE_TOO_LARGE, str(exc), details={"file": [str(exc)]})
        except FileContentMismatchError as exc:
            return _bad_request(ErrorCode.SIGNATURE_FILE_CONTENT_MISMATCH, str(exc), details={"file": [str(exc)]})

        return success_response(
            data=SignatorySerializer(updated).data,
            message="Signature uploaded.",
            http_status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TemplateListCreateView(TemplateActorView):
    """GET/POST /templates/ — the catalogue, or a new slug."""

    def get(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        search = TemplateSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_templates(get_templates(), search.validated_data)
        return _paginated(request, queryset, DocumentTemplateSerializer, "Templates retrieved.")

    def post(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        serializer = TemplateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template = services.create_template(
                actor=request.user,
                data=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except TemplateKeyAlreadyExistsError as exc:
            return _bad_request(ErrorCode.KEY_ALREADY_EXISTS, str(exc), details={"key": [str(exc)]})
        except TemplateKeyInvalidError as exc:
            return _bad_request(ErrorCode.TEMPLATE_KEY_INVALID, str(exc), details={"key": [str(exc)]})

        return success_response(
            data=DocumentTemplateSerializer(template).data,
            message="Template registered.",
            http_status=status.HTTP_201_CREATED,
        )


class TemplateDetailView(TemplateScopedView):
    """GET/PATCH /templates/<id>/ — read or edit one catalogue row."""

    def get(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err
        return success_response(data=DocumentTemplateSerializer(template).data, message="Template retrieved.")

    def patch(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err

        submitted = set(request.data or {})
        immutable = sorted(IMMUTABLE_TEMPLATE_FIELDS & submitted)
        if immutable:
            return _bad_request(
                ErrorCode.KEY_IMMUTABLE,
                "A template's key cannot be changed after creation.",
                details={field: ["This field cannot be changed after creation."] for field in immutable},
            )
        standing = sorted(STATUS_FIELDS & submitted)
        if standing:
            return _bad_request(
                ErrorCode.STATUS_IMMUTABLE,
                "A template's status is changed through the status action.",
                details={field: ["This field cannot be set directly."] for field in standing},
            )

        serializer = TemplateUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_template(
                actor=request.user,
                template=template,
                fields=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except TemplateKeyImmutableError as exc:
            return _bad_request(ErrorCode.KEY_IMMUTABLE, str(exc), details={"key": [str(exc)]})
        except TemplateKeyInvalidError as exc:
            return _bad_request(ErrorCode.TEMPLATE_KEY_INVALID, str(exc), details={"family": [str(exc)]})

        return success_response(data=DocumentTemplateSerializer(updated).data, message="Template updated.")


class TemplateStatusView(TemplateScopedView):
    """POST /templates/<id>/status/ — offer a template, or retire it."""

    def post(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err

        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_template_status(
                actor=request.user,
                template=template,
                status=serializer.validated_data["status"],
                note=serializer.validated_data.get("note", ""),
                ip_address=_client_ip(request),
            )
        except InvalidStatusTransitionError as exc:
            return _bad_request(ErrorCode.STATUS_INVALID_TRANSITION, str(exc))

        return success_response(data=DocumentTemplateSerializer(updated).data, message="Template status updated.")
