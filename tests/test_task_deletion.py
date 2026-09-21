import sqlite3
import unittest

import routers
from command_palette import ensure_search_schema
from db import _SCHEMA, _migrate


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    _migrate(connection)
    ensure_search_schema(connection)
    return connection


class TaskDeletionTests(unittest.TestCase):
    def test_delete_task_detaches_note_relationships_before_deleting(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO tasks(title) VALUES (?)", ("削除対象タスク",))
            target_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO tasks(title) VALUES (?)", ("保持するタスク",))
            survivor_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO notes(title, body, task_id) VALUES (?, ?, ?)",
                ("関連メモ", "本文", target_id),
            )
            note_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO task_notes(task_id, note_id) VALUES (?, ?)",
                (target_id, note_id),
            )
            connection.commit()

            routers.delete_task(target_id, connection)

            self.assertIsNone(
                connection.execute("SELECT id FROM tasks WHERE id = ?", (target_id,)).fetchone()
            )
            self.assertIsNotNone(
                connection.execute("SELECT id FROM tasks WHERE id = ?", (survivor_id,)).fetchone()
            )
            self.assertIsNone(
                connection.execute("SELECT task_id FROM notes WHERE id = ?", (note_id,)).fetchone()[0]
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM task_notes WHERE task_id = ?", (target_id,)
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                1,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
