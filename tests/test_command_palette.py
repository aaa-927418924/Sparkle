import sqlite3
import tempfile
import unittest
from pathlib import Path

from command_palette import (
    CommandPaletteSearchRequest,
    _heuristic_intent,
    _model_payload_to_intent,
    _resolve_model_files,
    search_command_palette,
)
from db import _SCHEMA, _migrate


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    _migrate(connection)
    return connection


class CommandPaletteTests(unittest.TestCase):
    def test_gguf_file_is_resolved_from_model_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "another-Q4.gguf").touch()
            preferred = model_dir / "LFM2.5-350M-Q6_K.gguf"
            preferred.touch()

            resolved_dir, gguf_file = _resolve_model_files(str(model_dir))

            self.assertEqual(resolved_dir, model_dir)
            self.assertEqual(gguf_file, preferred.name)

    def test_model_payload_normalizes_entities_and_empty_filters(self):
        intent = _model_payload_to_intent(
            {
                "entity_types": ["tasks", "pending", "notes"],
                "text_query": "映像編集",
                "is_done": "false",
                "is_favorite": "",
                "due_from": "",
                "due_to": None,
                "project_name": "",
                "category": None,
                "tag": "",
                "limit": 99,
            }
        )

        self.assertIsNotNone(intent)
        self.assertEqual(intent.entity_types, ["task", "note"])
        self.assertFalse(intent.is_done)
        self.assertIsNone(intent.due_from)
        self.assertEqual(intent.limit, 50)

    def test_heuristic_parses_japanese_task_filters(self):
        intent = _heuristic_intent("今週の未完了タスク")

        self.assertEqual(intent.entity_types, ["task"])
        self.assertFalse(intent.is_done)
        self.assertIsNotNone(intent.due_from)
        self.assertIsNotNone(intent.due_to)
        self.assertEqual(intent.text_query, "")

    def test_search_spans_clips_notes_tasks_and_projects(self):
        connection = make_connection()
        try:
            connection.execute(
                "INSERT INTO projects(name, description) VALUES (?, ?)",
                ("映像編集", "公開用の制作プロジェクト"),
            )
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, comment, project_id) VALUES (?, ?, ?, ?)",
                ("https://example.com/clip", "編集の参考クリップ", "映像編集の資料", project_id),
            )
            connection.execute(
                "INSERT INTO tasks(title, project_id) VALUES (?, ?)",
                ("映像編集を確認", project_id),
            )
            connection.execute(
                "INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)",
                ("編集メモ", "映像編集の手順", project_id),
            )
            connection.commit()

            response = search_command_palette(
                connection,
                CommandPaletteSearchRequest(query="映像編集", use_ai=False, limit=20),
            )

            self.assertIn(response.search_mode, {"fts+like", "like"})
            self.assertEqual(
                {item.entity_type for item in response.results},
                {"clip", "note", "task", "project"},
            )
            targets = {item.entity_type: item.target for item in response.results}
            self.assertTrue(targets["clip"].startswith("/Home?clip_id="))
            self.assertTrue(targets["note"].startswith("/Note?id="))
            self.assertTrue(targets["task"].startswith("/Notes?task_id="))
            self.assertTrue(targets["project"].startswith("/Projects?id="))
        finally:
            connection.close()

    def test_negative_favorite_filter_keeps_entities_without_favorite_field(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO tasks(title) VALUES (?)", ("未お気に入りタスク",))
            connection.commit()

            response = search_command_palette(
                connection,
                CommandPaletteSearchRequest(query="お気に入りでないタスク", use_ai=False),
            )

            self.assertEqual([item.entity_type for item in response.results], ["task"])
        finally:
            connection.close()

    def test_source_updates_mark_the_index_dirty(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO tasks(title) VALUES (?)", ("古いタスク名",))
            connection.commit()
            search_command_palette(
                connection,
                CommandPaletteSearchRequest(query="古いタスク名", use_ai=False),
            )

            connection.execute(
                "UPDATE tasks SET title = ? WHERE title = ?",
                ("新しいタスク名", "古いタスク名"),
            )
            connection.commit()
            response = search_command_palette(
                connection,
                CommandPaletteSearchRequest(query="新しいタスク名", use_ai=False),
            )

            self.assertEqual(response.total, 1)
            self.assertEqual(response.results[0].title, "新しいタスク名")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
