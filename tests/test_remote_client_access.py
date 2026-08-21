import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from remote_auth import AuthStore
from remote_client import RemoteClient, RemoteResponse, RemoteStreamResponse
from remote_gateway import RemoteGateway
from remote_proxy import RemoteClientProxy, _rewrite_remote_payload, _stream_response_from_remote
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


class _RecordingRemoteClient:
    def __init__(self):
        self.paths = []
        self._active = 0
        self.max_active = 0
        self._counter_lock = threading.Lock()

    def is_enabled(self):
        return True

    def base_url(self):
        return "https://remote.example.test"

    def request(self, path, method="GET", body=b"", headers=None):
        with self._counter_lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.01)
            self.paths.append((path, method, body, headers or {}))
            return RemoteResponse(200, {"Content-Type": "application/json"}, b"[]")
        finally:
            with self._counter_lock:
                self._active -= 1


class _KeepAliveResponse:
    status = 200
    headers = {"Content-Type": "application/json"}
    will_close = False

    def read(self):
        return b"{}"


class _KeepAliveConnection:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.requests = []
        self.closed = False
        type(self).instances.append(self)

    def request(self, method, target, body=None, headers=None):
        self.requests.append((method, target))

    def getresponse(self):
        return _KeepAliveResponse()

    def close(self):
        self.closed = True


class RemoteClientAccessTests(unittest.TestCase):
    def test_remote_client_reuses_keep_alive_connection_per_worker(self):
        _KeepAliveConnection.instances.clear()
        with tempfile.TemporaryDirectory() as directory, patch(
            "remote_client.http.client.HTTPConnection", _KeepAliveConnection
        ):
            client = RemoteClient(Path(directory) / "remote.json")
            first = client._raw_request("http://remote.example.test/clips")
            second = client._raw_request("http://remote.example.test/tasks")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(_KeepAliveConnection.instances), 1)
        self.assertEqual(
            _KeepAliveConnection.instances[0].requests,
            [("GET", "/clips"), ("GET", "/tasks")],
        )

    def test_remote_proxy_allows_concurrent_reads(self):
        remote = _RecordingRemoteClient()
        proxy = RemoteClientProxy(remote)

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(
                lambda _: proxy._serialized_request("/clips", "GET", b"", {}),
                range(6),
            ))

        self.assertGreaterEqual(remote.max_active, 2)
        self.assertEqual(len(remote.paths), 6)

    def test_remote_proxy_serializes_mutations(self):
        remote = _RecordingRemoteClient()
        proxy = RemoteClientProxy(remote)

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(
                lambda _: proxy._serialized_request("/clips", "POST", b"{}", {}),
                range(6),
            ))

        self.assertEqual(remote.max_active, 1)
        self.assertEqual(len(remote.paths), 6)

    def test_remote_proxy_preserves_query_filters(self):
        app = FastAPI()
        remote = _RecordingRemoteClient()
        app.add_middleware(BaseHTTPMiddleware, dispatch=RemoteClientProxy(remote).dispatch)

        with TestClient(app) as client:
            self.assertEqual(client.get("/clips", params={"url": "https://example.test"}).status_code, 200)
            self.assertEqual(client.get("/projects", params={"done": "0"}).status_code, 200)
            self.assertEqual(client.get("/clips", params={"project_id": "7"}).status_code, 200)
            self.assertEqual(client.get("/tasks", params={"project_id": "7"}).status_code, 200)
            self.assertEqual(client.get("/notes", params={"project_id": "7"}).status_code, 200)

        paths = [item[0] for item in remote.paths]
        self.assertIn("/clips?url=https%3A%2F%2Fexample.test", paths)
        self.assertIn("/projects?done=0", paths)
        self.assertIn("/clips?project_id=7", paths)
        self.assertIn("/tasks?project_id=7", paths)
        self.assertIn("/notes?project_id=7", paths)

    def test_remote_profile_icon_url_is_rewritten_to_local_proxy_path(self):
        remote = _RecordingRemoteClient()
        payload = {
            "icon_url": "https://remote.example.test/uploads/profile/profile-icon.png",
            "picks": [
                {"thumbnail_url": "https://remote.example.test/uploads/thumb.png"},
            ],
        }

        rewritten = _rewrite_remote_payload(remote, payload, "/profile")

        self.assertEqual(rewritten["icon_url"], "/uploads/profile/profile-icon.png")
        self.assertEqual(rewritten["picks"][0]["thumbnail_url"], "/uploads/thumb.png")

    def test_stream_proxy_preserves_incremental_event_chunks(self):
        response = _stream_response_from_remote(
            RemoteStreamResponse(
                200,
                {"Content-Type": "text/event-stream", "Content-Length": "999"},
                iter((b"event: start\n\n", b"event: done\n\n")),
            )
        )

        async def collect():
            return [chunk async for chunk in response.body_iterator]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks, [b"event: start\n\n", b"event: done\n\n"])
        self.assertNotIn("content-length", {key.lower() for key in response.headers})

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
