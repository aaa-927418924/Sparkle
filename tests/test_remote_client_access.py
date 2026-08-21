import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from remote_auth import AuthStore
from remote_gateway import RemoteGateway
from remote_runtime import (
    CLIENT_SERVE_HTTPS_PORT,
    MCP_FUNNEL_HTTPS_PORT,
    REMOTE_TARGET,
    RemoteAccessManager,
)


class _NoMcpRuntime:
    def handles_path(self, path):
        return False

    @property
    def app(self):
        return self

    @asynccontextmanager
    async def lifespan_context(self):
        yield

    async def __call__(self, scope, receive, send):
        await JSONResponse({"detail": "not found"}, status_code=404)(scope, receive, send)


class RemoteClientAccessTests(unittest.TestCase):
    def test_client_key_and_bearer_session_protect_full_data_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = FastAPI()

            @root.get("/clips")
            def clips():
                return [{"id": 1, "title": "remote"}]

            @root.post("/clips")
            def create_clip():
                return {"ok": True}

            web_store = AuthStore(Path(directory) / "web.json")
            client_store = AuthStore(Path(directory) / "client.json")
            client_key = client_store.enable()
            gateway = RemoteGateway(
                root,
                web_store,
                client_auth_store=client_store,
                mcp_runtime=_NoMcpRuntime(),
            )

            with TestClient(gateway) as client:
                self.assertEqual(client.get("/clips").status_code, 401)
                login = client.post(
                    "/remote-client/login",
                    json={"access_key": client_key, "device_label": "test"},
                )
                self.assertEqual(login.status_code, 200)
                token = login.json()["token"]
                status = client.get(
                    "/remote-client/status",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertTrue(status.json()["authenticated"])
                response = client.get(
                    "/clips",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()[0]["title"], "remote")
                self.assertEqual(
                    client.get(
                        "/dialog/open-files",
                        headers={"Authorization": f"Bearer {token}"},
                    ).status_code,
                    404,
                )
                self.assertEqual(
                    client.post(
                        "/clips/local/reference",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"file_path": "C:/client-only/file.mp4"},
                    ).status_code,
                    404,
                )

    def test_client_serve_route_is_separate_from_android_route(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "web.json")
            client_store = AuthStore(Path(directory) / "client.json")
            client_store.enable()
            client_store.set_remote_mode("serve")
            manager = RemoteAccessManager(
                auth_store=web_store,
                client_auth_store=client_store,
            )
            inactive = {"available": True, "active": False, "target": None, "public_url": None}
            active = {
                "available": True,
                "active": True,
                "target": "remote",
                "public_url": "https://sparkle.example.ts.net:8444",
            }
            manager._port_status = lambda port: inactive
            manager._status_for_target = lambda command, target, port: active
            manager._run_cli = lambda args, timeout=30.0: (True, "", "")
            result = manager._start_client_route()
            self.assertTrue(result["ok"])
            self.assertEqual(CLIENT_SERVE_HTTPS_PORT, 8444)
            self.assertEqual(REMOTE_TARGET, "http://127.0.0.1:8001")

    def test_shutdown_stops_shared_funnel_for_client_only_combination(self):
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "web.json")
            client_store = AuthStore(Path(directory) / "client.json")
            web_store.enable()
            client_store.enable()
            manager = RemoteAccessManager(
                auth_store=web_store,
                client_auth_store=client_store,
            )
            current = {
                "available": True,
                "active": True,
                "target": "remote",
                "public_url": "https://sparkle.example.ts.net",
            }
            with (
                patch.object(manager, "_port_status", return_value=current),
                patch.object(manager, "_stop_route") as stop_route,
                patch.object(manager, "_stop_remote_server"),
            ):
                manager.shutdown()

            stop_route.assert_called_once_with(
                "funnel",
                REMOTE_TARGET,
                MCP_FUNNEL_HTTPS_PORT,
                current,
            )


if __name__ == "__main__":
    unittest.main()
