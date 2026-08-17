"""core.network.client_ip must agree with DRF's NUM_PROXIES semantics (S7)."""

from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from rest_framework.settings import api_settings

from core.network import client_ip


class ClientIpTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_default_ignores_forgeable_forwarded_header(self) -> None:
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6", REMOTE_ADDR="10.0.0.9")
        self.assertEqual(client_ip(request), "10.0.0.9")

    def test_behind_one_proxy_reads_the_last_forwarded_hop(self) -> None:
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7", REMOTE_ADDR="10.0.0.9")
        with patch.object(api_settings, "NUM_PROXIES", 1):
            self.assertEqual(client_ip(request), "203.0.113.7")

    def test_behind_a_proxy_with_no_header_falls_back_to_remote_addr(self) -> None:
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.9")
        with patch.object(api_settings, "NUM_PROXIES", 1):
            self.assertEqual(client_ip(request), "10.0.0.9")
