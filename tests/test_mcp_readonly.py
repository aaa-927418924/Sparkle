from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mcp_server import build_server
from sparkle_mcp.readonly_db import read_connection
from sparkle_mcp.service import ToolService


SCHEMA = """
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE clips (
    id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT, thumbnail_url TEXT,
    comment TEXT, category_id INTEGER, is_favorite INTEGER NOT NULL DEFAULT 0,
    embedding BLOB, created_at TEXT NOT NULL, clip_type TEXT DEFAULT 'url',
    file_ref TEXT, file_size INTEGER, project_id INTEGER, is_folder INTEGER DEFAULT 0
);
CREATE TABLE clip_tags (clip_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY (clip_id, tag_id));
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, is_done INTEGER NOT NULL DEFAULT 0,
    clip_id INTEGER, created_at TEXT NOT NULL, due_date TEXT, priority INTEGER,
    completed_at TEXT, project_id INTEGER
);
CREATE TABLE notes (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT, is_done INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    task_id INTEGER, project_id INTEGER
);
CREATE TABLE note_clips (note_id INTEGER NOT NULL, clip_id INTEGER NOT NULL, PRIMARY KEY (note_id, clip_id));
CREATE TABLE projects (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT, is_done INTEGER NOT NULL DEFAULT 0,
    done_snapshot TEXT, notes_done_snapshot TEXT, created_at TEXT NOT NULL
);
CREATE TABLE project_clips (project_id INTEGER NOT NULL, clip_id INTEGER NOT NULL, PRIMARY KEY (project_id, clip_id));
CREATE TABLE project_notes (project_id INTEGER NOT NULL, note_id INTEGER NOT NULL, PRIMARY KEY (project_id, note_id));
CREATE TABLE project_tasks (project_id INTEGER NOT NULL, task_id INTEGER NOT NULL, PRIMARY KEY (project_id, task_id));
CREATE TABLE task_notes (task_id INTEGER NOT NULL, note_id INTEGER NOT NULL, PRIMARY KEY (task_id, note_id));
"""


