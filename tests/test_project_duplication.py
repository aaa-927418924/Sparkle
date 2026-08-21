import sqlite3
import unittest

import routers
from db import _SCHEMA, _migrate


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    _migrate(connection)
    return connection


class ProjectDuplicationTests(unittest.TestCase):
    def test_duplicate_reuses_attached_records_and_preserves_shared_task_links(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name, description) VALUES (?, ?)", ("元プロジェクト", "説明"))
            source_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO clips(url, title) VALUES (?, ?)", ("https://example.test/clip", "共有クリップ"))
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO notes(title, body) VALUES (?, ?)", ("共有メモ", "本文"))
            note_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO tasks(title) VALUES (?)", ("共有タスク",))
            task_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO project_clips(project_id, clip_id) VALUES (?, ?)", (source_id, clip_id))
            connection.execute("INSERT INTO project_notes(project_id, note_id) VALUES (?, ?)", (source_id, note_id))
            connection.execute("INSERT INTO project_tasks(project_id, task_id) VALUES (?, ?)", (source_id, task_id))
            connection.commit()

            duplicate = routers.duplicate_project(source_id, connection)
            duplicate_id = duplicate.id

            self.assertNotEqual(source_id, duplicate_id)
            self.assertEqual(duplicate.name, "元プロジェクト（コピー）")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM clips").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM project_clips WHERE clip_id = ?", (clip_id,)).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM project_notes WHERE note_id = ?", (note_id,)).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM project_tasks WHERE task_id = ?", (task_id,)).fetchone()[0],
                2,
            )

            source_tasks = routers.list_tasks(done=None, project_id=source_id, exclude_project=None, db=connection)
            duplicate_tasks = routers.list_tasks(done=None, project_id=duplicate_id, exclude_project=None, db=connection)
            self.assertEqual([task.id for task in source_tasks], [task_id])
            self.assertEqual([task.id for task in duplicate_tasks], [task_id])
            self.assertEqual(set(duplicate_tasks[0].project_ids), {source_id, duplicate_id})
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
