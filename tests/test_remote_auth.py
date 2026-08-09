import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from remote_auth import AuthStore, InvalidAccessKey
from remote_runtime import RemoteAccessManager, _find_public_url


class RemoteAuthStoreTests(unittest.TestCase):
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
