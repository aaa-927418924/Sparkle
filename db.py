"""SQLite connection and schema setup for the clip-save backend."""

import sqlite3

from paths import get_app_data_dir

DB_PATH = get_app_data_dir() / "clips.db"


_WRITE_SQL_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "REPLACE",
    "CREATE",
    "ALTER",
    "DROP",
    "VACUUM",
    "REINDEX",
)


class TrackedConnection(sqlite3.Connection):
    """Mark write transactions so text exports stay in sync with the DB."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sparkle_dirty = False

    @staticmethod
    def _is_write(sql: str) -> bool:
        statement = sql.lstrip().upper()
        return statement.startswith(_WRITE_SQL_PREFIXES)

    def execute(self, sql, parameters=()):
        if self._is_write(sql):
            self._sparkle_dirty = True
        return super().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        if self._is_write(sql):
            self._sparkle_dirty = True
        return super().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script):
        if any(self._is_write(statement) for statement in sql_script.split(";")):
            self._sparkle_dirty = True
        return super().executescript(sql_script)

    def commit(self):
        was_dirty = self._sparkle_dirty
        super().commit()
        self._sparkle_dirty = False
        if was_dirty:
            from ai_export import request_export

            request_export()

    def rollback(self):
        super().rollback()
        self._sparkle_dirty = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    title         TEXT,
    thumbnail_url TEXT,
    comment       TEXT,
    category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_favorite   INTEGER NOT NULL DEFAULT 0,
    embedding     BLOB,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clip_tags (
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (clip_id, tag_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    is_done    INTEGER NOT NULL DEFAULT 0,
    clip_id    INTEGER REFERENCES clips(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    body        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS note_clips (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, clip_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    is_done     INTEGER NOT NULL DEFAULT 0,
    done_snapshot TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_clips (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    clip_id    INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, clip_id)
);

CREATE TABLE IF NOT EXISTS project_notes (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    note_id    INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, note_id)
);

CREATE TABLE IF NOT EXISTS task_notes (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, note_id)
);

CREATE INDEX IF NOT EXISTS idx_clips_category ON clips(category_id);
CREATE INDEX IF NOT EXISTS idx_clip_tags_tag  ON clip_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_tasks_clip    ON tasks(clip_id);
CREATE INDEX IF NOT EXISTS idx_note_clips_note ON note_clips(note_id);
CREATE INDEX IF NOT EXISTS idx_note_clips_clip ON note_clips(clip_id);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,
        factory=TrackedConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
    if "task_id" not in cols:
        conn.execute(
            "ALTER TABLE notes ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL"
        )

    task_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "due_date" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
    if "priority" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER")
    if "completed_at" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")

    clip_cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    if "clip_type" not in clip_cols:
        conn.execute("ALTER TABLE clips ADD COLUMN clip_type TEXT DEFAULT 'url'")
    if "file_ref" not in clip_cols:
        conn.execute("ALTER TABLE clips ADD COLUMN file_ref TEXT")
    if "file_size" not in clip_cols:
        conn.execute("ALTER TABLE clips ADD COLUMN file_size INTEGER")
    if "project_id" not in clip_cols:
        conn.execute("ALTER TABLE clips ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL")

    if "project_id" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL")

    note_cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
    if "project_id" not in note_cols:
        conn.execute("ALTER TABLE notes ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL")

    proj_cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "is_done" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN is_done INTEGER NOT NULL DEFAULT 0")
    if "done_snapshot" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN done_snapshot TEXT")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS project_clips (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
            PRIMARY KEY (project_id, clip_id)
        );
        CREATE TABLE IF NOT EXISTS project_notes (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            PRIMARY KEY (project_id, note_id)
        );
        CREATE TABLE IF NOT EXISTS task_notes (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            PRIMARY KEY (task_id, note_id)
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO project_clips(project_id, clip_id) "
        "SELECT project_id, id FROM clips WHERE project_id IS NOT NULL"
    )
    conn.execute(
        "INSERT OR IGNORE INTO project_notes(project_id, note_id) "
        "SELECT project_id, id FROM notes WHERE project_id IS NOT NULL"
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_notes(task_id, note_id) "
        "SELECT task_id, id FROM notes WHERE task_id IS NOT NULL"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_clips_clip ON project_clips(clip_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_notes_note ON project_notes(note_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_notes_note ON task_notes(note_id)")


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")
