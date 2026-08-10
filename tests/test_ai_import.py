import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ai_import import apply_project_clip_links, parse_projects_md


class ProjectMarkdownImportTests(unittest.TestCase):
    def test_parse_projects_md_reads_clip_ids_only_from_related_clip_field(self):
        text = """
# プロジェクト一覧

## [7] Web redesign
- 状態: 進行中
- 関連クリップ: [11] Design reference, [12] Another reference
- 関連ノート: [3] Notes
### 説明
```text
プロジェクトの説明
```
"""
        self.assertEqual(
            parse_projects_md(text),
            [{"id": 7, "clip_ids": [11, 12]}],
        )

    def test_apply_project_clip_links_is_additive_and_skips_unknown_ids(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE projects (id INTEGER PRIMARY KEY);
            CREATE TABLE clips (id INTEGER PRIMARY KEY, project_id INTEGER);
            CREATE TABLE project_clips (project_id INTEGER, clip_id INTEGER,
                PRIMARY KEY (project_id, clip_id));
            INSERT INTO projects(id) VALUES (7);
            INSERT INTO clips(id, project_id) VALUES (11, NULL);
            """
        )

        @contextmanager
        def get_test_connection():
            yield connection

        try:
            with patch("db.get_connection", get_test_connection):
                result = apply_project_clip_links(
                    [{"id": 7, "clip_ids": [11, 99]}]
                )

            self.assertEqual(result["project_links_applied"], 1)
            self.assertEqual(result["project_links_skipped"], 1)
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM project_clips WHERE project_id = 7 AND clip_id = 11"
                ).fetchone()
            )
            self.assertEqual(
                connection.execute("SELECT project_id FROM clips WHERE id = 11").fetchone()[0],
                7,
            )

            with patch("db.get_connection", get_test_connection):
                repeat = apply_project_clip_links(
                    [{"id": 7, "clip_ids": [11]}]
                )
            self.assertEqual(repeat["project_links_applied"], 0)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
