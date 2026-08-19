from django.db import OperationalError, connection
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from core import __version__


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def health(request: Request) -> Response:
    # `version` rides on the liveness probe rather than readiness because
    # /health/ answers without touching the database: a box that is up but
    # cannot reach PostgreSQL still reports which build it is running, which
    # is exactly when that answer matters. Adding an optional response field
    # is non-breaking (CLAUDE.md §22).
    return Response({"status": "ok", "version": __version__}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def ready(request: Request) -> Response:
    try:
        connection.ensure_connection()
    except OperationalError:
        return Response({"status": "not ready"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"status": "ready"}, status=status.HTTP_200_OK)
