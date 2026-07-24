"""Thin views for the documents app.

Views receive the request, apply the interim access check (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

**Admin only, on every route including reads.** See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from typing import Any

from applicants.selectors import get_applicant_by_id
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from documents import services
from documents.access import require_document_actor
from documents.constants import ErrorCode
from documents.exceptions import (
    ActorNotPermittedError,
    ArchiveReasonRequiredError,
    ContentInvalidError,
    ContentTooLargeError,
    DocumentAlreadyArchivedError,
    DocumentNotArchivedError,
    DocumentNotEditableError,
    InvalidStatusTransitionError,
    OwnerRequiredError,
    TemplateKeyInvalidError,
)
from documents.models import Document
from documents.selectors import (
    filter_documents,
    get_document_by_id,
    get_documents,
    get_history_for_document,
    get_workspace_summaries,
)
from documents.serializers import (
    ArchiveSerializer,
    DocumentCreateSerializer,
    DocumentDetailSerializer,
    DocumentHistorySerializer,
    DocumentListSerializer,
    DocumentSearchSerializer,
    DocumentUpdateSerializer,
    StatusChangeSerializer,
    WorkspaceSummarySerializer,
)

#: Fields a PATCH may not carry, and the code each is refused with. Rejected
#: loudly rather than dropped silently: a client that sent `applicant` and got
#: 200 back would believe a document had been reassigned.
OWNERSHIP_FIELDS = frozenset({"applicant", "family", "template_key"})
STATUS_FIELDS = frozenset({"status", "archive_reason", "archived_at", "archived_by"})


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Admin authority is required to access documents.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found() -> Response:
    return error_response(
        ErrorCode.DOCUMENT_NOT_FOUND,
        "Document not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _conflict(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_409_CONFLICT)


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


def _content_error(exc: Exception, code: str) -> Response:
    return _bad_request(code, str(exc), details={"content": [str(exc)]})


class DocumentActorView(APIView):
    """Base for every view in this app — one authority check, applied everywhere."""

    permission_classes = [IsAuthenticated]

    def check_actor(self, request: Request) -> Response | None:
        try:
            require_document_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        return None


class DocumentScopedView(DocumentActorView):
    """Base for every view addressing a single document by id."""

    def resolve(self, request: Request, document_id: str) -> tuple[Document | None, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        document = get_document_by_id(document_id)
        if document is None:
            return None, _not_found()
        return document, None


class DocumentListCreateView(DocumentActorView):
    """GET/POST /api/v1/documents/ — the worklist, or a new working record."""

    def get(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        search = DocumentSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_documents(get_documents(), search.validated_data)
        return _paginated(request, queryset, DocumentListSerializer, "Documents retrieved.")

    def post(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        serializer = DocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        applicant = None
        applicant_id = data.pop("applicant", None)
        if applicant_id:
            applicant = get_applicant_by_id(str(applicant_id))
            if applicant is None:
                return _bad_request(
                    ErrorCode.APPLICANT_NOT_FOUND,
                    "Applicant not found.",
                    details={"applicant": ["No applicant with that id."]},
                )

        try:
            document = services.create_document(
                actor=request.user,
                applicant=applicant,
                data=data,
                ip_address=_client_ip(request),
            )
        except OwnerRequiredError as exc:
            return _bad_request(
                ErrorCode.OWNER_REQUIRED,
                str(exc),
                details={"standalone_purpose": ["Required when the document has no applicant."]},
            )
        except TemplateKeyInvalidError as exc:
            return _bad_request(
                ErrorCode.TEMPLATE_KEY_INVALID,
                str(exc),
                details={"template_key": [str(exc)]},
            )
        except ContentInvalidError as exc:
            return _content_error(exc, ErrorCode.CONTENT_INVALID)
        except ContentTooLargeError as exc:
            return _content_error(exc, ErrorCode.CONTENT_TOO_LARGE)

        return success_response(
            data=DocumentDetailSerializer(document).data,
            message="Document created.",
            http_status=status.HTTP_201_CREATED,
        )


class WorkspaceListView(DocumentActorView):
    """GET /api/v1/documents/workspaces/ — documents grouped by applicant."""

    def get(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err
        return _paginated(
            request,
            get_workspace_summaries(),
            WorkspaceSummarySerializer,
            "Workspaces retrieved.",
        )


class DocumentDetailView(DocumentScopedView):
    """GET/PATCH /api/v1/documents/<id>/ — read or save the workspace."""

    def get(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err
        return success_response(data=DocumentDetailSerializer(document).data, message="Document retrieved.")

    def patch(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err

        submitted = set(request.data or {})
        ownership = sorted(OWNERSHIP_FIELDS & submitted)
        if ownership:
            return _bad_request(
                ErrorCode.OWNERSHIP_IMMUTABLE,
                "A document's owner, family, and template cannot be changed after creation.",
                details={field: ["This field cannot be changed after creation."] for field in ownership},
            )
        standing = sorted(STATUS_FIELDS & submitted)
        if standing:
            return _bad_request(
                ErrorCode.STATUS_IMMUTABLE,
                "A document's status is changed through the status, archive, and restore actions.",
                details={field: ["This field cannot be set directly."] for field in standing},
            )

        serializer = DocumentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_document(
                actor=request.user,
                document=document,
                fields=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except DocumentNotEditableError as exc:
            return _conflict(ErrorCode.DOCUMENT_NOT_EDITABLE, str(exc))
        except OwnerRequiredError as exc:
            return _bad_request(
                ErrorCode.OWNER_REQUIRED,
                str(exc),
                details={"standalone_purpose": ["Required when the document has no applicant."]},
            )
        except ContentInvalidError as exc:
            return _content_error(exc, ErrorCode.CONTENT_INVALID)
        except ContentTooLargeError as exc:
            return _content_error(exc, ErrorCode.CONTENT_TOO_LARGE)

        return success_response(data=DocumentDetailSerializer(updated).data, message="Document updated.")


class DocumentStatusView(DocumentScopedView):
    """POST /api/v1/documents/<id>/status/ — move between draft and ready."""

    def post(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err

        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_status(
                actor=request.user,
                document=document,
                status=serializer.validated_data["status"],
                ip_address=_client_ip(request),
            )
        except DocumentNotEditableError as exc:
            return _conflict(ErrorCode.DOCUMENT_NOT_EDITABLE, str(exc))
        except InvalidStatusTransitionError as exc:
            return _bad_request(ErrorCode.STATUS_INVALID_TRANSITION, str(exc))

        return success_response(data=DocumentDetailSerializer(updated).data, message="Status updated.")


class DocumentArchiveView(DocumentScopedView):
    """POST /api/v1/documents/<id>/archive/ — retire a document, recording why."""

    def post(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err

        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.archive_document(
                actor=request.user,
                document=document,
                reason=serializer.validated_data["reason"],
                ip_address=_client_ip(request),
            )
        except DocumentAlreadyArchivedError as exc:
            return _conflict(ErrorCode.DOCUMENT_ALREADY_ARCHIVED, str(exc))
        except ArchiveReasonRequiredError as exc:
            return _bad_request(
                ErrorCode.ARCHIVE_REASON_REQUIRED,
                str(exc),
                details={"reason": ["This field is required."]},
            )

        return success_response(data=DocumentDetailSerializer(updated).data, message="Document archived.")


class DocumentRestoreView(DocumentScopedView):
    """POST /api/v1/documents/<id>/restore/ — return an archived document to draft."""

    def post(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err
        try:
            updated = services.restore_document(
                actor=request.user,
                document=document,
                ip_address=_client_ip(request),
            )
        except DocumentNotArchivedError as exc:
            return _conflict(ErrorCode.DOCUMENT_NOT_ARCHIVED, str(exc))
        return success_response(data=DocumentDetailSerializer(updated).data, message="Document restored.")


class DocumentHistoryView(DocumentScopedView):
    """GET /api/v1/documents/<id>/history/ — the document's chronological history."""

    def get(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve(request, document_id)
        if err:
            return err
        return _paginated(
            request,
            get_history_for_document(document),
            DocumentHistorySerializer,
            "History retrieved.",
        )
