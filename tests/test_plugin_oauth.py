import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import plugin_oauth


class FakeSecretStore:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class FakeHttpServer:
    def __init__(self, address, handler):
        self.server_port = 43123
        self.timeout = None
        self.closed = False

    def server_close(self):
        self.closed = True


class FakeThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        return None


class PluginOAuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plugins = Path(self.temporary.name) / "plugins"
        self.plugins.mkdir()
        self.store = FakeSecretStore()
        self.addCleanup(self.temporary.cleanup)

    def config(self):
        return {
            "connection_id": "codex-plan",
            "name": "Codex plan",
            "agent_name_hint": "Sparkle",
            "authorization_url": "https://auth.example.test/authorize",
            "token_url": "https://auth.example.test/token",
            "client_id": "public-client-id",
            "scopes": ["openid", "offline_access", "resource.invoke"],
            "resource": "https://api.example.test/v1",
            "api_origin": "https://api.example.test",
            "issuer": "https://auth.example.test",
            "jwks_url": "https://auth.example.test/jwks",
        }

    def test_oauth_connect_uses_pkce_browser_flow_and_returns_no_tokens(self):
        fake_server = FakeHttpServer(None, None)
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"), patch(
            "plugin_oauth.HTTPServer", return_value=fake_server
        ), patch("plugin_oauth.threading.Thread", FakeThread), patch(
            "plugin_oauth.webbrowser.open", return_value=True
        ), patch("plugin_oauth._secret_store", return_value=self.store):
            status = plugin_oauth.start_connection("test-plugin", self.config(), self.plugins)
            pending = plugin_oauth._pending[("test-plugin", "codex-plan")]
            url = plugin_oauth._authorization_url(pending.profile, pending.client_id, pending)
            self.assertTrue(status["pending"])
            self.assertTrue(status["api_origin"].startswith("https://api.example.test"))
            self.assertNotIn("access_token", status)
            self.assertNotIn("refresh_token", status)
            self.assertNotIn("verifier", status)
            self.assertIn("code_challenge_method=S256", url)
            self.assertIn("code_challenge=", url)
            self.assertIn("nonce=", url)
            plugin_oauth.disconnect_connection("test-plugin", "codex-plan", self.plugins)
        self.assertTrue(fake_server.closed)

    def test_dynamic_agent_registration_adds_host_identity_only_for_first_sign_in(self):
        config = self.config()
        config.update(client_id="dynamic_agent_client", dynamic_registration=True)
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"), patch(
            "plugin_oauth.HTTPServer", return_value=FakeHttpServer(None, None)
        ), patch("plugin_oauth.threading.Thread", FakeThread), patch(
            "plugin_oauth.webbrowser.open", return_value=True
        ), patch("plugin_oauth._secret_store", return_value=self.store):
            plugin_oauth.start_connection("test-plugin", config, self.plugins)
            pending = plugin_oauth._pending[("test-plugin", "codex-plan")]
            first_url = plugin_oauth._authorization_url(pending.profile, pending.client_id, pending)
            self.assertIn("client_id=dynamic_agent_client", first_url)
            self.assertIn("ext_agent_host_id=urn%3Auuid%3A", first_url)
            self.assertIn("agent_name_hint=Sparkle", first_url)
            host_id = pending.profile["host_id"]
            self.assertEqual(plugin_oauth._select_callback_client_id(
                pending.profile,
                pending_client_id="dynamic_agent_client",
                callback_client_id="issued-client-id",
            ), "issued-client-id")
            plugin_oauth.disconnect_connection("test-plugin", "codex-plan", self.plugins)
            self.assertEqual(plugin_oauth._persistent_host_id("test-plugin", {}, self.plugins), host_id)
            self.assertEqual(plugin_oauth._select_callback_client_id(
                pending.profile,
                pending_client_id="issued-client-id",
                callback_client_id="",
            ), "issued-client-id")
            self.assertEqual(plugin_oauth._select_callback_client_id(
                pending.profile,
                pending_client_id="issued-client-id",
                callback_client_id="different-client-id",
            ), "")

    def test_dynamic_registration_reauthorization_reuses_issued_client_id_and_host_id(self):
        config = self.config()
        config.update(client_id="dynamic_agent_client", dynamic_registration=True)
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"):
            profile = plugin_oauth._validate_config(config, "test-plugin")
        profile.update(registered_client_id="issued-client-id", host_id="urn:uuid:12345678-1234-5678-1234-567812345678")
        plugin_oauth._write_profiles("test-plugin", {"codex-plan": profile}, self.plugins)
        self.store.values[plugin_oauth._key("test-plugin", "codex-plan", "access")] = "expired-access-token"
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"), patch(
            "plugin_oauth.HTTPServer", return_value=FakeHttpServer(None, None)
        ), patch("plugin_oauth.threading.Thread", FakeThread), patch(
            "plugin_oauth.webbrowser.open", return_value=True
        ), patch("plugin_oauth._secret_store", return_value=self.store):
            plugin_oauth.start_connection("test-plugin", {**config, "reauthorize": True}, self.plugins)
            pending = plugin_oauth._pending[("test-plugin", "codex-plan")]
            authorization_url = plugin_oauth._authorization_url(pending.profile, pending.client_id, pending)
            self.assertEqual(pending.client_id, "issued-client-id")
            self.assertIn("client_id=issued-client-id", authorization_url)
            self.assertNotIn("ext_agent_host_id", authorization_url)
            self.assertNotIn("agent_name_hint", authorization_url)
            self.assertEqual(
                plugin_oauth._select_callback_client_id(
                    pending.profile,
                    pending_client_id=pending.client_id,
                    callback_client_id="",
                ),
                "issued-client-id",
            )
            plugin_oauth.disconnect_connection("test-plugin", "codex-plan", self.plugins)

    def test_authenticated_request_injects_secret_and_is_bound_to_declared_origin(self):
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"):
            profile = plugin_oauth._validate_config(self.config(), "test-plugin")
        profile["registered_client_id"] = profile["client_id"]
        plugin_oauth._write_profiles("test-plugin", {"codex-plan": profile}, self.plugins)
        self.store.values.update({
            plugin_oauth._key("test-plugin", "codex-plan", "access"): "never-return-this-token",
            plugin_oauth._key("test-plugin", "codex-plan", "expires"): "4102444800",
        })
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"), patch(
            "plugin_oauth._secret_store", return_value=self.store
        ), patch(
            "plugin_oauth.perform_plugin_network_request",
            return_value={"status": 200, "headers": {"content-type": "application/json"}, "body": "{\"ok\":true}"},
        ) as request:
            result = plugin_oauth.authenticated_request(
                "test-plugin",
                "codex-plan",
                url="https://api.example.test/v1/responses",
                method="POST",
                headers={"Content-Type": "application/json"},
                body="{}",
                directory=self.plugins,
            )
        self.assertEqual(result["status"], 200)
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer never-return-this-token")
        self.assertEqual(request.call_args.kwargs["timeout_seconds"], 120)

        with patch("plugin_oauth._secret_store", return_value=self.store):
            with self.assertRaises(plugin_oauth.PluginOAuthError):
                plugin_oauth.authenticated_request(
                    "test-plugin",
                    "codex-plan",
                    url="https://other.example.test/v1/responses",
                    directory=self.plugins,
                )

    def test_disconnect_and_permission_cleanup_remove_plugin_tokens_and_profiles(self):
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"):
            profile = plugin_oauth._validate_config(self.config(), "test-plugin")
        plugin_oauth._write_profiles("test-plugin", {"codex-plan": profile}, self.plugins)
        self.store.values.update({
            plugin_oauth._key("test-plugin", "codex-plan", "access"): "access-secret",
            plugin_oauth._key("test-plugin", "codex-plan", "refresh"): "refresh-secret",
        })
        with patch("plugin_oauth._secret_store", return_value=self.store):
            plugin_oauth.clear_plugin_connections("test-plugin", self.plugins)
        self.assertFalse(self.store.values)
        self.assertFalse((self.plugins.parent / "plugin-data" / "test-plugin" / "oauth-connections.json").exists())

    def test_permission_revoke_during_token_exchange_cannot_restore_credentials(self):
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"):
            profile = plugin_oauth._validate_config(self.config(), "test-plugin")
        plugin_oauth._write_profiles("test-plugin", {"codex-plan": profile}, self.plugins)
        pending = plugin_oauth._PendingAuthorization(
            plugin_id="test-plugin",
            connection_id="codex-plan",
            profile=profile,
            state="state",
            nonce="nonce",
            verifier="verifier",
            redirect_uri="http://127.0.0.1:43123/auth/callback",
            client_id="public-client-id",
            server=FakeHttpServer(None, None),
        )
        plugin_oauth._pending[("test-plugin", "codex-plan")] = pending

        def revoke_during_exchange(*_args, **_kwargs):
            with patch("plugin_oauth._secret_store", return_value=self.store):
                plugin_oauth.clear_plugin_connections("test-plugin", self.plugins)
            return {"access_token": "must-not-be-saved", "expires_in": 3600}

        with patch("plugin_oauth._secret_store", return_value=self.store), patch(
            "plugin_oauth._post_token_form", side_effect=revoke_during_exchange
        ):
            plugin_oauth._complete_authorization(pending, "authorization-code", "public-client-id", self.plugins)

        self.assertFalse(self.store.values)
        self.assertFalse((self.plugins.parent / "plugin-data" / "test-plugin" / "oauth-connections.json").exists())
        self.assertNotIn(("test-plugin", "codex-plan"), plugin_oauth._pending)

    def test_openid_requires_verification_configuration(self):
        config = self.config()
        config["jwks_url"] = None
        with patch("plugin_oauth._public_address", return_value="93.184.216.34"):
            with self.assertRaises(plugin_oauth.PluginOAuthError):
                plugin_oauth._validate_config(config, "test-plugin")


if __name__ == "__main__":
    unittest.main()
