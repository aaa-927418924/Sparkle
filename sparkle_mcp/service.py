"""Transport-neutral MCP tool service with validation and safe errors."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .readonly_db import DatabaseAccessError
from .repository import ReadRepository, RecordNotFoundError
from .validation import (
    McpInputError,
    normalized_date,
    normalized_tags,
    optional_text,
    valid_cursor,
    valid_id,
    valid_limit,
)


logger = logging.getLogger("sparkle_mcp.service")


class ToolService:
    """Validate MCP arguments, run a read query, and normalize failures."""

    CLIP_SORTS = {"created_desc", "created_asc", "title_asc", "title_desc"}
    MEMO_SORTS = {"updated_desc", "created_desc", "title_asc", "title_desc"}
    TASK_SORTS = {"created_desc", "created_asc", "due_date_asc", "priority_desc", "title_asc"}
    PROJECT_SORTS = {"created_desc", "created_asc", "name_asc", "name_desc"}

    def __init__(self, db_path: Path | str | None = None):
        self.repository = ReadRepository(db_path)

    @staticmethod
    def _error(code: str, message: str, *, field: str | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if field:
            error["field"] = field
        return {"error": error}

    def _run(self, tool_name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except McpInputError as exc:
            return self._error(exc.code, exc.message, field=exc.field)
        except RecordNotFoundError as exc:
            return self._error("not_found", f"The requested {exc.record_type} was not found.", field="id")
        except DatabaseAccessError as exc:
            return self._error(exc.code, exc.message)
        except sqlite3.OperationalError:
            logger.exception("MCP database schema/query error in %s", tool_name)
            return self._error(
                "database_schema_error",
                "Sparkle's database schema is not ready for this MCP operation.",
            )
        except sqlite3.Error:
            logger.exception("MCP database error in %s", tool_name)
            return self._error("database_error", "Sparkle's database could not be read.")
        except Exception:
            logger.exception("Unexpected MCP error in %s", tool_name)
            return self._error("internal_error", "The MCP operation could not be completed.")

    @staticmethod
    def _date_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
        start = normalized_date(date_from, field="date_from")
        end = normalized_date(date_to, field="date_to", end_of_day=True)
        if start and end and start > end:
            raise McpInputError("date_from must not be later than date_to.", field="date_from")
        return start, end

    @classmethod
    def _common(
        cls,
        *,
        query: str | None,
        tags: list[str] | None,
        tag_mode: str,
        category: str | None,
        project_id: int | None,
        project_query: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        cursor: str | None,
        sort: str,
        allowed_sorts: set[str],
    ) -> dict[str, Any]:
        query = optional_text(query, field="query", max_length=200)
        category = optional_text(category, field="category", max_length=120)
        project_query = optional_text(project_query, field="project_query", max_length=120)
        if tag_mode not in {"any", "all"}:
            raise McpInputError("tag_mode must be 'any' or 'all'.", field="tag_mode")
        if project_id is not None:
            project_id = valid_id(project_id, field="project_id")
        if sort not in allowed_sorts:
            raise McpInputError("sort is not supported for this search.", field="sort")
        start, end = cls._date_range(date_from, date_to)
        return {
            "query": query,
            "tags": normalized_tags(tags),
            "tag_mode": tag_mode,
            "category": category,
            "project_id": project_id,
            "project_query": project_query,
            "date_from": start,
            "date_to": end,
            "limit": valid_limit(limit),
            "cursor": valid_cursor(cursor),
            "sort": sort,
        }

    @staticmethod
    def _max_chars(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 30000:
            raise McpInputError("max_chars must be between 1 and 30000.", field="max_chars")
        return value

    def search_clips(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: str = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        favorite: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort: str = "created_desc",
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            arguments = self._common(
                query=query,
                tags=tags,
                tag_mode=tag_mode,
                category=category,
                project_id=project_id,
                project_query=project_query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                cursor=cursor,
                sort=sort,
                allowed_sorts=self.CLIP_SORTS,
            )
            if favorite is not None and not isinstance(favorite, bool):
                raise McpInputError("favorite must be a boolean.", field="favorite")
            return self.repository.search_clips(favorite=favorite, **arguments)

        return self._run("search_clips", operation)

    def get_clip(self, *, id: int, max_chars: int = 12000) -> dict[str, Any]:
        return self._run("get_clip", lambda: self.repository.get_clip(valid_id(id), max_chars=self._max_chars(max_chars)))

    def search_memos(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: str = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        done: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        date_field: str = "updated_at",
        limit: int = 20,
        cursor: str | None = None,
        sort: str = "updated_desc",
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            arguments = self._common(
                query=query,
                tags=tags,
                tag_mode=tag_mode,
                category=category,
                project_id=project_id,
                project_query=project_query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                cursor=cursor,
                sort=sort,
                allowed_sorts=self.MEMO_SORTS,
            )
            if date_field not in {"created_at", "updated_at"}:
                raise McpInputError("date_field must be 'created_at' or 'updated_at'.", field="date_field")
            if done is not None and not isinstance(done, bool):
                raise McpInputError("done must be a boolean.", field="done")
            return self.repository.search_memos(date_field=date_field, done=done, **arguments)

        return self._run("search_memos", operation)

    def get_memo(self, *, id: int, max_chars: int = 20000) -> dict[str, Any]:
        return self._run("get_memo", lambda: self.repository.get_memo(valid_id(id), max_chars=self._max_chars(max_chars)))

    def search_tasks(
        self,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: str = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        status: str = "all",
        date_from: str | None = None,
        date_to: str | None = None,
        date_field: str = "created_at",
        limit: int = 20,
        cursor: str | None = None,
        sort: str = "created_desc",
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            arguments = self._common(
                query=query,
                tags=tags,
                tag_mode=tag_mode,
                category=category,
                project_id=project_id,
                project_query=project_query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                cursor=cursor,
                sort=sort,
                allowed_sorts=self.TASK_SORTS,
            )
            if status not in {"all", "open", "done"}:
                raise McpInputError("status must be 'all', 'open', or 'done'.", field="status")
            if date_field not in {"created_at", "due_date"}:
                raise McpInputError("date_field must be 'created_at' or 'due_date'.", field="date_field")
            return self.repository.search_tasks(status=status, date_field=date_field, **arguments)

        return self._run("search_tasks", operation)

    def get_task(self, *, id: int) -> dict[str, Any]:
        return self._run("get_task", lambda: self.repository.get_task(valid_id(id)))

    def search_projects(
        self,
        *,
        query: str | None = None,
        status: str = "all",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort: str = "created_desc",
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            query_value = optional_text(query, field="query", max_length=200)
            if status not in {"all", "open", "done"}:
                raise McpInputError("status must be 'all', 'open', or 'done'.", field="status")
            if sort not in self.PROJECT_SORTS:
                raise McpInputError("sort is not supported for projects.", field="sort")
            start, end = self._date_range(date_from, date_to)
            return self.repository.search_projects(
                query=query_value,
                status=status,
                date_from=start,
                date_to=end,
                limit=valid_limit(limit),
                cursor=valid_cursor(cursor),
                sort=sort,
            )

        return self._run("search_projects", operation)

    def get_project(self, *, id: int) -> dict[str, Any]:
        return self._run("get_project", lambda: self.repository.get_project(valid_id(id)))

    def list_project_items(self, *, project_id: int, limit: int = 20) -> dict[str, Any]:
        return self._run(
            "list_project_items",
            lambda: self.repository.list_project_items(valid_id(project_id, field="project_id"), limit=valid_limit(limit)),
        )
