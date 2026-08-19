from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_readonly import seed_database


ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SERVER = ROOT / "dist" / "SparkleMCP.exe"


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


if __name__ == "__main__":
    unittest.main()
