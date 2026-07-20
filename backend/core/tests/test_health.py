from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase


class HealthCheckTestCase(APITestCase):
    def test_health_returns_200(self) -> None:
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ok")

    def test_health_does_not_require_auth(self) -> None:
        response = self.client.get("/health/")
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ready_returns_200_when_db_connected(self) -> None:
        response = self.client.get("/ready/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ready")

    def test_ready_returns_503_when_db_unavailable(self) -> None:
        from django.db import OperationalError

        with patch("core.views.connection.ensure_connection", side_effect=OperationalError):
            response = self.client.get("/ready/")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["status"], "not ready")

    def test_ready_does_not_require_auth(self) -> None:
        response = self.client.get("/ready/")
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
