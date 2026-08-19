from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_readonly import seed_database


ROOT = Path(__file__).resolve().parents[1]


class McpStdioProtocolTests(unittest.TestCase):
    def test_initialize_list_tools_and_call_over_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "clips.db"
            seed_database(db_path)

            async def run_protocol() -> tuple[str, list[str], dict]:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[str(ROOT / "mcp_server.py"), "--db-path", str(db_path)],
                    cwd=ROOT,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        listed = await session.list_tools()
                        called = await session.call_tool("search_clips", {"query": "Qwen"})
                        payload = json.loads(called.content[0].text)
                        return (
                            initialized.server_info.name,
                            [tool.name for tool in listed.tools],
                            payload,
                        )

            server_name, tool_names, payload = asyncio.run(run_protocol())
            self.assertEqual(server_name, "sparkle")
            self.assertIn("search_clips", tool_names)
            self.assertEqual(payload["items"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
