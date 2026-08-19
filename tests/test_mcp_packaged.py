from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path

import httpx2
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from tests.test_mcp_readonly import seed_database


ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SERVER = ROOT / "dist" / "SparkleMCP.exe"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PackagedMcpTests(unittest.TestCase):
    def test_packaged_exe_responds_over_stdio(self) -> None:
        self.assertTrue(PACKAGED_SERVER.is_file(), PACKAGED_SERVER)
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "clips.db"
            seed_database(db_path)

            async def run_protocol() -> tuple[str, dict]:
                parameters = StdioServerParameters(
                    command=str(PACKAGED_SERVER),
                    args=["--db-path", str(db_path)],
                    cwd=ROOT,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        result = await session.call_tool("search_clips", {"query": "Qwen"})
                        return initialized.server_info.name, json.loads(result.content[0].text)

            server_name, payload = asyncio.run(run_protocol())
            self.assertEqual(server_name, "sparkle")
            self.assertEqual(payload["items"][0]["id"], 1)

    def test_packaged_exe_responds_over_streamable_http(self) -> None:
        self.assertTrue(PACKAGED_SERVER.is_file(), PACKAGED_SERVER)
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "clips.db"
            seed_database(db_path)
            port = _free_port()
            token = "0123456789abcdef-packaged-token"

            async def run() -> dict:
                environment = {
                    **os.environ,
                    "SPARKLE_MCP_PUBLIC_URL": f"http://127.0.0.1:{port}/mcp",
                    "SPARKLE_MCP_TOKEN": token,
                }
                process = await asyncio.create_subprocess_exec(
                    str(PACKAGED_SERVER),
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--db-path",
                    str(db_path),
                    env=environment,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                client = httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {token}"}, timeout=10.0
                )
                try:
                    for _ in range(100):
                        try:
                            response = await client.get(
                                f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp"
                            )
                            if response.status_code == 200:
                                break
                        except Exception:
                            await asyncio.sleep(0.05)
                    else:
                        self.fail("Packaged Remote MCP server did not start")

                    async with streamable_http_client(
                        f"http://127.0.0.1:{port}/mcp", http_client=client
                    ) as streams:
                        read_stream, write_stream = streams[:2]
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            result = await session.call_tool("search_clips", {"query": "Qwen"})
                            return json.loads(result.content[0].text)
                finally:
                    await client.aclose()
                    if process.returncode is None:
                        process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)

            payload = asyncio.run(run())
            self.assertEqual(payload["items"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
