"""Thin views for the uploaded_files app.

Views receive the request, apply the interim access check (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

**Two authority levels, unlike every other app in the project.** Admin and Lead
Manager share the read/upload/replace/download routes; verify, archive, and
restore are Admin-only. The split is expressed as two base classes so a route
cannot accidentally acquire the wrong one by omission — a view either extends
``FileScopedView`` or ``AdminFileScopedView``, and there is no third option that
resolves a file without checking anything.

**The download route is the only one that does not return the standard JSON
envelope**, because it returns bytes. §7 governs API responses; a file transfer
is not one. Every failure on that route still uses the envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from core.network import client_ip
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from django.http import FileResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from uploaded_files import services
from uploaded_files.access import (
    is_admin,
    require_admin,
    require_file_actor,
    require_owner_visibility,
)
from uploaded_files.constants import OWNER_FIELDS, ErrorCode
from uploaded_files.exceptions import (
    ActorNotPermittedError,
    AlreadyArchivedError,
    AlreadySupersededError,
    FieldImmutableError,
    FileArchivedError,
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    InvalidVerificationStatusError,
    NotArchivedError,
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReasonRequiredError,
)
from uploaded_files.models import UploadedFile
from uploaded_files.selectors import (
    filter_files,
    get_file_by_id,
    get_version_chain,
    get_visible_files,
)
from uploaded_files.serializers import (
    FileArchiveSerializer,
    FileReplaceSerializer,
    FileRestoreSerializer,
    FileReviewSerializer,
    FileSearchSerializer,
    FileUpdateSerializer,
    FileUploadSerializer,
    UploadedFileSerializer,
)

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    # Proxy-aware via NUM_PROXIES — keeps download records in step with what
    # the throttles and axes attribute the request to (2026-08-17 audit, S7).
    return client_ip(request)


def _forbidden(message: str) -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        message,
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_404_NOT_FOUND)


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _rejected_upload(exc: Exception) -> Response:
    """Map a §14 upload rejection to its error code.

    One helper because the upload and replace routes must answer identically —
    a client that learns the size limit from ``POST /files/`` should not
    discover a different code for the same refusal on ``.../replace/``.
    """
    if isinstance(exc, FileEmptyError):
        code = ErrorCode.FILE_EMPTY
    elif isinstance(exc, FileTooLargeError):
        code = ErrorCode.FILE_TOO_LARGE
    elif isinstance(exc, FileTypeNotAllowedError):
        code = ErrorCode.FILE_TYPE_NOT_ALLOWED
    else:
        code = ErrorCode.FILE_CONTENT_MISMATCH
    return _bad_request(code, str(exc), details={"file": [str(exc)]})


def _paginated(request: Request, queryset: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = UploadedFileSerializer(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


class FileActorView(APIView):
    """Base for the routes Admin and Lead Manager share."""

    permission_classes = [IsAuthenticated]

    def check_actor(self, request: Request) -> Response | None:
        try:
            require_file_actor(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))
        return None


class FileScopedView(FileActorView):
    """Base for views addressing one file, open to Admin and Lead Manager.

    **A file whose owner is a document or a print snapshot is Admin-only**, and
    that check happens here rather than in each view, so no per-file route can
    omit it. It reports 404 rather than 403 deliberately: `documents` and
    `document_history` are invisible to a Lead Manager, so confirming that a file
    exists on one of them would leak exactly what those modules hide.
    """

    def resolve(self, request: Request, file_id: str) -> tuple[UploadedFile | None, Response | None]:
        err = self.check_actor(request)
        if err:
            return None, err
        uploaded_file = get_file_by_id(file_id)
        if uploaded_file is None:
            return None, _not_found(ErrorCode.FILE_NOT_FOUND, "File not found.")
        try:
            require_owner_visibility(request.user, uploaded_file.owner_type)
        except ActorNotPermittedError:
            return None, _not_found(ErrorCode.FILE_NOT_FOUND, "File not found.")
        return uploaded_file, None


class AdminFileScopedView(FileScopedView):
    """Base for the three review and archival routes — Admin only.

    The two checks run in order, and the order carries a message: a Superadmin
    gets "may not access uploaded files" rather than the narrower "Admin
    authority is required", which would imply they are one grant away from a
    permission they will never hold.
    """

    def resolve(self, request: Request, file_id: str) -> tuple[UploadedFile | None, Response | None]:
        uploaded_file, err = super().resolve(request, file_id)
        if err:
            return None, err
        try:
            require_admin(request.user)
        except ActorNotPermittedError as exc:
            return None, _forbidden(str(exc))
        return uploaded_file, None


# ---------------------------------------------------------------------------
# List and upload
# ---------------------------------------------------------------------------


class FileListUploadView(FileActorView):
    """GET/POST /files/ — the file ledger, or a new upload."""

    parser_classes = [MultiPartParser, FormParser]

    def get(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        search = FileSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_files(get_visible_files(is_admin=is_admin(request.user)), search.validated_data)
        return _paginated(request, queryset, "Files retrieved.")

    def post(self, request: Request) -> Response:
        err = self.check_actor(request)
        if err:
            return err

        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        upload = data.pop("file")

        # A Lead Manager may not attach a file to a document or a print
        # snapshot, because they cannot open either. Checked here, before the
        # service, so nothing is written to disk on the way to a 403.
        submitted_owner = next((field for field in OWNER_FIELDS if data.get(field) is not None), None)
        try:
            require_owner_visibility(request.user, submitted_owner)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))

        try:
            uploaded_file = services.upload_file(
                actor=request.user,
                upload=upload,
                data=data,
                ip_address=_client_ip(request),
            )
        except OwnerNotResolvedError as exc:
            return _bad_request(ErrorCode.OWNER_REQUIRED, str(exc), details={"owner": [str(exc)]})
        except OwnerNotFoundError as exc:
            return _bad_request(
                ErrorCode.OWNER_NOT_FOUND,
                str(exc),
                details={exc.owner_field: [str(exc)]},
            )
        except (FileEmptyError, FileTooLargeError, FileTypeNotAllowedError, FileContentMismatchError) as exc:
            return _rejected_upload(exc)

        return success_response(
            data=UploadedFileSerializer(uploaded_file).data,
            message="File uploaded.",
            http_status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# One file
# ---------------------------------------------------------------------------


class FileDetailView(FileScopedView):
    """GET/PATCH /files/<id>/ — read one file's metadata, or correct it."""

    def get(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err
        return success_response(
            data=UploadedFileSerializer(uploaded_file).data,
            message="File retrieved.",
        )

    def patch(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        # Refused at the boundary as well as in the service, so a client that
        # sent `applicant` or `verification_status` is told which field was
        # refused rather than having it silently dropped by the serializer.
        submitted = set(request.data or {})
        fixed = sorted(submitted - services.MUTABLE_FIELDS)
        if fixed:
            return _bad_request(
                ErrorCode.FIELD_IMMUTABLE,
                "These fields cannot be changed after upload.",
                details={field: ["This field cannot be changed after upload."] for field in fixed},
            )

        serializer = FileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_file(
                actor=request.user,
                uploaded_file=uploaded_file,
                fields=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except FileArchivedError as exc:
            return _bad_request(ErrorCode.FILE_ARCHIVED, str(exc))
        except FieldImmutableError as exc:
            return _bad_request(ErrorCode.FIELD_IMMUTABLE, str(exc))

        return success_response(data=UploadedFileSerializer(updated).data, message="File updated.")


class FileDownloadView(FileScopedView):
    """GET /files/<id>/download/ — stream the bytes.

    **The only route in the project that returns something other than the
    standard JSON envelope on success**, and the only read that writes an audit
    event. Both follow from what it is: this is where an applicant's passport
    actually leaves the system.

    Three headers are set deliberately:

    * ``Content-Disposition: attachment`` — always, never ``inline``. A file
      rendered in the API's own origin could execute against it; forcing a
      download removes the whole class of problem.
    * ``X-Content-Type-Options: nosniff`` — stops a browser from second-guessing
      the declared type and rendering something as HTML.
    * ``Cache-Control: private, no-store`` — an applicant's passport must not sit
      in a shared cache or on disk after the tab closes.
    """

    def get(self, request: Request, file_id: str) -> Any:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        try:
            handle = uploaded_file.file.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            # The row exists and the bytes do not. Not a client error in any
            # meaningful sense — the database and the storage volume have
            # diverged, which no application code can repair — so it is logged
            # loudly and reported as a 404 rather than leaking a path in a 500.
            logger.error(
                "uploaded_file_bytes_missing",
                extra={"file_id": str(uploaded_file.id), "error_code": ErrorCode.FILE_BYTES_MISSING},
            )
            return _not_found(
                ErrorCode.FILE_BYTES_MISSING,
                "The stored file could not be read.",
            )

        services.record_download(
            actor=request.user,
            uploaded_file=uploaded_file,
            ip_address=_client_ip(request),
        )

        response = FileResponse(
            handle,
            as_attachment=True,
            filename=uploaded_file.original_filename,
            content_type=uploaded_file.content_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


class FileVersionsView(FileScopedView):
    """GET /files/<id>/versions/ — the whole replacement chain, oldest first.

    Returns the chain from any member of it, not just from the current version:
    a client holding a superseded id can still ask what replaced it.
    Unpaginated by design — a chain is short, and paging it would let a caller
    request a slice of something only meaningful whole.
    """

    def get(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        chain = get_version_chain(uploaded_file)
        return success_response(
            data=UploadedFileSerializer(chain, many=True).data,
            message="Version chain retrieved.",
            meta={"count": len(chain)},
        )


class FileReplaceView(FileScopedView):
    """POST /files/<id>/replace/ — supersede this file with a newer one."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        serializer = FileReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            successor = services.replace_file(
                actor=request.user,
                uploaded_file=uploaded_file,
                upload=serializer.validated_data["file"],
                notes=serializer.validated_data.get("notes", ""),
                ip_address=_client_ip(request),
            )
        except FileArchivedError as exc:
            return _bad_request(ErrorCode.FILE_ARCHIVED, str(exc))
        except AlreadySupersededError as exc:
            return _bad_request(ErrorCode.ALREADY_SUPERSEDED, str(exc))
        except (FileEmptyError, FileTooLargeError, FileTypeNotAllowedError, FileContentMismatchError) as exc:
            return _rejected_upload(exc)

        return success_response(
            data=UploadedFileSerializer(successor).data,
            message="File replaced.",
            http_status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin-only: review and archival
# ---------------------------------------------------------------------------


class FileReviewView(AdminFileScopedView):
    """POST /files/<id>/verify/ — record a verdict on a file."""

    def post(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        serializer = FileReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reviewed = services.review_file(
                actor=request.user,
                uploaded_file=uploaded_file,
                status=serializer.validated_data["status"],
                reason=serializer.validated_data.get("reason", ""),
                ip_address=_client_ip(request),
            )
        except FileArchivedError as exc:
            return _bad_request(ErrorCode.FILE_ARCHIVED, str(exc))
        except InvalidVerificationStatusError as exc:
            return _bad_request(ErrorCode.VERIFICATION_STATUS_INVALID, str(exc))
        except ReasonRequiredError as exc:
            return _bad_request(
                ErrorCode.REJECTION_REASON_REQUIRED,
                str(exc),
                details={"reason": [str(exc)]},
            )

        return success_response(data=UploadedFileSerializer(reviewed).data, message="File reviewed.")


class FileArchiveView(AdminFileScopedView):
    """POST /files/<id>/archive/ — retire a file from active work."""

    def post(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        serializer = FileArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            archived = services.archive_file(
                actor=request.user,
                uploaded_file=uploaded_file,
                reason=serializer.validated_data["reason"],
                ip_address=_client_ip(request),
            )
        except AlreadyArchivedError as exc:
            return _bad_request(ErrorCode.ALREADY_ARCHIVED, str(exc))
        except ReasonRequiredError as exc:
            return _bad_request(
                ErrorCode.ARCHIVE_REASON_REQUIRED,
                str(exc),
                details={"reason": [str(exc)]},
            )

        return success_response(data=UploadedFileSerializer(archived).data, message="File archived.")


class FileRestoreView(AdminFileScopedView):
    """POST /files/<id>/restore/ — return an archived file to active work."""

    def post(self, request: Request, file_id: str) -> Response:
        uploaded_file, err = self.resolve(request, file_id)
        if err:
            return err

        serializer = FileRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            restored = services.restore_file(
                actor=request.user,
                uploaded_file=uploaded_file,
                note=serializer.validated_data.get("note", ""),
                ip_address=_client_ip(request),
            )
        except NotArchivedError as exc:
            return _bad_request(ErrorCode.NOT_ARCHIVED, str(exc))

        return success_response(data=UploadedFileSerializer(restored).data, message="File restored.")
