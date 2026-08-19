"""MCP tool registration.  The callable signatures are the public schemas."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer

from .service import ToolService


def register_tools(server: MCPServer, service: ToolService | None = None) -> ToolService:
    """Register the read-only tools on an SDK server and return their service."""

    service = service or ToolService()

    def search_clips(
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: Literal["any", "all"] = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        favorite: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort: Literal["created_desc", "created_asc", "title_asc", "title_desc"] = "created_desc",
    ) -> dict[str, Any]:
        return service.search_clips(
            query=query,
            tags=tags,
            tag_mode=tag_mode,
            category=category,
            project_id=project_id,
            project_query=project_query,
            favorite=favorite,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            cursor=cursor,
            sort=sort,
        )

    def get_clip(id: int, max_chars: int = 12000) -> dict[str, Any]:
        return service.get_clip(id=id, max_chars=max_chars)

    def search_memos(
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: Literal["any", "all"] = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        done: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        date_field: Literal["created_at", "updated_at"] = "updated_at",
        limit: int = 20,
        cursor: str | None = None,
        sort: Literal["updated_desc", "created_desc", "title_asc", "title_desc"] = "updated_desc",
    ) -> dict[str, Any]:
        return service.search_memos(
            query=query,
            tags=tags,
            tag_mode=tag_mode,
            category=category,
            project_id=project_id,
            project_query=project_query,
            done=done,
            date_from=date_from,
            date_to=date_to,
            date_field=date_field,
            limit=limit,
            cursor=cursor,
            sort=sort,
        )

    def get_memo(id: int, max_chars: int = 20000) -> dict[str, Any]:
        return service.get_memo(id=id, max_chars=max_chars)

    def search_tasks(
        query: str | None = None,
        tags: list[str] | None = None,
        tag_mode: Literal["any", "all"] = "any",
        category: str | None = None,
        project_id: int | None = None,
        project_query: str | None = None,
        status: Literal["all", "open", "done"] = "all",
        date_from: str | None = None,
        date_to: str | None = None,
        date_field: Literal["created_at", "due_date"] = "created_at",
        limit: int = 20,
        cursor: str | None = None,
        sort: Literal["created_desc", "created_asc", "due_date_asc", "priority_desc", "title_asc"] = "created_desc",
    ) -> dict[str, Any]:
        return service.search_tasks(
            query=query,
            tags=tags,
            tag_mode=tag_mode,
            category=category,
            project_id=project_id,
            project_query=project_query,
            status=status,
            date_from=date_from,
            date_to=date_to,
            date_field=date_field,
            limit=limit,
            cursor=cursor,
            sort=sort,
        )

    def get_task(id: int) -> dict[str, Any]:
        return service.get_task(id=id)

    def search_projects(
        query: str | None = None,
        status: Literal["all", "open", "done"] = "all",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort: Literal["created_desc", "created_asc", "name_asc", "name_desc"] = "created_desc",
    ) -> dict[str, Any]:
        return service.search_projects(
            query=query,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            cursor=cursor,
            sort=sort,
        )

    def get_project(id: int) -> dict[str, Any]:
        return service.get_project(id=id)

    def list_project_items(project_id: int, limit: int = 20) -> dict[str, Any]:
        return service.list_project_items(project_id=project_id, limit=limit)

    definitions = [
        (search_clips, "search_clips", "Search saved clips and return compact candidates. Use get_clip for full details."),
        (get_clip, "get_clip", "Get one saved clip by ID, including its safe URL, body/comment, tags, projects, and related items."),
        (search_memos, "search_memos", "Search memos and return compact candidates. Use get_memo for the full memo body."),
        (get_memo, "get_memo", "Get one memo by ID, including its body, linked clips, projects, and related tasks."),
        (search_tasks, "search_tasks", "Search tasks by text, project, status, tags, dates, or linked clip metadata."),
        (get_task, "get_task", "Get one task by ID, including its linked clip, project, and related memos."),
        (search_projects, "search_projects", "Search projects by name, description, status, or creation date."),
        (get_project, "get_project", "Get one project by ID, with bounded item IDs and item counts."),
        (list_project_items, "list_project_items", "List bounded clip, memo, and task candidates belonging to one project."),
    ]
    for function, name, description in definitions:
        server.add_tool(function, name=name, description=description, structured_output=False)
    return service
