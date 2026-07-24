"""Thin views for the clients app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

The access split is applied by the base classes below: **every Admin and Lead
Manager may read; only an Admin may write.** See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from clients import services
from clients.access import require_admin, require_client_reader
from clients.constants import ErrorCode
from clients.exceptions import (
    ActorNotPermittedError,
    ClientAlreadyRetiredError,
    ClientNotRetiredError,
    ContactNumberDuplicateError,
    StatusNoteRequiredError,
)
from clients.models import Client
from clients.selectors import filter_clients, get_client_by_id, get_clients, get_history_for_client
from clients.serializers import (
    ClientCreateSerializer,
    ClientDetailSerializer,
    ClientHistorySerializer,
    ClientListSerializer,
    ClientSearchSerializer,
    ClientUpdateSerializer,
    RetireSerializer,
)

#: Fields a PATCH may not carry. `status` has exactly one path — the retire and
#: restore actions — so an edit form that tried to set it directly is rejected
#: rather than silently ignored: a client that sent `status` and got 200 back
#: would believe the record had changed.
REJECTED_ON_PATCH = frozenset({"status", "status_note", "retired_at", "retired_by"})


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden(message: str = "Your authority level may not perform this action.") -> Response:
    return error_response(ErrorCode.ACTOR_FORBIDDEN, message, http_status=status.HTTP_403_FORBIDDEN)


def _not_found() -> Response:
    return error_response(
        ErrorCode.CLIENT_NOT_FOUND,
        "Client not found.",
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


def _duplicate_number(exc: ContactNumberDuplicateError) -> Response:
    return _bad_request(
        ErrorCode.CONTACT_NUMBER_DUPLICATE,
        str(exc),
        details={"contact_numbers": ["The same number is listed more than once."]},
    )


class ClientScopedView(APIView):
    """Base for every view addressing a single client by id.

    ``resolve`` takes the required check as an argument so a read route and a
    write route on the same resource cannot accidentally share the wrong one.
    """

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, client_id: str, *, check: Any) -> tuple[Client | None, Response | None]:
        try:
            check(request.user)
        except ActorNotPermittedError as exc:
            return None, _forbidden(str(exc))
        client = get_client_by_id(client_id)
        if client is None:
            return None, _not_found()
        return client, None


class ClientListCreateView(APIView):
    """GET/POST /api/v1/clients/ — browse the directory, or add a partner."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_client_reader(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))

        search = ClientSearchSerializer(data=request.query_params)
        search.is_valid(raise_exception=True)
        queryset = filter_clients(get_clients(), search.validated_data)
        return _paginated(request, queryset, ClientListSerializer, "Clients retrieved.")

    def post(self, request: Request) -> Response:
        try:
            require_admin(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))

        serializer = ClientCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        contact_numbers = [dict(n) for n in data.pop("contact_numbers", [])]

        try:
            client = services.create_client(
                actor=request.user,
                data=data,
                contact_numbers=contact_numbers,
                ip_address=_client_ip(request),
            )
        except ContactNumberDuplicateError as exc:
            return _duplicate_number(exc)

        return success_response(
            data=ClientDetailSerializer(client).data,
            message="Client added.",
            http_status=status.HTTP_201_CREATED,
        )


class ClientDetailView(ClientScopedView):
    """GET/PATCH /api/v1/clients/<id>/ — read or correct one client."""

    def get(self, request: Request, client_id: str) -> Response:
        client, err = self.resolve(request, client_id, check=require_client_reader)
        if err:
            return err
        return success_response(data=ClientDetailSerializer(client).data, message="Client retrieved.")

    def patch(self, request: Request, client_id: str) -> Response:
        client, err = self.resolve(request, client_id, check=require_admin)
        if err:
            return err

        attempted = sorted(REJECTED_ON_PATCH & set(request.data or {}))
        if attempted:
            return _bad_request(
                ErrorCode.STATUS_IMMUTABLE,
                "A client's standing is changed through the retire and restore actions, not by editing it.",
                details={field: ["This field cannot be set directly."] for field in attempted},
            )

        serializer = ClientUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        # `None` means "leave the numbers alone"; an empty list means "clear
        # them". Popping with a sentinel is what keeps the two distinguishable.
        contact_numbers = fields.pop("contact_numbers", None)
        if contact_numbers is not None:
            contact_numbers = [dict(n) for n in contact_numbers]

        try:
            updated = services.update_client(
                actor=request.user,
                client=client,
                fields=fields,
                contact_numbers=contact_numbers,
                ip_address=_client_ip(request),
            )
        except ContactNumberDuplicateError as exc:
            return _duplicate_number(exc)

        return success_response(data=ClientDetailSerializer(updated).data, message="Client updated.")


class ClientRetireView(ClientScopedView):
    """POST /api/v1/clients/<id>/retire/ — withdraw a partner from current use."""

    def post(self, request: Request, client_id: str) -> Response:
        client, err = self.resolve(request, client_id, check=require_admin)
        if err:
            return err

        serializer = RetireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.retire_client(
                actor=request.user,
                client=client,
                reason=serializer.validated_data["reason"],
                ip_address=_client_ip(request),
            )
        except ClientAlreadyRetiredError as exc:
            return _conflict(ErrorCode.CLIENT_ALREADY_RETIRED, str(exc))
        except StatusNoteRequiredError as exc:
            return _bad_request(
                ErrorCode.STATUS_NOTE_REQUIRED,
                str(exc),
                details={"reason": ["This field is required."]},
            )
        return success_response(data=ClientDetailSerializer(updated).data, message="Client retired.")


class ClientRestoreView(ClientScopedView):
    """POST /api/v1/clients/<id>/restore/ — return a retired partner to use."""

    def post(self, request: Request, client_id: str) -> Response:
        client, err = self.resolve(request, client_id, check=require_admin)
        if err:
            return err
        try:
            updated = services.restore_client(
                actor=request.user,
                client=client,
                ip_address=_client_ip(request),
            )
        except ClientNotRetiredError as exc:
            return _conflict(ErrorCode.CLIENT_NOT_RETIRED, str(exc))
        return success_response(data=ClientDetailSerializer(updated).data, message="Client restored.")


class ClientHistoryView(ClientScopedView):
    """GET /api/v1/clients/<id>/history/ — the client's chronological history."""

    def get(self, request: Request, client_id: str) -> Response:
        client, err = self.resolve(request, client_id, check=require_client_reader)
        if err:
            return err
        return _paginated(
            request,
            get_history_for_client(client),
            ClientHistorySerializer,
            "History retrieved.",
        )
