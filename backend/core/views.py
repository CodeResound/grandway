from django.db import OperationalError, connection
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def health(request: Request) -> Response:
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def ready(request: Request) -> Response:
    try:
        connection.ensure_connection()
    except OperationalError:
        return Response({"status": "not ready"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"status": "ready"}, status=status.HTTP_200_OK)
