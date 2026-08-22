import sqlite3
import unittest

from fastapi import HTTPException

import routers
from db import _SCHEMA, _migrate


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    _migrate(connection)
    return connection


class ProjectDeletionTests(unittest.TestCase):
    def test_delete_preserves_records_and_removes_project_owned_rows(self):
        connection = make_connection()
        try:
            # Older databases may have created this link table without a
            # cascading foreign key. The delete route must not depend on the
            # current schema's ON DELETE CASCADE behavior.
            connection.execute("DROP TABLE project_clips")
            connection.execute(
                "CREATE TABLE project_clips ("
                "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT, "
                "clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE, "
                "PRIMARY KEY (project_id, clip_id)"
                ")"
            )
            connection.execute(
                "INSERT INTO projects(name, description) VALUES (?, ?)",
                ("削除対象", "説明"),
            )
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.test/clip", "共有クリップ", project_id),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)",
                ("共有メモ", "本文", project_id),
            )
            note_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO tasks(title, project_id) VALUES (?, ?)",
                ("共有タスク", project_id),
            )
            task_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.executemany(
                "INSERT INTO project_clips(project_id, clip_id) VALUES (?, ?)",
                [(project_id, clip_id)],
            )
            connection.executemany(
                "INSERT INTO project_notes(project_id, note_id) VALUES (?, ?)",
                [(project_id, note_id)],
            )
            connection.executemany(
                "INSERT INTO project_tasks(project_id, task_id) VALUES (?, ?)",
                [(project_id, task_id)],
            )
            connection.execute(
                "INSERT INTO project_assistant_messages(project_id, role, content) VALUES (?, ?, ?)",
                (project_id, "user", "削除テスト"),
            )
            connection.execute(
                "INSERT INTO project_assistant_action_proposals(id, project_id, operation, action_json) "
                "VALUES (?, ?, ?, ?)",
                ("proposal-delete-test", project_id, "create_note", "{}"),
            )
            connection.commit()

            routers.delete_project(project_id, connection)

            self.assertIsNone(
                connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            )
            for table, record_id in (("clips", clip_id), ("notes", note_id), ("tasks", task_id)):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table} WHERE id = ?", (record_id,)).fetchone()[0],
                    1,
                )
                self.assertIsNone(
                    connection.execute(f"SELECT project_id FROM {table} WHERE id = ?", (record_id,)).fetchone()[0]
                )
            for table in (
                "project_clips",
                "project_notes",
                "project_tasks",
                "project_assistant_messages",
                "project_assistant_action_proposals",
            ):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)).fetchone()[0],
                    0,
                )
        finally:
            connection.close()

    def test_delete_rolls_back_all_changes_when_parent_delete_fails(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("削除阻止対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.test/clip", "保持対象", project_id),
            )
            connection.execute(
                "CREATE TRIGGER prevent_project_delete BEFORE DELETE ON projects "
                "BEGIN SELECT RAISE(ABORT, 'test block'); END;"
            )
            connection.commit()

            with self.assertRaises(HTTPException) as raised:
                routers.delete_project(project_id, connection)

            self.assertEqual(raised.exception.status_code, 409)
            self.assertIsNotNone(
                connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            )
            self.assertEqual(
                connection.execute("SELECT project_id FROM clips WHERE project_id = ?", (project_id,)).fetchone()[0],
                project_id,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