def seed_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO categories(id, name) VALUES (?, ?)", [(1, "AI"), (2, "開発")])
        connection.executemany("INSERT INTO tags(id, name) VALUES (?, ?)", [(1, "Qwen"), (2, "LLM"), (3, "Python")])
        connection.executemany(
            """
            INSERT INTO projects(id, name, description, is_done, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, "MCP対応", "AIクライアント連携", 0, "2026-08-01 09:00:00"),
                (2, "完了プロジェクト", "完了済み", 1, "2026-07-01 09:00:00"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO clips(
                id, url, title, thumbnail_url, comment, category_id, is_favorite,
                created_at, clip_type, file_ref, file_size, project_id, is_folder
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "https://example.com/qwen",
                    "Qwenの評価記事",
                    "https://example.com/qwen.png",
                    "QwenとMCPについてのメモ",
                    1,
                    1,
                    "2026-08-10 10:00:00",
                    "url",
                    None,
                    None,
                    1,
                    0,
                ),
                (
                    2,
                    "https://example.com/python",
                    "Python記事",
                    None,
                    "SQLiteの読み取りについて",
                    2,
                    0,
                    "2026-08-09 10:00:00",
                    "url",
                    None,
                    None,
                    None,
                    0,
                ),
                (
                    3,
                    "local://reference/C:\\Users\\Test\\secret.pdf",
                    "ローカル資料",
                    None,
                    "秘密のファイルパスを含む資料",
                    None,
                    0,
                    "2026-08-08 10:00:00",
                    "local",
                    "reference",
                    123,
                    None,
                    0,
                ),
            ],
        )
        connection.executemany("INSERT INTO clip_tags(clip_id, tag_id) VALUES (?, ?)", [(1, 1), (1, 2), (2, 3)])
        connection.executemany(
            """
            INSERT INTO notes(id, title, body, is_done, created_at, updated_at, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "Qwenメモ", "Qwenの調査本文です。", 0, "2026-08-10 11:00:00", "2026-08-10 12:00:00", 1),
                (2, "完了メモ", "完了したメモ", 1, "2026-07-01 11:00:00", "2026-07-01 12:00:00", 2),
            ],
        )
        connection.executemany("INSERT INTO note_clips(note_id, clip_id) VALUES (?, ?)", [(1, 1), (2, 2)])
        connection.executemany(
            """
            INSERT INTO tasks(id, title, is_done, clip_id, created_at, due_date, priority, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "Qwenを確認", 0, 1, "2026-08-10 13:00:00", "2026-08-20 09:00:00", 3, 1),
                (2, "完了タスク", 1, 2, "2026-07-01 13:00:00", "2026-07-02 09:00:00", 1, 2),
            ],
        )
        connection.executemany("INSERT INTO project_clips(project_id, clip_id) VALUES (?, ?)", [(1, 1), (2, 2)])
        connection.executemany("INSERT INTO project_notes(project_id, note_id) VALUES (?, ?)", [(1, 1), (2, 2)])
        connection.executemany("INSERT INTO project_tasks(project_id, task_id) VALUES (?, ?)", [(1, 1), (2, 2)])
        connection.execute("INSERT INTO task_notes(task_id, note_id) VALUES (?, ?)", (1, 1))
        connection.commit()
    finally:
        connection.close()


class McpReadonlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "clips.db"
        seed_database(self.db_path)
        self.service = ToolService(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sqlite_connection_is_read_only(self) -> None:
        with read_connection(self.db_path) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO projects(name) VALUES ('must not write')")

    def test_clip_search_get_and_local_path_redaction(self) -> None:
        result = self.service.search_clips(query="Qwen", tags=["LLM"], favorite=True, limit=1)
        self.assertEqual([item["id"] for item in result["items"]], [1])
        self.assertEqual(result["items"][0]["projects"][0]["name"], "MCP対応")

        local_clip = self.service.get_clip(id=3)
        self.assertIsNone(local_clip["url"])
        self.assertTrue(local_clip["is_local"])
        self.assertEqual(local_clip["local_file_name"], "secret.pdf")
        self.assertNotIn("Users", json.dumps(local_clip, ensure_ascii=False))

    def test_cursor_pagination_and_all_record_types(self) -> None:
        first = self.service.search_clips(limit=1)
        self.assertEqual(len(first["items"]), 1)
        self.assertIsNotNone(first["next_cursor"])
        second = self.service.search_clips(limit=1, cursor=first["next_cursor"])
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])

        memo = self.service.search_memos(query="Qwen")["items"]
        self.assertEqual(memo[0]["id"], 1)
        self.assertIn("Qwen", self.service.get_memo(id=1)["body"])

        tasks = self.service.search_tasks(status="open", project_id=1)["items"]
        self.assertEqual([item["id"] for item in tasks], [1])
        self.assertEqual(self.service.get_task(id=1)["clip"]["id"], 1)
        priority_page = self.service.search_tasks(sort="priority_desc", limit=1)
        self.assertIsNotNone(priority_page["next_cursor"])
        priority_next = self.service.search_tasks(sort="priority_desc", limit=1, cursor=priority_page["next_cursor"])
        self.assertEqual(priority_page["items"][0]["id"], 1)
        self.assertEqual(priority_next["items"][0]["id"], 2)

        projects = self.service.search_projects(query="MCP")["items"]
        self.assertEqual(projects[0]["id"], 1)
        project = self.service.get_project(id=1)
        self.assertEqual(project["item_counts"], {"clips": 1, "memos": 1, "tasks": 1})
        items = self.service.list_project_items(project_id=1, limit=10)
        self.assertEqual([item["id"] for item in items["clips"]], [1])
        self.assertEqual([item["id"] for item in items["memos"]], [1])
        self.assertEqual([item["id"] for item in items["tasks"]], [1])

    def test_safe_errors(self) -> None:
        self.assertEqual(self.service.get_clip(id=999)["error"]["code"], "not_found")
        self.assertEqual(self.service.search_clips(limit=0)["error"]["code"], "invalid_input")
        self.assertEqual(self.service.get_project(id=999)["error"]["code"], "not_found")

    def test_mcp_protocol_tool_list_and_call(self) -> None:
        server = build_server(self.db_path)
        tools = asyncio.run(server.list_tools())
        self.assertEqual(
            {tool.name for tool in tools},
            {
                "search_clips",
                "get_clip",
                "search_memos",
                "get_memo",
                "search_tasks",
                "get_task",
                "search_projects",
                "get_project",
                "list_project_items",
            },
        )
        result = asyncio.run(server.call_tool("search_clips", {"query": "Qwen"}))
        self.assertFalse(result.is_error)
        payload = json.loads(result.content[0].text)
        self.assertEqual(payload["items"][0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
