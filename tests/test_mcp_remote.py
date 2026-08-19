from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import uvicorn
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from remote_auth import AuthStore
from remote_gateway import RemoteGateway
from remote_mcp import build_remote_mcp_runtime
from tests.test_mcp_readonly import seed_database


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pkce(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


class RemoteMcpTests(unittest.TestCase):
    def test_remote_gateway_uses_mcp_store_separate_from_web_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            web_store = AuthStore(Path(directory) / "remote-auth.json")
            mcp_store = AuthStore(Path(directory) / "mcp-auth.json")
            web_key = web_store.enable()
            mcp_key = mcp_store.enable()
            gateway = RemoteGateway(
                FastAPI(),
                web_store,
                mcp_auth_store=mcp_store,
            )

            self.assertIs(gateway.mcp_auth_store, mcp_store)
            self.assertIs(gateway.mcp_runtime.auth_store, mcp_store)
            self.assertTrue(gateway.mcp_runtime.auth_store.validate_access_key(mcp_key))
            self.assertFalse(gateway.mcp_runtime.auth_store.validate_access_key(web_key))

    def test_remote_gateway_keeps_mcp_lifespan_and_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "clips.db"
            seed_database(db_path)
            auth_store = AuthStore(Path(directory) / "remote-auth.json")
            port = _free_port()
            runtime = build_remote_mcp_runtime(
                db_path=str(db_path),
                auth_store=auth_store,
                host="127.0.0.1",
                port=8001,
                public_url=f"http://127.0.0.1:{port}/mcp",
                static_token="0123456789abcdef-static-token",
            )
            main_app = FastAPI()
            gateway = RemoteGateway(main_app, auth_store, mcp_runtime=runtime)
            server = uvicorn.Server(
                uvicorn.Config(
                    gateway,
                    host="127.0.0.1",
                    port=port,
                    log_config=None,
                    access_log=False,
                )
            )

            async def run() -> int:
                task = asyncio.create_task(server.serve())
                client = httpx2.AsyncClient(timeout=10.0)
                try:
                    for _ in range(50):
                        try:
                            response = await client.get(f"http://127.0.0.1:{port}/health")
                            if response.status_code == 200:
                                break
                        except Exception:
                            await asyncio.sleep(0.05)
                    metadata = await client.get(
                        f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp"
                    )
                    self.assertEqual(metadata.status_code, 200)
                    denied = await client.post(
                        f"http://127.0.0.1:{port}/mcp",
                        content=b"{}",
                        headers={"content-type": "application/json"},
                    )
                    return denied.status_code
                finally:
                    await client.aclose()
                    server.should_exit = True
                    await task

            self.assertEqual(asyncio.run(run()), 401)

    def test_oauth_and_streamable_http_read_only_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "clips.db"
            seed_database(db_path)
            auth_store = AuthStore(Path(directory) / "remote-auth.json")
            access_key = auth_store.enable()
            port = _free_port()
            runtime = build_remote_mcp_runtime(
                db_path=str(db_path),
                auth_store=auth_store,
                host="127.0.0.1",
                port=port,
                public_url=f"http://127.0.0.1:{port}/mcp",
                static_token="0123456789abcdef-static-token",
            )
            config = uvicorn.Config(
                runtime.app,
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
            )
            server = uvicorn.Server(config)

            async def run() -> tuple[str, dict, list[str]]:
                task = asyncio.create_task(server.serve())
                client = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
                try:
                    for _ in range(50):
                        try:
                            probe = await client.get(f"http://127.0.0.1:{port}/health")
                            if probe.status_code in {404, 405}:
                                break
                        except Exception:
                            await asyncio.sleep(0.05)
                    metadata = await client.get(
                        f"http://127.0.0.1:{port}/.well-known/oauth-authorization-server"
                    )
                    self.assertEqual(metadata.status_code, 200)

                    registration = await client.post(
                        f"http://127.0.0.1:{port}/oauth/register",
                        json={
                            "client_name": "Sparkle test client",
                            "redirect_uris": ["http://127.0.0.1:9876/callback"],
                            "token_endpoint_auth_method": "none",
                        },
                    )
                    self.assertEqual(registration.status_code, 201)
                    client_info = registration.json()
                    verifier = "test-verifier-012345678901234567890123456789"
                    authorize = await client.get(
                        f"http://127.0.0.1:{port}/oauth/authorize",
                        params={
                            "response_type": "code",
                            "client_id": client_info["client_id"],
                            "redirect_uri": "http://127.0.0.1:9876/callback",
                            "code_challenge": _pkce(verifier),
                            "code_challenge_method": "S256",
                            "state": "state-1",
                            "scope": "sparkle.read",
                            "resource": f"http://127.0.0.1:{port}/mcp",
                        },
                    )
                    self.assertEqual(authorize.status_code, 200)
                    request_id = re.search(r'name="request_id" value="([^"]+)"', authorize.text).group(1)
                    form_token = re.search(r'name="form_token" value="([^"]+)"', authorize.text).group(1)
                    approved = await client.post(
                        f"http://127.0.0.1:{port}/oauth/approve",
                        data={
                            "request_id": request_id,
                            "form_token": form_token,
                            "access_key": access_key,
                        },
                    )
                    self.assertEqual(approved.status_code, 303)
                    redirect = urlsplit(approved.headers["location"])
                    callback = parse_qs(redirect.query)
                    self.assertEqual(callback["state"], ["state-1"])

                    token_response = await client.post(
                        f"http://127.0.0.1:{port}/oauth/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": client_info["client_id"],
                            "redirect_uri": "http://127.0.0.1:9876/callback",
                            "code": callback["code"][0],
                            "code_verifier": verifier,
                        },
                    )
                    self.assertEqual(token_response.status_code, 200, token_response.text)
                    token = token_response.json()["access_token"]

                    no_auth = await client.post(
                        f"http://127.0.0.1:{port}/mcp",
                        content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                        headers={"content-type": "application/json"},
                    )
                    self.assertEqual(no_auth.status_code, 401)

                    mcp_client = httpx2.AsyncClient(
                        headers={"Authorization": f"Bearer {token}"}, timeout=10.0
                    )
                    try:
                        async with streamable_http_client(
                            f"http://127.0.0.1:{port}/mcp", http_client=mcp_client
                        ) as streams:
                            read_stream, write_stream = streams[:2]
                            async with ClientSession(read_stream, write_stream) as session:
                                initialized = await session.initialize()
                                tools = await session.list_tools()
                                result = await session.call_tool("search_clips", {"query": "Qwen"})
                                payload = json.loads(result.content[0].text)
                                return (
                                    initialized.server_info.name,
                                    payload,
                                    [tool.name for tool in tools.tools],
                                )
                    finally:
                        await mcp_client.aclose()
                finally:
                    await client.aclose()
                    server.should_exit = True
                    await task

            server_name, payload, tool_names = asyncio.run(run())
            self.assertEqual(server_name, "sparkle")
            self.assertEqual(payload["items"][0]["id"], 1)
            self.assertIn("search_clips", tool_names)


if __name__ == "__main__":
    unittest.main()
