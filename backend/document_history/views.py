"""Thin views for the document_history app.

Views receive the request, apply the interim access check (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

**Admin only, on every route including reads.** Identical to ``documents`` — see
``documents/docs/SECURITY.md`` §1, which argues it for both apps.

Two exception classes are caught here that this app does not raise:
``DocumentNotEditableError`` and ``ContentTooLargeError`` come out of
``documents.services.update_document`` during a recovery. They are re-coded
under this app's ``DOCUMENT_HISTORY_*`` codes, because a consumer calling a
``/document-history/`` route should never receive a ``DOCUMENTS_*`` code for a
route it did not call.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from documents.exceptions import ContentTooLargeError, DocumentNotEditableError
from documents.selectors import get_document_by_id
from documents.serializers import DocumentDetailSerializer
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from document_history import services
from document_history.access import require_document_history_actor
from document_history.constants import ErrorCode
from document_history.exceptions import (
    ActorNotPermittedError,
    RenderContextInvalidError,
    RenderContextTooLargeError,
)
from document_history.models import DocumentSnapshot
from document_history.selectors import (
    filter_print_events,
    filter_snapshots,
    get_print_events_for_document,
    get_snapshot_by_id,
    get_snapshots_for_document,
)
from document_history.serializers import (
    PrintEventNoteSerializer,
    PrintEventSerializer,
    SnapshotCaptureSerializer,
    SnapshotDetailSerializer,
    SnapshotListSerializer,
    SnapshotSearchSerializer,
    TimelineSearchSerializer,
)


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Admin authority is required to access document history.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _document_not_found() -> Response:
    return error_response(
        ErrorCode.DOCUMENT_NOT_FOUND,
        "Document not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _snapshot_not_found() -> Response:
    return error_response(
        ErrorCode.SNAPSHOT_NOT_FOUND,
        "Snapshot not found.",
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


class HistoryActorView(APIView):
    """Base for every view in this app — one authority check, applied everywhere."""

    permission_classes = [IsAuthenticated]

    def check_actor(self, request: Request) -> Response | None:
        try:
            require_document_history_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        return None


class DocumentScopedView(HistoryActorView):
    """Base for views addressing one document's history by document id.

    Resolves through ``documents.selectors`` rather than assuming the id is
    valid: a timeline for a document that does not exist is a 404, not an empty
    list, because an empty list asserts "this document has never been printed".
    """

    def resolve_document(self, request: Request, document_id: str) -> tuple[Any, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        document = get_document_by_id(document_id)
        if document is None:
            return None, _document_not_found()
        return document, None


class SnapshotScopedView(HistoryActorView):
    """Base for views addressing a single snapshot by id."""

    def resolve_snapshot(self, request: Request, snapshot_id: str) -> tuple[DocumentSnapshot | None, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        snapshot = get_snapshot_by_id(snapshot_id)
        if snapshot is None:
            return None, _snapshot_not_found()
        return snapshot, None


class SnapshotListCreateView(DocumentScopedView):
    """GET/POST /documents/<document_id>/snapshots/ — the version chain, or a new capture."""

    def get(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve_document(request, document_id)
        if err:
            return err

        search = SnapshotSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_snapshots(get_snapshots_for_document(str(document.id)), search.validated_data)
        return _paginated(request, queryset, SnapshotListSerializer, "Snapshots retrieved.")

    def post(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve_document(request, document_id)
        if err:
            return err

        serializer = SnapshotCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            snapshot = services.create_snapshot(
                actor=request.user,
                document=document,
                render_context=data.get("render_context", {}),
                capture_note=data.get("capture_note", ""),
                ip_address=_client_ip(request),
            )
        except RenderContextInvalidError as exc:
            return _bad_request(
                ErrorCode.RENDER_CONTEXT_INVALID,
                str(exc),
                details={"render_context": [str(exc)]},
            )
        except RenderContextTooLargeError as exc:
            return _bad_request(
                ErrorCode.RENDER_CONTEXT_TOO_LARGE,
                str(exc),
                details={"render_context": [str(exc)]},
            )

        return success_response(
            data=SnapshotDetailSerializer(snapshot).data,
            message="Snapshot captured.",
            http_status=status.HTTP_201_CREATED,
        )


class TimelineView(DocumentScopedView):
    """GET /documents/<document_id>/timeline/ — every print event, newest first."""

    def get(self, request: Request, document_id: str) -> Response:
        document, err = self.resolve_document(request, document_id)
        if err:
            return err

        search = TimelineSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_print_events(get_print_events_for_document(str(document.id)), search.validated_data)
        return _paginated(request, queryset, PrintEventSerializer, "Timeline retrieved.")


class SnapshotDetailView(SnapshotScopedView):
    """GET /snapshots/<snapshot_id>/ — one frozen snapshot in full."""

    def get(self, request: Request, snapshot_id: str) -> Response:
        snapshot, err = self.resolve_snapshot(request, snapshot_id)
        if err:
            return err
        return success_response(data=SnapshotDetailSerializer(snapshot).data, message="Snapshot retrieved.")


class SnapshotReprintView(SnapshotScopedView):
    """POST /snapshots/<snapshot_id>/reprint/ — record a reprint of a past snapshot."""

    def post(self, request: Request, snapshot_id: str) -> Response:
        snapshot, err = self.resolve_snapshot(request, snapshot_id)
        if err:
            return err

        serializer = PrintEventNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = services.reprint_snapshot(
            actor=request.user,
            snapshot=snapshot,
            note=serializer.validated_data.get("note", ""),
            ip_address=_client_ip(request),
        )
        return success_response(
            data=PrintEventSerializer(event).data,
            message="Reprint recorded.",
            http_status=status.HTTP_201_CREATED,
        )


class SnapshotRecoverView(SnapshotScopedView):
    """POST /snapshots/<snapshot_id>/recover/ — restore a frozen body into the working document.

    Returns the updated **Document**, not the snapshot, so the client can drop
    it straight back into the workspace without a second request.
    """

    def post(self, request: Request, snapshot_id: str) -> Response:
        snapshot, err = self.resolve_snapshot(request, snapshot_id)
        if err:
            return err

        serializer = PrintEventNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            document = services.recover_snapshot(
                actor=request.user,
                snapshot=snapshot,
                note=serializer.validated_data.get("note", ""),
                ip_address=_client_ip(request),
            )
        except DocumentNotEditableError:
            return _conflict(
                ErrorCode.DOCUMENT_NOT_EDITABLE,
                "This document is archived; restore it before recovering a snapshot into it.",
            )
        except ContentTooLargeError as exc:
            return _bad_request(ErrorCode.CONTENT_TOO_LARGE, str(exc), details={"content": [str(exc)]})

        return success_response(
            data=DocumentDetailSerializer(document).data,
            message="Snapshot recovered into the document.",
        )
