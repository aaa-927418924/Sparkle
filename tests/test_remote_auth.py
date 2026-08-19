import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from remote_auth import AuthStore, InvalidAccessKey
from remote_runtime import (
    REMOTE_TARGET,
    SERVE_WEB_HTTPS_PORT,
    RemoteAccessManager,
    _find_public_url,
)


class RemoteAuthStoreTests(unittest.TestCase):
    def test_web_and_mcp_access_keys_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_key = web_store.enable()
            mcp_key = mcp_store.enable()

            self.assertNotEqual(web_key, mcp_key)
            self.assertTrue(web_store.validate_access_key(web_key))
            self.assertTrue(mcp_store.validate_access_key(mcp_key))
            self.assertFalse(web_store.validate_access_key(mcp_key))
            self.assertFalse(mcp_store.validate_access_key(web_key))

    def test_mcp_enable_does_not_enable_web_or_share_its_key(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            manager = RemoteAccessManager(
                auth_store=web_store,
                mcp_auth_store=mcp_store,
            )
            with (
                patch.object(manager, "_start_remote_server", return_value=True),
                patch.object(manager, "_start_web_route", return_value={"ok": True}),
                patch.object(
                    manager,
                    "_web_status",
                    return_value={
                        "available": True,
                        "active": True,
                        "target": "remote",
                        "public_url": "https://sparkle.example.ts.net",
                    },
                ),
            ):
                result = manager.enable_mcp()

            self.assertTrue(result["ok"])
            self.assertFalse(web_store.is_enabled())
            self.assertTrue(mcp_store.is_enabled())
            self.assertTrue(mcp_store.validate_access_key(result["access_key"]))
            self.assertFalse(web_store.validate_access_key(result["access_key"]))

    def test_disabling_web_keeps_mcp_route_and_server_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_store.enable()
            mcp_store.enable()
            manager = RemoteAccessManager(
                auth_store=web_store,
                mcp_auth_store=mcp_store,
            )
            with (
                patch.object(manager, "_web_status", return_value={"available": True, "active": True, "target": "remote", "public_url": "https://sparkle.example.ts.net"}),
                patch.object(manager, "_stop_remote_server") as stop_server,
            ):
                result = manager.disable()

            self.assertTrue(result["ok"])
            self.assertFalse(web_store.is_enabled())
            self.assertTrue(mcp_store.is_enabled())
            stop_server.assert_not_called()

    def test_disabling_mcp_keeps_web_route_and_server_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_store.enable()
            mcp_store.enable()
            manager = RemoteAccessManager(
                auth_store=web_store,
                mcp_auth_store=mcp_store,
            )
            with (
                patch.object(manager, "_web_status", return_value={"available": True, "active": True, "target": "remote", "public_url": "https://sparkle.example.ts.net"}),
                patch.object(manager, "_stop_remote_server") as stop_server,
            ):
                result = manager.disable_mcp()

            self.assertTrue(result["ok"])
            self.assertTrue(web_store.is_enabled())
            self.assertFalse(mcp_store.is_enabled())
            stop_server.assert_not_called()

    def test_remote_mode_defaults_to_funnel_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remote-auth.json"
            store = AuthStore(path)
            self.assertEqual(store.get_remote_mode(), "funnel")
            store.set_remote_mode("serve")
            self.assertEqual(AuthStore(path).get_remote_mode(), "serve")
            with self.assertRaises(ValueError):
                store.set_remote_mode("invalid")

    def test_funnel_status_host_key_becomes_public_url(self):
        status = {
            "Web": {
                "sparkle.example.ts.net:443": {
                    "Handlers": {
                        "/": {
                            "Proxy": "http://127.0.0.1:8001",
                        }
                    }
                }
            }
        }
        self.assertEqual(
            _find_public_url(status),
            "https://sparkle.example.ts.net",
        )

    def test_funnel_status_hides_url_for_desktop_target(self):
        status = {
            "Web": {
                "sparkle.example.ts.net:443": {
                    "Handlers": {
                        "/": {
                            "Proxy": "http://127.0.0.1:8000",
                        }
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with patch.object(
                manager,
                "_run_cli",
                return_value=(True, json.dumps(status), ""),
            ):
                result = manager.funnel_status(force=True)
        self.assertEqual(result["target"], "main")
        self.assertIsNone(result["public_url"])

    def test_serve_web_status_selects_remote_port_when_desktop_route_also_exists(self):
        status = {
            "Web": {
                "sparkle.example.ts.net:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}},
                },
                f"sparkle.example.ts.net:{SERVE_WEB_HTTPS_PORT}": {
                    "Handlers": {"/": {"Proxy": REMOTE_TARGET}},
                },
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with patch.object(
                manager,
                "_run_cli",
                return_value=(True, json.dumps(status), ""),
            ):
                result = manager._serve_web_status()
        self.assertEqual(result["target"], "remote")
        self.assertEqual(
            result["public_url"],
            f"https://sparkle.example.ts.net:{SERVE_WEB_HTTPS_PORT}",
        )

    def test_serve_web_route_uses_dedicated_port_and_remote_gateway(self):
        inactive = {
            "available": True,
            "active": False,
            "target": None,
            "public_url": None,
        }
        active = {
            "available": True,
            "active": True,
            "target": "remote",
            "public_url": f"https://sparkle.example.ts.net:{SERVE_WEB_HTTPS_PORT}",
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with (
                patch.object(manager, "_serve_web_status", side_effect=[inactive, active]),
                patch.object(
                    manager,
                    "funnel_status",
                    return_value={"available": True, "active": False},
                ),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_serve_web_route()
        self.assertTrue(result["ok"])
        self.assertEqual(
            run_cli.call_args.args[0],
            ["serve", "--bg", f"--https={SERVE_WEB_HTTPS_PORT}", "--yes", REMOTE_TARGET],
        )

    def test_enable_replaces_sparkles_existing_desktop_funnel(self):
        current = {
            "available": True,
            "active": True,
            "target": "main",
            "public_url": "https://sparkle.example.ts.net",
        }
        remote = {
            "available": True,
            "active": True,
            "target": "remote",
            "public_url": "https://sparkle.example.ts.net",
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with (
                patch.object(manager, "funnel_status", side_effect=[current, remote]),
                patch.object(manager, "_prepare_serve_switch", return_value=(True, None)),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_funnel_route()
        self.assertTrue(result["ok"])
        self.assertEqual(run_cli.call_count, 2)
        self.assertEqual(run_cli.call_args_list[0].args[0], ["funnel", "reset"])
        self.assertEqual(
            run_cli.call_args_list[1].args[0],
            ["funnel", "--bg", "--https=443", "--yes", "http://127.0.0.1:8001"],
        )

    def test_trusted_session_survives_store_reload_without_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remote-auth.json"
            first = AuthStore(path)
            access_key = first.enable()
            result = first.login(access_key, trust_device=True, device_label="テスト端末")

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn(access_key, raw)
            self.assertNotIn(result["token"], raw)

            reloaded = AuthStore(path)
            record = reloaded.authenticate(result["token"])
            self.assertIsNotNone(record)
            self.assertTrue(record["persistent"])
            self.assertEqual(record["label"], "テスト端末")

    def test_wrong_key_rotate_and_revoke(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(Path(directory) / "remote-auth.json")
            access_key = store.enable()
            with self.assertRaises(InvalidAccessKey):
                store.login("wrong-key")

            session = store.login(access_key, trust_device=False)
            self.assertIsNotNone(store.authenticate(session["token"]))
            rotated = store.rotate_access_key()
            self.assertNotEqual(access_key, rotated)
            self.assertIsNone(store.authenticate(session["token"]))

            new_session = store.login(rotated, trust_device=True)
            store.revoke_all()
            self.assertIsNone(store.authenticate(new_session["token"]))

    def test_expired_session_is_removed_and_disable_invalidates_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remote-auth.json"
            store = AuthStore(path)
            access_key = store.enable()
            session = store.login(access_key)

            payload = json.loads(path.read_text(encoding="utf-8"))
            token_hash = next(iter(payload["sessions"]))
            payload["sessions"][token_hash]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps(payload), encoding="utf-8")

            reloaded = AuthStore(path)
            self.assertIsNone(reloaded.authenticate(session["token"]))
            reloaded.disable()
            with self.assertRaises(InvalidAccessKey):
                reloaded.login(access_key)


if __name__ == "__main__":
    unittest.main()
