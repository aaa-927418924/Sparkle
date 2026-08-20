import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from remote_auth import AuthStore, InvalidAccessKey
from remote_runtime import (
    ANDROID_WEB_HTTPS_PORT,
    MCP_FUNNEL_HTTPS_PORT,
    REMOTE_TARGET,
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
                patch.object(manager, "_start_enabled_routes", return_value={"ok": True}),
                patch.object(
                    manager,
                    "_mcp_route_status",
                    return_value={
                        "available": True,
                        "active": True,
                        "target": "remote",
                        "public_url": f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}",
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
                patch.object(manager, "_stop_public_route", return_value=(True, None)) as stop_route,
                patch.object(manager, "_mcp_route_status", return_value={"available": True, "active": True, "target": "remote", "public_url": f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}"}),
                patch.object(manager, "_stop_remote_server") as stop_server,
            ):
                result = manager.disable()

            self.assertTrue(result["ok"])
            self.assertFalse(web_store.is_enabled())
            self.assertTrue(mcp_store.is_enabled())
            stop_route.assert_called_once()
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
                patch.object(manager, "_stop_mcp_route", return_value=(True, None)) as stop_route,
                patch.object(manager, "_web_status", return_value={"available": True, "active": True, "target": "main", "public_url": "https://sparkle.example.ts.net"}),
                patch.object(manager, "_stop_remote_server") as stop_server,
            ):
                result = manager.disable_mcp()

            self.assertTrue(result["ok"])
            self.assertTrue(web_store.is_enabled())
            self.assertFalse(mcp_store.is_enabled())
            stop_route.assert_called_once()
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

    def test_serve_web_status_selects_android_port_when_mcp_route_also_exists(self):
        status = {
            "Web": {
                "sparkle.example.ts.net:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}},
                },
                f"sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}": {
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
        self.assertEqual(result["target"], "main")
        self.assertEqual(result["public_url"], "https://sparkle.example.ts.net")

    def test_serve_web_route_uses_443_and_main_app(self):
        inactive = {
            "available": True,
            "active": False,
            "target": None,
            "public_url": None,
        }
        active = {
            "available": True,
            "active": True,
            "target": "main",
            "public_url": "https://sparkle.example.ts.net",
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with (
                patch.object(manager, "_port_status", return_value=inactive),
                patch.object(manager, "_status_for_target", return_value=active),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_serve_web_route()
        self.assertTrue(result["ok"])
        self.assertEqual(
            run_cli.call_args.args[0],
            ["serve", "--bg", f"--https={ANDROID_WEB_HTTPS_PORT}", "--yes", "http://127.0.0.1:8000"],
        )

    def test_funnel_web_route_uses_443_without_global_reset(self):
        current = {
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
                patch.object(manager, "_port_status", return_value=current),
                patch.object(manager, "_status_for_target", return_value=current),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_funnel_route()
        self.assertTrue(result["ok"])
        self.assertEqual(run_cli.call_count, 1)
        self.assertEqual(run_cli.call_args.args[0], ["funnel", "--bg", "--https=443", "--yes", REMOTE_TARGET])

    def test_mcp_route_uses_funnel_web_443_by_default(self):
        inactive = {"available": True, "active": False, "target": None, "public_url": None}
        active = {
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
                patch.object(manager, "_port_status", return_value=inactive),
                patch.object(manager, "_status_for_target", return_value=active),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_mcp_route()
        self.assertTrue(result["ok"])
        self.assertEqual(
            run_cli.call_args.args[0],
            ["funnel", "--bg", f"--https={ANDROID_WEB_HTTPS_PORT}", "--yes", REMOTE_TARGET],
        )

    def test_mcp_route_uses_8443_when_serve_web_mode_is_selected(self):
        inactive = {"available": True, "active": False, "target": None, "public_url": None}
        active = {
            "available": True,
            "active": True,
            "target": "remote",
            "public_url": f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}",
        }
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            web_store.set_remote_mode("serve")
            manager = RemoteAccessManager(auth_store=web_store)
            with (
                patch.object(manager, "_port_status", return_value=inactive),
                patch.object(manager, "_status_for_target", return_value=active),
                patch.object(manager, "_run_cli", return_value=(True, "", "")) as run_cli,
            ):
                result = manager._start_mcp_route()
        self.assertTrue(result["ok"])
        self.assertEqual(
            run_cli.call_args.args[0],
            ["funnel", "--bg", f"--https={MCP_FUNNEL_HTTPS_PORT}", "--yes", REMOTE_TARGET],
        )

    def test_mcp_url_without_port_uses_funnel_web_443(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "remote-auth.json")
            )
            with patch.dict(os.environ, {"SPARKLE_MCP_PUBLIC_URL": "https://sparkle.example.ts.net/mcp"}):
                self.assertEqual(
                    manager._mcp_public_url({}),
                    "https://sparkle.example.ts.net/mcp",
                )

    def test_mcp_url_without_port_moves_to_8443_for_serve_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            web_store.set_remote_mode("serve")
            manager = RemoteAccessManager(auth_store=web_store)
            with patch.dict(os.environ, {"SPARKLE_MCP_PUBLIC_URL": "https://sparkle.example.ts.net/mcp"}):
                self.assertEqual(
                    manager._mcp_public_url({}),
                    "https://sparkle.example.ts.net:8443/mcp",
                )

    def test_mcp_configured_route_port_follows_web_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            funnel_manager = RemoteAccessManager(
                auth_store=AuthStore(Path(directory) / "funnel-auth.json")
            )
            serve_store = AuthStore(Path(directory) / "serve-auth.json")
            serve_store.set_remote_mode("serve")
            serve_manager = RemoteAccessManager(auth_store=serve_store)
            with patch.dict(
                os.environ,
                {"SPARKLE_MCP_PUBLIC_URL": "https://sparkle.example.ts.net:8443/mcp"},
            ):
                self.assertEqual(
                    funnel_manager._mcp_public_url({}),
                    "https://sparkle.example.ts.net/mcp",
                )
            with patch.dict(
                os.environ,
                {"SPARKLE_MCP_PUBLIC_URL": "https://sparkle.example.ts.net:443/mcp"},
            ):
                self.assertEqual(
                    serve_manager._mcp_public_url({}),
                    "https://sparkle.example.ts.net:8443/mcp",
                )

    def test_status_reports_web_and_mcp_routes_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_store.enable()
            web_store.set_remote_mode("serve")
            mcp_store.enable()
            manager = RemoteAccessManager(
                auth_store=web_store,
                mcp_auth_store=mcp_store,
            )
            web_route = {
                "available": True,
                "active": True,
                "target": "main",
                "public_url": "https://sparkle.example.ts.net",
            }
            mcp_route = {
                "available": True,
                "active": True,
                "target": "remote",
                "public_url": f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}",
            }
            with (
                patch.object(manager, "_web_status", return_value=web_route),
                patch.object(manager, "_mcp_route_status", return_value=mcp_route),
            ):
                status = manager.status()
        self.assertEqual(status["web_route"], web_route)
        self.assertEqual(status["android"], web_route)
        self.assertEqual(status["mcp_route"], mcp_route)
        self.assertEqual(status["remote"], mcp_route)
        self.assertEqual(status["mcp_url"], f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}/mcp")

    def test_switching_from_shared_funnel_to_serve_stops_443_before_starting_routes(self):
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
                patch.object(manager, "_stop_public_route", return_value=(True, None)) as stop_web,
                patch.object(manager, "_stop_route") as stop_mcp,
                patch.object(manager, "_stop_remote_server") as stop_server,
                patch.object(manager, "_start_remote_server", return_value=True) as start_server,
                patch.object(manager, "_start_enabled_routes", return_value={"ok": True}) as start_routes,
                patch.object(manager, "status", return_value={}),
            ):
                result = manager.set_mode("serve")

        self.assertTrue(result["ok"])
        self.assertEqual(web_store.get_remote_mode(), "serve")
        stop_web.assert_called_once_with(force=True)
        stop_mcp.assert_not_called()
        stop_server.assert_called_once()
        start_server.assert_called_once()
        start_routes.assert_called_once()

    def test_switching_from_serve_to_funnel_stops_serve_and_mcp_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_store.enable()
            web_store.set_remote_mode("serve")
            mcp_store.enable()
            manager = RemoteAccessManager(
                auth_store=web_store,
                mcp_auth_store=mcp_store,
            )
            current_mcp = {
                "available": True,
                "active": True,
                "target": "remote",
                "public_url": f"https://sparkle.example.ts.net:{MCP_FUNNEL_HTTPS_PORT}",
            }
            with (
                patch.object(manager, "_stop_public_route", return_value=(True, None)) as stop_web,
                patch.object(manager, "_port_status", return_value=current_mcp),
                patch.object(manager, "_stop_route", return_value=(True, None)) as stop_route,
                patch.object(manager, "_stop_remote_server") as stop_server,
                patch.object(manager, "_start_remote_server", return_value=True),
                patch.object(manager, "_start_enabled_routes", return_value={"ok": True}),
                patch.object(manager, "status", return_value={}),
            ):
                result = manager.set_mode("funnel")

        self.assertTrue(result["ok"])
        self.assertEqual(web_store.get_remote_mode(), "funnel")
        stop_web.assert_called_once_with(force=True)
        stop_route.assert_called_once_with(
            "funnel",
            REMOTE_TARGET,
            MCP_FUNNEL_HTTPS_PORT,
            current_mcp,
        )
        stop_server.assert_called_once()

    def test_reapplying_serve_mode_restarts_missing_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            web_store.enable()
            web_store.set_remote_mode("serve")
            manager = RemoteAccessManager(auth_store=web_store)
            with (
                patch.object(manager, "_start_remote_server", return_value=True) as start_server,
                patch.object(manager, "_start_enabled_routes", return_value={"ok": True}) as start_routes,
                patch.object(manager, "status", return_value={}),
            ):
                result = manager.set_mode("serve")

        self.assertTrue(result["ok"])
        start_server.assert_called_once()
        start_routes.assert_called_once()

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
