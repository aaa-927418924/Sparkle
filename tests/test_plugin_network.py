import unittest
from unittest.mock import patch

import plugin_network


class PluginNetworkTests(unittest.TestCase):
    def test_local_and_non_https_destinations_are_rejected(self):
        for url in (
            "http://example.com/",
            "https://127.0.0.1/",
            "https://localhost/",
            "https://example.com:8443/",
        ):
            with self.subTest(url=url), self.assertRaises(plugin_network.PluginNetworkError):
                plugin_network.perform_plugin_network_request(url=url)

    def test_dns_results_that_include_private_addresses_are_rejected(self):
        private_result = (None, None, None, None, ("192.168.1.20", 443))
        with patch.object(plugin_network.socket, "getaddrinfo", return_value=[private_result]):
            with self.assertRaises(plugin_network.PluginNetworkError):
                plugin_network._public_address("service.example", 443)

    def test_public_https_request_is_pinned_and_does_not_follow_redirects(self):
        calls = []

        class FakeResponse:
            status = 302

            def read(self, limit):
                return b"redirect response"

            def getheader(self, name, default=""):
                return {
                    "Content-Type": "text/plain",
                    "Location": "https://login.example/continue",
                }.get(name, default)

        class FakeConnection:
            def __init__(self, host, address, port):
                calls.append(("connect", host, address, port))

            def request(self, method, path, body=None, headers=None):
                calls.append(("request", method, path, body, dict(headers or {})))

            def getresponse(self):
                return FakeResponse()

            def close(self):
                calls.append(("close",))

        with patch.object(plugin_network, "_public_address", return_value="93.184.216.34"), patch.object(
            plugin_network, "_PinnedHTTPSConnection", FakeConnection
        ):
            result = plugin_network.perform_plugin_network_request(
                url="https://api.example/v1/items?q=one",
                method="POST",
                headers={"Authorization": "Bearer plugin-token", "Content-Type": "application/json"},
                body="{}",
            )

        self.assertEqual(result["status"], 302)
        self.assertEqual(result["headers"]["location"], "https://login.example/continue")
        self.assertEqual(result["body"], "redirect response")
        self.assertEqual(calls[0], ("connect", "api.example", "93.184.216.34", 443))
        self.assertEqual(calls[1][1:4], ("POST", "/v1/items?q=one", b"{}"))
        self.assertEqual(sum(1 for call in calls if call[0] == "request"), 1)
        self.assertEqual(calls[-1], ("close",))

    def test_sensitive_transport_headers_and_body_limits_are_rejected(self):
        with self.assertRaises(plugin_network.PluginNetworkError):
            plugin_network._validate_headers({"Host": "127.0.0.1"})
        with self.assertRaises(plugin_network.PluginNetworkError):
            plugin_network._validate_headers({"Cookie": "session=secret"})
        with self.assertRaises(plugin_network.PluginNetworkError):
            plugin_network.perform_plugin_network_request(
                url="https://example.com/",
                body="x" * (plugin_network.MAX_REQUEST_BYTES + 1),
            )


if __name__ == "__main__":
    unittest.main()
