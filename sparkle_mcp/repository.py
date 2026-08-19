"""Read-only, parameterized data access used by every MCP transport."""

from __future__ import annotations

import base64
import hashlib
import json
import ntpath
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .readonly_db import read_connection
from .validation import McpInputError


class RecordNotFoundError(LookupError):
    """A requested Sparkle record does not exist."""

    def __init__(self, record_type: str, record_id: int):
        super().__init__(f"{record_type} with id {record_id} was not found.")
        self.record_type = record_type
        self.record_id = record_id


def _snippet(value: str | None, max_chars: int = 500) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


def _safe_url(url: str | None, clip_type: str | None) -> str | None:
    """Return a URL while never exposing local absolute paths to an AI client."""

    if not url:
        return None
    normalized = str(url)
    if (clip_type or "").casefold() == "local":
        return None
    if normalized.casefold().startswith(("local://", "file://")):
        return None
    if normalized.startswith(("\\\\", "/")) or (len(normalized) > 2 and normalized[1] == ":"):
        return None
    return normalized


def _is_local_clip(url: str | None, clip_type: str | None) -> bool:
    return (clip_type or "").casefold() == "local" or (url or "").casefold().startswith(("local://", "file://"))


def _local_file_name(url: str | None, clip_type: str | None) -> str | None:
    if not _is_local_clip(url, clip_type):
        return None
    candidate = str(url or "")
    if candidate.casefold().startswith("local://"):
        candidate = candidate[8:]
    candidate = candidate.replace("/", "\\")
    name = ntpath.basename(candidate)
    return name or None


def _safe_file_ref(value: str | None) -> str | None:
    if value in {"reference", "copy"}:
        return value
    return None


def _filter_token(kind: str, values: dict[str, Any]) -> str:
    encoded = json.dumps({"kind": kind, "values": values}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _encode_cursor(sort: str, token: str, value: Any, record_id: int) -> str:
    payload = {"v": 1, "sort": sort, "token": token, "value": value, "id": record_id}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, sort: str, token: str) -> tuple[Any, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if (
            payload.get("v") != 1
            or payload.get("sort") != sort
            or payload.get("token") != token
            or not isinstance(payload.get("value"), (str, int, float))
            or isinstance(payload.get("value"), bool)
            or not isinstance(payload.get("id"), int)
        ):
            raise ValueError
        return payload["value"], payload["id"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
        raise McpInputError("cursor is invalid or belongs to another search.", field="cursor", code="invalid_cursor") from exc


def _add_cursor_filter(
    where: list[str],
    params: list[Any],
    *,
    cursor: str | None,
    sort: str,
    token: str,
    value_expression: str,
    id_expression: str,
) -> None:
    if not cursor:
        return
    value, record_id = _decode_cursor(cursor, sort, token)
    descending = sort.endswith("_desc")
    operator = "<" if descending else ">"
    where.append(
        f"({value_expression} {operator} ? OR "
        f"({value_expression} = ? AND {id_expression} {operator} ?))"
    )
    params.extend([value, value, record_id])


def _page(
    rows: Sequence[sqlite3.Row],
    *,
    limit: int,
    sort: str,
    token: str,
    item_builder: Callable[[sqlite3.Row], dict[str, Any]],
) -> dict[str, Any]:
    has_more = len(rows) > limit
    visible = rows[:limit]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = _encode_cursor(sort, token, last["_sort_value"], int(last["id"]))
    return {
        "items": [item_builder(row) for row in visible],
        "next_cursor": next_cursor,
        "limit": limit,
    }


def _append_query(where: list[str], params: list[Any], query: str | None, expressions: Iterable[str]) -> None:
    if not query:
        return
    expressions = list(expressions)
    where.append("(" + " OR ".join(f"{expression} LIKE ? ESCAPE '\\' COLLATE NOCASE" for expression in expressions) + ")")
    params.extend([_like(query)] * len(expressions))


def _append_date_range(
    where: list[str],
    params: list[Any],
    expression: str,
    date_from: str | None,
    date_to: str | None,
) -> None:
    if date_from:
        where.append(f"COALESCE({expression}, '') >= ?")
        params.append(date_from)
    if date_to:
        where.append(f"COALESCE({expression}, '') <= ?")
        params.append(date_to)


class ReadRepository:
    """A small query-oriented facade over Sparkle's existing SQLite schema."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path).expanduser() if db_path is not None else None

    def _read(self, callback: Callable[[sqlite3.Connection], Any]) -> Any:
        with read_connection(self.db_path) as connection:
            return callback(connection)

    @staticmethod
    def _clip_select(alias: str = "c") -> str:
        return f"""
            {alias}.id,
            {alias}.url,
            {alias}.title,
            {alias}.thumbnail_url,
            {alias}.comment,
            {alias}.category_id,
            {alias}.is_favorite,
            {alias}.created_at,
            COALESCE({alias}.clip_type, 'url') AS clip_type,
            {alias}.file_ref,
            {alias}.file_size,
            COALESCE({alias}.is_folder, 0) AS is_folder
        """

    @staticmethod
    def _category(connection: sqlite3.Connection, category_id: int | None) -> dict[str, Any] | None:
        if category_id is None:
            return None
        row = connection.execute("SELECT id, name FROM categories WHERE id = ?", (category_id,)).fetchone()
        return {"id": int(row["id"]), "name": row["name"]} if row else None

    @staticmethod
    def _tags_for_clip(connection: sqlite3.Connection, clip_id: int) -> list[str]:
        rows = connection.execute(
            """
            SELECT t.name
            FROM tags t
            JOIN clip_tags ct ON ct.tag_id = t.id
            WHERE ct.clip_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (clip_id,),
        ).fetchall()
        return [str(row["name"]) for row in rows]

    @staticmethod
    def _project_ids_for_clip(connection: sqlite3.Connection, clip_id: int) -> list[int]:
        rows = connection.execute(
            """
            SELECT project_id FROM project_clips WHERE clip_id = ?
            UNION
            SELECT project_id FROM clips WHERE id = ? AND project_id IS NOT NULL
            ORDER BY project_id
            """,
            (clip_id, clip_id),
        ).fetchall()
        return [int(row["project_id"]) for row in rows if row["project_id"] is not None]

    @staticmethod
    def _project_ids_for_note(connection: sqlite3.Connection, note_id: int) -> list[int]:
        rows = connection.execute(
            """
            SELECT project_id FROM project_notes WHERE note_id = ?
            UNION
            SELECT project_id FROM notes WHERE id = ? AND project_id IS NOT NULL
            ORDER BY project_id
            """,
            (note_id, note_id),
        ).fetchall()
        return [int(row["project_id"]) for row in rows if row["project_id"] is not None]

    @staticmethod
    def _project_refs(connection: sqlite3.Connection, project_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not project_ids:
            return []
        placeholders = ",".join("?" for _ in project_ids)
        rows = connection.execute(
            f"SELECT id, name, is_done, created_at FROM projects WHERE id IN ({placeholders}) ORDER BY name COLLATE NOCASE, id",
            tuple(project_ids),
        ).fetchall()
        return [
            {"id": int(row["id"]), "name": row["name"], "is_done": _bool(row["is_done"]), "created_at": row["created_at"]}
            for row in rows
        ]

    @classmethod
    def _clip_ref(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        clip_type = row["clip_type"] or "url"
        url = _safe_url(row["url"], clip_type)
        result: dict[str, Any] = {
            "id": int(row["id"]),
            "title": row["title"],
            "url": url,
            "clip_type": clip_type,
            "is_local": _is_local_clip(row["url"], clip_type),
            "local_file_name": _local_file_name(row["url"], clip_type),
            "tags": cls._tags_for_clip(connection, int(row["id"])),
        }
        return result

    @classmethod
    def _clip_summary(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        clip_type = row["clip_type"] or "url"
        project_ids = cls._project_ids_for_clip(connection, int(row["id"]))
        category = cls._category(connection, row["category_id"])
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "summary": _snippet(row["comment"]),
            "url": _safe_url(row["url"], clip_type),
            "tags": cls._tags_for_clip(connection, int(row["id"])),
            "category": category["name"] if category else None,
            "project_ids": project_ids,
            "projects": cls._project_refs(connection, project_ids),
            "created_at": row["created_at"],
            "is_favorite": _bool(row["is_favorite"]),
            "clip_type": clip_type,
            "is_local": _is_local_clip(row["url"], clip_type),
            "local_file_name": _local_file_name(row["url"], clip_type),
        }

    @classmethod
    def _clip_detail(cls, connection: sqlite3.Connection, row: sqlite3.Row, max_chars: int) -> dict[str, Any]:
        clip_type = row["clip_type"] or "url"
        project_ids = cls._project_ids_for_clip(connection, int(row["id"]))
        tasks = connection.execute(
            "SELECT id, title, is_done, due_date, priority, created_at FROM tasks WHERE clip_id = ? ORDER BY is_done, created_at DESC, id DESC LIMIT 50",
            (int(row["id"]),),
        ).fetchall()
        memos = connection.execute(
            """
            SELECT n.id, n.title, n.is_done, n.created_at, n.updated_at
            FROM notes n JOIN note_clips nc ON nc.note_id = n.id
            WHERE nc.clip_id = ? ORDER BY n.updated_at DESC, n.id DESC LIMIT 50
            """,
            (int(row["id"]),),
        ).fetchall()
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "url": _safe_url(row["url"], clip_type),
            "thumbnail_url": _safe_url(row["thumbnail_url"], "url"),
            "comment": _snippet(row["comment"], max_chars),
            "summary": _snippet(row["comment"], max_chars),
            "tags": cls._tags_for_clip(connection, int(row["id"])),
            "category": cls._category(connection, row["category_id"]),
            "projects": cls._project_refs(connection, project_ids),
            "project_ids": project_ids,
            "created_at": row["created_at"],
            "is_favorite": _bool(row["is_favorite"]),
            "clip_type": clip_type,
            "file_ref": _safe_file_ref(row["file_ref"]),
            "file_size": row["file_size"],
            "is_folder": _bool(row["is_folder"]),
            "is_local": clip_type.casefold() == "local",
            "local_file_name": _local_file_name(row["url"], clip_type),
            "related_tasks": [
                {
                    "id": int(task["id"]),
                    "title": task["title"],
                    "is_done": _bool(task["is_done"]),
                    "due_date": task["due_date"],
                    "priority": task["priority"],
                    "created_at": task["created_at"],
                }
                for task in tasks
            ],
            "related_memos": [
                {
                    "id": int(memo["id"]),
                    "title": memo["title"],
                    "is_done": _bool(memo["is_done"]),
                    "created_at": memo["created_at"],
                    "updated_at": memo["updated_at"],
                }
                for memo in memos
            ],
        }

    def search_clips(
        self,
        *,
        query: str | None,
        tags: list[str],
        tag_mode: str,
        category: str | None,
        project_id: int | None,
        project_query: str | None,
        favorite: bool | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        cursor: str | None,
        sort: str,
    ) -> dict[str, Any]:
        token = _filter_token(
            "clips",
            {
                "query": query,
                "tags": tags,
                "tag_mode": tag_mode,
                "category": category,
                "project_id": project_id,
                "project_query": project_query,
                "favorite": favorite,
                "date_from": date_from,
                "date_to": date_to,
                "sort": sort,
            },
        )

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            where = ["1 = 1"]
            params: list[Any] = []
            if query:
                search = _like(query)
                where.append(
                    "(COALESCE(c.title, '') LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR COALESCE(c.url, '') LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR COALESCE(c.comment, '') LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR COALESCE(cat.name, '') LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR EXISTS (SELECT 1 FROM clip_tags qct JOIN tags qt ON qt.id = qct.tag_id WHERE qct.clip_id = c.id AND qt.name LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                    "OR EXISTS (SELECT 1 FROM project_clips qpc JOIN projects qp ON qp.id = qpc.project_id WHERE qpc.clip_id = c.id AND qp.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
                )
                params.extend([search] * 6)
            if category:
                where.append("LOWER(COALESCE(cat.name, '')) = LOWER(?)")
                params.append(category)
            if favorite is not None:
                where.append("c.is_favorite = ?")
                params.append(1 if favorite else 0)
            if tags:
                if tag_mode == "all":
                    for tag in tags:
                        where.append(
                            "EXISTS (SELECT 1 FROM clip_tags fct JOIN tags ft ON ft.id = fct.tag_id WHERE fct.clip_id = c.id AND LOWER(ft.name) = LOWER(?))"
                        )
                        params.append(tag)
                else:
                    placeholders = ",".join("LOWER(?)" for _ in tags)
                    where.append(
                        f"EXISTS (SELECT 1 FROM clip_tags fct JOIN tags ft ON ft.id = fct.tag_id WHERE fct.clip_id = c.id AND LOWER(ft.name) IN ({placeholders}))"
                    )
                    params.extend(tags)
            if project_id is not None:
                where.append(
                    "(c.project_id = ? OR EXISTS (SELECT 1 FROM project_clips fpc WHERE fpc.clip_id = c.id AND fpc.project_id = ?))"
                )
                params.extend([project_id, project_id])
            if project_query:
                where.append(
                    "(EXISTS (SELECT 1 FROM projects fpd WHERE fpd.id = c.project_id AND fpd.name LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                    "OR EXISTS (SELECT 1 FROM project_clips fpcl JOIN projects fp ON fp.id = fpcl.project_id WHERE fpcl.clip_id = c.id AND fp.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
                )
                params.extend([_like(project_query), _like(project_query)])
            _append_date_range(where, params, "c.created_at", date_from, date_to)

            sort_map = {
                "created_desc": ("COALESCE(c.created_at, '')", "COALESCE(c.created_at, '') DESC, c.id DESC"),
                "created_asc": ("COALESCE(c.created_at, '')", "COALESCE(c.created_at, '') ASC, c.id ASC"),
                "title_asc": ("LOWER(COALESCE(c.title, ''))", "LOWER(COALESCE(c.title, '')) ASC, c.id ASC"),
                "title_desc": ("LOWER(COALESCE(c.title, ''))", "LOWER(COALESCE(c.title, '')) DESC, c.id DESC"),
            }
            value_expression, ordering = sort_map[sort]
            _add_cursor_filter(
                where,
                params,
                cursor=cursor,
                sort=sort,
                token=token,
                value_expression=value_expression,
                id_expression="c.id",
            )
            rows = connection.execute(
                f"""
                SELECT {self._clip_select('c')}, {value_expression} AS _sort_value
                FROM clips c
                LEFT JOIN categories cat ON cat.id = c.category_id
                WHERE {' AND '.join(where)}
                ORDER BY {ordering}
                LIMIT ?
                """,
                (*params, limit + 1),
            ).fetchall()
            return _page(rows, limit=limit, sort=sort, token=token, item_builder=lambda row: self._clip_summary(connection, row))

        return self._read(read)

    def get_clip(self, record_id: int, *, max_chars: int) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                f"SELECT {self._clip_select('c')} FROM clips c WHERE c.id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError("clip", record_id)
            return self._clip_detail(connection, row, max_chars)

        return self._read(read)

    @staticmethod
    def _note_clip_rows(connection: sqlite3.Connection, note_id: int) -> list[sqlite3.Row]:
        return connection.execute(
            f"""
            SELECT {ReadRepository._clip_select('c')}
            FROM clips c JOIN note_clips nc ON nc.clip_id = c.id
            WHERE nc.note_id = ? ORDER BY c.created_at DESC, c.id DESC
            """,
            (note_id,),
        ).fetchall()

    @classmethod
    def _note_tags(cls, connection: sqlite3.Connection, note_id: int) -> list[str]:
        rows = connection.execute(
            """
            SELECT DISTINCT t.name
            FROM tags t
            JOIN clip_tags ct ON ct.tag_id = t.id
            JOIN note_clips nc ON nc.clip_id = ct.clip_id
            WHERE nc.note_id = ? ORDER BY t.name COLLATE NOCASE
            """,
            (note_id,),
        ).fetchall()
        return [str(row["name"]) for row in rows]

    @classmethod
    def _note_categories(cls, connection: sqlite3.Connection, note_id: int) -> list[str]:
        rows = connection.execute(
            """
            SELECT DISTINCT cat.name
            FROM categories cat
            JOIN clips c ON c.category_id = cat.id
            JOIN note_clips nc ON nc.clip_id = c.id
            WHERE nc.note_id = ? ORDER BY cat.name COLLATE NOCASE
            """,
            (note_id,),
        ).fetchall()
        return [str(row["name"]) for row in rows]

    @classmethod
    def _note_summary(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        project_ids = cls._project_ids_for_note(connection, int(row["id"]))
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "summary": _snippet(row["body"]),
            "tags": cls._note_tags(connection, int(row["id"])),
            "categories": cls._note_categories(connection, int(row["id"])),
            "project_ids": project_ids,
            "projects": cls._project_refs(connection, project_ids),
            "is_done": _bool(row["is_done"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _note_detail(cls, connection: sqlite3.Connection, row: sqlite3.Row, max_chars: int) -> dict[str, Any]:
        note_id = int(row["id"])
        project_ids = cls._project_ids_for_note(connection, note_id)
        task_rows = connection.execute(
            """
            SELECT t.id, t.title, t.is_done, t.due_date, t.priority, t.created_at
            FROM tasks t JOIN task_notes tn ON tn.task_id = t.id
            WHERE tn.note_id = ? ORDER BY t.is_done, t.created_at DESC, t.id DESC LIMIT 50
            """,
            (note_id,),
        ).fetchall()
        return {
            "id": note_id,
            "title": row["title"],
            "body": _snippet(row["body"], max_chars),
            "is_done": _bool(row["is_done"]),
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tags": cls._note_tags(connection, note_id),
            "categories": cls._note_categories(connection, note_id),
            "projects": cls._project_refs(connection, project_ids),
            "project_ids": project_ids,
            "clips": [cls._clip_ref(connection, clip) for clip in cls._note_clip_rows(connection, note_id)[:50]],
            "related_tasks": [
                {
                    "id": int(task["id"]),
                    "title": task["title"],
                    "is_done": _bool(task["is_done"]),
                    "due_date": task["due_date"],
                    "priority": task["priority"],
                    "created_at": task["created_at"],
                }
                for task in task_rows
            ],
        }

    def search_memos(
        self,
        *,
        query: str | None,
        tags: list[str],
        tag_mode: str,
        category: str | None,
        project_id: int | None,
        project_query: str | None,
        done: bool | None,
        date_from: str | None,
        date_to: str | None,
        date_field: str,
        limit: int,
        cursor: str | None,
        sort: str,
    ) -> dict[str, Any]:
        token = _filter_token(
            "memos",
            {
                "query": query,
                "tags": tags,
                "tag_mode": tag_mode,
                "category": category,
                "project_id": project_id,
                "project_query": project_query,
                "done": done,
                "date_from": date_from,
                "date_to": date_to,
                "date_field": date_field,
                "sort": sort,
            },
        )

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            where = ["1 = 1"]
            params: list[Any] = []
            if query:
                search = _like(query)
                where.append(
                    "(n.title LIKE ? ESCAPE '\\' COLLATE NOCASE OR n.body LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR EXISTS (SELECT 1 FROM note_clips qnc JOIN clips qc ON qc.id = qnc.clip_id WHERE qnc.note_id = n.id AND (qc.title LIKE ? ESCAPE '\\' COLLATE NOCASE OR qc.url LIKE ? ESCAPE '\\' COLLATE NOCASE OR qc.comment LIKE ? ESCAPE '\\' COLLATE NOCASE)) "
                    "OR EXISTS (SELECT 1 FROM project_notes qpn JOIN projects qpr ON qpr.id = qpn.project_id WHERE qpn.note_id = n.id AND qpr.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
                )
                params.extend([search] * 6)
            if category:
                where.append(
                    "EXISTS (SELECT 1 FROM note_clips fcn JOIN clips fc ON fc.id = fcn.clip_id JOIN categories fcat ON fcat.id = fc.category_id WHERE fcn.note_id = n.id AND LOWER(fcat.name) = LOWER(?))"
                )
                params.append(category)
            if tags:
                if tag_mode == "all":
                    for tag in tags:
                        where.append(
                            "EXISTS (SELECT 1 FROM note_clips ntc JOIN clip_tags nct ON nct.clip_id = ntc.clip_id JOIN tags ntag ON ntag.id = nct.tag_id WHERE ntc.note_id = n.id AND LOWER(ntag.name) = LOWER(?))"
                        )
                        params.append(tag)
                else:
                    placeholders = ",".join("LOWER(?)" for _ in tags)
                    where.append(
                        f"EXISTS (SELECT 1 FROM note_clips ntc JOIN clip_tags nct ON nct.clip_id = ntc.clip_id JOIN tags ntag ON ntag.id = nct.tag_id WHERE ntc.note_id = n.id AND LOWER(ntag.name) IN ({placeholders}))"
                    )
                    params.extend(tags)
            if project_id is not None:
                where.append(
                    "(n.project_id = ? OR EXISTS (SELECT 1 FROM project_notes fpn WHERE fpn.note_id = n.id AND fpn.project_id = ?))"
                )
                params.extend([project_id, project_id])
            if project_query:
                where.append(
                    "(EXISTS (SELECT 1 FROM projects fpd WHERE fpd.id = n.project_id AND fpd.name LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                    "OR EXISTS (SELECT 1 FROM project_notes fpno JOIN projects fpo ON fpo.id = fpno.project_id WHERE fpno.note_id = n.id AND fpo.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
                )
                params.extend([_like(project_query), _like(project_query)])
            if done is not None:
                where.append("n.is_done = ?")
                params.append(1 if done else 0)
            date_expression = "n.updated_at" if date_field == "updated_at" else "n.created_at"
            _append_date_range(where, params, date_expression, date_from, date_to)
            sort_map = {
                "updated_desc": ("COALESCE(n.updated_at, '')", "COALESCE(n.updated_at, '') DESC, n.id DESC"),
                "created_desc": ("COALESCE(n.created_at, '')", "COALESCE(n.created_at, '') DESC, n.id DESC"),
                "title_asc": ("LOWER(COALESCE(n.title, ''))", "LOWER(COALESCE(n.title, '')) ASC, n.id ASC"),
                "title_desc": ("LOWER(COALESCE(n.title, ''))", "LOWER(COALESCE(n.title, '')) DESC, n.id DESC"),
            }
            value_expression, ordering = sort_map[sort]
            _add_cursor_filter(
                where,
                params,
                cursor=cursor,
                sort=sort,
                token=token,
                value_expression=value_expression,
                id_expression="n.id",
            )
            rows = connection.execute(
                f"""
                SELECT n.id, n.title, n.body, n.is_done, n.completed_at, n.created_at, n.updated_at,
                       {value_expression} AS _sort_value
                FROM notes n
                WHERE {' AND '.join(where)}
                ORDER BY {ordering}
                LIMIT ?
                """,
                (*params, limit + 1),
            ).fetchall()
            return _page(rows, limit=limit, sort=sort, token=token, item_builder=lambda row: self._note_summary(connection, row))

        return self._read(read)

    def get_memo(self, record_id: int, *, max_chars: int) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT id, title, body, is_done, completed_at, created_at, updated_at FROM notes WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError("memo", record_id)
            return self._note_detail(connection, row, max_chars)

        return self._read(read)

    @staticmethod
    def _task_clip_row(connection: sqlite3.Connection, clip_id: int | None) -> sqlite3.Row | None:
        if clip_id is None:
            return None
        return connection.execute(
            f"SELECT {ReadRepository._clip_select('c')} FROM clips c WHERE c.id = ?",
            (clip_id,),
        ).fetchone()

    @classmethod
    def _task_summary(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        clip_row = cls._task_clip_row(connection, row["clip_id"])
        project_ids = [int(row["project_id"])] if row["project_id"] is not None else []
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "status": "done" if _bool(row["is_done"]) else "open",
            "is_done": _bool(row["is_done"]),
            "due_date": row["due_date"],
            "priority": row["priority"],
            "created_at": row["created_at"],
            "project_ids": project_ids,
            "projects": cls._project_refs(connection, project_ids),
            "clip": cls._clip_ref(connection, clip_row) if clip_row else None,
        }

    @classmethod
    def _task_detail(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        task_id = int(row["id"])
        note_rows = connection.execute(
            "SELECT n.id, n.title, n.is_done, n.created_at, n.updated_at FROM notes n JOIN task_notes tn ON tn.note_id = n.id WHERE tn.task_id = ? ORDER BY n.updated_at DESC, n.id DESC LIMIT 50",
            (task_id,),
        ).fetchall()
        result = cls._task_summary(connection, row)
        result.update(
            {
                "completed_at": row["completed_at"],
                "related_memos": [
                    {
                        "id": int(note["id"]),
                        "title": note["title"],
                        "is_done": _bool(note["is_done"]),
                        "created_at": note["created_at"],
                        "updated_at": note["updated_at"],
                    }
                    for note in note_rows
                ],
            }
        )
        return result

    def search_tasks(
        self,
        *,
        query: str | None,
        tags: list[str],
        tag_mode: str,
        category: str | None,
        project_id: int | None,
        project_query: str | None,
        status: str,
        date_from: str | None,
        date_to: str | None,
        date_field: str,
        limit: int,
        cursor: str | None,
        sort: str,
    ) -> dict[str, Any]:
        token = _filter_token(
            "tasks",
            {
                "query": query,
                "tags": tags,
                "tag_mode": tag_mode,
                "category": category,
                "project_id": project_id,
                "project_query": project_query,
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
                "date_field": date_field,
                "sort": sort,
            },
        )

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            where = ["1 = 1"]
            params: list[Any] = []
            if query:
                search = _like(query)
                where.append(
                    "(t.title LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "OR EXISTS (SELECT 1 FROM clips qc WHERE qc.id = t.clip_id AND (qc.title LIKE ? ESCAPE '\\' COLLATE NOCASE OR qc.url LIKE ? ESCAPE '\\' COLLATE NOCASE OR qc.comment LIKE ? ESCAPE '\\' COLLATE NOCASE)) "
                    "OR EXISTS (SELECT 1 FROM projects qp WHERE qp.id = t.project_id AND qp.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
                )
                params.extend([search] * 5)
            if category:
                where.append(
                    "EXISTS (SELECT 1 FROM clips tc JOIN categories tcat ON tcat.id = tc.category_id WHERE tc.id = t.clip_id AND LOWER(tcat.name) = LOWER(?))"
                )
                params.append(category)
            if tags:
                if tag_mode == "all":
                    for tag in tags:
                        where.append(
                            "EXISTS (SELECT 1 FROM clip_tags tct JOIN tags tt ON tt.id = tct.tag_id WHERE tct.clip_id = t.clip_id AND LOWER(tt.name) = LOWER(?))"
                        )
                        params.append(tag)
                else:
                    placeholders = ",".join("LOWER(?)" for _ in tags)
                    where.append(
                        f"EXISTS (SELECT 1 FROM clip_tags tct JOIN tags tt ON tt.id = tct.tag_id WHERE tct.clip_id = t.clip_id AND LOWER(tt.name) IN ({placeholders}))"
                    )
                    params.extend(tags)
            if project_id is not None:
                where.append("t.project_id = ?")
                params.append(project_id)
            if project_query:
                where.append("EXISTS (SELECT 1 FROM projects tp WHERE tp.id = t.project_id AND tp.name LIKE ? ESCAPE '\\' COLLATE NOCASE)")
                params.append(_like(project_query))
            if status != "all":
                where.append("t.is_done = ?")
                params.append(1 if status == "done" else 0)
            date_expression = "t.due_date" if date_field == "due_date" else "t.created_at"
            _append_date_range(where, params, date_expression, date_from, date_to)
            sort_map = {
                "created_desc": ("COALESCE(t.created_at, '')", "COALESCE(t.created_at, '') DESC, t.id DESC"),
                "created_asc": ("COALESCE(t.created_at, '')", "COALESCE(t.created_at, '') ASC, t.id ASC"),
                "due_date_asc": ("COALESCE(t.due_date, '9999-12-31 23:59:59')", "COALESCE(t.due_date, '9999-12-31 23:59:59') ASC, t.id ASC"),
                "priority_desc": ("COALESCE(t.priority, -1)", "COALESCE(t.priority, -1) DESC, t.id DESC"),
                "title_asc": ("LOWER(COALESCE(t.title, ''))", "LOWER(COALESCE(t.title, '')) ASC, t.id ASC"),
            }
            value_expression, ordering = sort_map[sort]
            _add_cursor_filter(
                where,
                params,
                cursor=cursor,
                sort=sort,
                token=token,
                value_expression=value_expression,
                id_expression="t.id",
            )
            rows = connection.execute(
                f"""
                SELECT t.id, t.title, t.is_done, t.clip_id, t.due_date, t.priority, t.completed_at, t.created_at, t.project_id,
                       {value_expression} AS _sort_value
                FROM tasks t
                WHERE {' AND '.join(where)}
                ORDER BY {ordering}
                LIMIT ?
                """,
                (*params, limit + 1),
            ).fetchall()
            return _page(rows, limit=limit, sort=sort, token=token, item_builder=lambda row: self._task_summary(connection, row))

        return self._read(read)

    def get_task(self, record_id: int) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT id, title, is_done, clip_id, due_date, priority, completed_at, created_at, project_id FROM tasks WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError("task", record_id)
            return self._task_detail(connection, row)

        return self._read(read)

    @classmethod
    def _project_row(cls, connection: sqlite3.Connection, row: sqlite3.Row, *, include_ids: bool = False) -> dict[str, Any]:
        project_id = int(row["id"])
        clip_ids = [int(item["id"]) for item in connection.execute(
            "SELECT DISTINCT c.id FROM clips c LEFT JOIN project_clips pc ON pc.clip_id = c.id WHERE c.project_id = ? OR pc.project_id = ? ORDER BY c.created_at DESC, c.id DESC LIMIT 100",
            (project_id, project_id),
        ).fetchall()]
        memo_ids = [int(item["id"]) for item in connection.execute(
            "SELECT DISTINCT n.id FROM notes n LEFT JOIN project_notes pn ON pn.note_id = n.id WHERE n.project_id = ? OR pn.project_id = ? ORDER BY n.updated_at DESC, n.id DESC LIMIT 100",
            (project_id, project_id),
        ).fetchall()]
        task_ids = [int(item["id"]) for item in connection.execute(
            "SELECT id FROM tasks WHERE project_id = ? ORDER BY is_done, created_at DESC, id DESC LIMIT 100",
            (project_id,),
        ).fetchall()]
        clip_count = int(connection.execute(
            "SELECT COUNT(DISTINCT c.id) FROM clips c LEFT JOIN project_clips pc ON pc.clip_id = c.id WHERE c.project_id = ? OR pc.project_id = ?",
            (project_id, project_id),
        ).fetchone()[0])
        memo_count = int(connection.execute(
            "SELECT COUNT(DISTINCT n.id) FROM notes n LEFT JOIN project_notes pn ON pn.note_id = n.id WHERE n.project_id = ? OR pn.project_id = ?",
            (project_id, project_id),
        ).fetchone()[0])
        task_count = int(connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0])
        result: dict[str, Any] = {
            "id": project_id,
            "name": row["name"],
            "description": _snippet(row["description"], 4000),
            "is_done": _bool(row["is_done"]),
            "created_at": row["created_at"],
            "item_counts": {"clips": clip_count, "memos": memo_count, "tasks": task_count},
        }
        if include_ids:
            result["item_ids"] = {"clip_ids": clip_ids, "memo_ids": memo_ids, "task_ids": task_ids}
        return result

    def search_projects(
        self,
        *,
        query: str | None,
        status: str,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        cursor: str | None,
        sort: str,
    ) -> dict[str, Any]:
        token = _filter_token(
            "projects",
            {"query": query, "status": status, "date_from": date_from, "date_to": date_to, "sort": sort},
        )

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            where = ["1 = 1"]
            params: list[Any] = []
            _append_query(where, params, query, ["COALESCE(p.name, '')", "COALESCE(p.description, '')"])
            if status != "all":
                where.append("p.is_done = ?")
                params.append(1 if status == "done" else 0)
            _append_date_range(where, params, "p.created_at", date_from, date_to)
            sort_map = {
                "created_desc": ("COALESCE(p.created_at, '')", "COALESCE(p.created_at, '') DESC, p.id DESC"),
                "created_asc": ("COALESCE(p.created_at, '')", "COALESCE(p.created_at, '') ASC, p.id ASC"),
                "name_asc": ("LOWER(COALESCE(p.name, ''))", "LOWER(COALESCE(p.name, '')) ASC, p.id ASC"),
                "name_desc": ("LOWER(COALESCE(p.name, ''))", "LOWER(COALESCE(p.name, '')) DESC, p.id DESC"),
            }
            value_expression, ordering = sort_map[sort]
            _add_cursor_filter(
                where,
                params,
                cursor=cursor,
                sort=sort,
                token=token,
                value_expression=value_expression,
                id_expression="p.id",
            )
            rows = connection.execute(
                f"""
                SELECT p.id, p.name, p.description, p.is_done, p.created_at, {value_expression} AS _sort_value
                FROM projects p
                WHERE {' AND '.join(where)}
                ORDER BY {ordering}
                LIMIT ?
                """,
                (*params, limit + 1),
            ).fetchall()
            return _page(rows, limit=limit, sort=sort, token=token, item_builder=lambda row: self._project_row(connection, row))

        return self._read(read)

    def get_project(self, record_id: int) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT id, name, description, is_done, created_at FROM projects WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError("project", record_id)
            return self._project_row(connection, row, include_ids=True)

        return self._read(read)

    def list_project_items(self, project_id: int, *, limit: int) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            project = connection.execute(
                "SELECT id, name FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise RecordNotFoundError("project", project_id)
            clips = connection.execute(
                f"""
                SELECT DISTINCT {self._clip_select('c')}
                FROM clips c LEFT JOIN project_clips pc ON pc.clip_id = c.id
                WHERE c.project_id = ? OR pc.project_id = ?
                ORDER BY c.created_at DESC, c.id DESC LIMIT ?
                """,
                (project_id, project_id, limit + 1),
            ).fetchall()
            memos = connection.execute(
                """
                SELECT DISTINCT n.id, n.title, n.body, n.is_done, n.completed_at, n.created_at, n.updated_at
                FROM notes n LEFT JOIN project_notes pn ON pn.note_id = n.id
                WHERE n.project_id = ? OR pn.project_id = ?
                ORDER BY n.updated_at DESC, n.id DESC LIMIT ?
                """,
                (project_id, project_id, limit + 1),
            ).fetchall()
            tasks = connection.execute(
                "SELECT id, title, is_done, clip_id, due_date, priority, completed_at, created_at, project_id FROM tasks WHERE project_id = ? ORDER BY is_done, due_date IS NULL, due_date ASC, id DESC LIMIT ?",
                (project_id, limit + 1),
            ).fetchall()
            return {
                "project": {"id": int(project["id"]), "name": project["name"]},
                "clips": [self._clip_summary(connection, row) for row in clips[:limit]],
                "memos": [self._note_summary(connection, row) for row in memos[:limit]],
                "tasks": [self._task_summary(connection, row) for row in tasks[:limit]],
                "truncated": {
                    "clips": len(clips) > limit,
                    "memos": len(memos) > limit,
                    "tasks": len(tasks) > limit,
                },
                "limit": limit,
            }

        return self._read(read)
