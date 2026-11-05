"""HTTP routes for local Sparkle plugin management."""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from contextlib import ExitStack, contextmanager
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlite3 import Connection

from routers import (
    create_clip as host_create_clip,
    create_note as host_create_note,
    create_project as host_create_project,
    create_task as host_create_task,
    delete_clip as host_delete_clip,
    delete_note as host_delete_note,
    delete_project as host_delete_project,
    delete_task as host_delete_task,
    get_clip as host_get_clip,
    get_db,
    get_note as host_get_note,
    get_project as host_get_project,
    get_task as host_get_task,
    list_clips as host_list_clips,
    list_notes as host_list_notes,
    list_projects as host_list_projects,
    list_tasks as host_list_tasks,
    update_clip as host_update_clip,
    update_note as host_update_note,
    update_project as host_update_project,
    update_task as host_update_task,
    _validate_metadata_url as host_validate_metadata_url,
)
from schemas import (
    ClipCreate,
    ClipUpdate,
    NoteCreate,
    NoteUpdate,
    ProjectCreate,
    ProjectUpdate,
    TaskCreate,
    TaskUpdate,
)
from plugin_ai import generate_plugin_ai_response
from plugin_network import PluginNetworkError, perform_plugin_network_request
from plugin_oauth import (
    PluginOAuthError,
    authenticated_request as plugin_oauth_request,
    disconnect_connection as disconnect_plugin_oauth,
    get_connection_status as get_plugin_oauth_status,
    start_connection as start_plugin_oauth,
)
from project_assistant import ProjectAssistantError

from plugin_manager import (
    MAX_ARCHIVE_BYTES,
    PluginError,
    PluginPermissionRequired,
    export_plugin_archive,
    get_active_theme,
    get_active_theme_page_stylesheet,
    get_authoring_skill_status,
    get_plugin_ui_state,
    install_authoring_skill,
    install_plugin_archive,
    list_plugins,
    plugin_resource_path,
    plugin_permission_guard,
    put_plugin_storage,
    get_plugin_storage,
    remove_plugin,
    revoke_plugin_permissions,
    set_plugin_permission_grant,
    set_active_theme,
    set_plugin_enabled,
)


router = APIRouter(prefix="/plugins", tags=["plugins"])

PANEL_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "object-src 'none'; "
    "sandbox allow-scripts"
)

PLUGIN_PANEL_THEME_BASE_CSS = """
html[data-sparkle-plugin-theme] {
  color-scheme: var(--sparkle-theme-color-scheme, light dark);
  color: var(--sparkle-theme-text, CanvasText);
  background-color: var(--sparkle-theme-background, transparent);
}
html[data-sparkle-plugin-theme] body {
  color: var(--sparkle-theme-text, CanvasText);
  background-color: var(--sparkle-theme-background, transparent);
}
html[data-sparkle-plugin-theme] :where(a) {
  color: var(--sparkle-theme-accent, currentColor);
}
html[data-sparkle-plugin-theme] :where(button, [role="button"]) {
  color: var(--sparkle-theme-action-button-text, var(--sparkle-theme-text, inherit));
  background-color: var(--sparkle-theme-action-button-background, var(--sparkle-theme-surface, transparent));
  border-color: var(--sparkle-theme-action-button-border, var(--sparkle-theme-border, currentColor));
}
html[data-sparkle-plugin-theme] :where(button, [role="button"]):hover {
  color: var(--sparkle-theme-action-button-hover-text, var(--sparkle-theme-action-button-text, var(--sparkle-theme-text, inherit)));
  background-color: var(--sparkle-theme-action-button-hover-background, var(--sparkle-theme-surface-hover, transparent));
  border-color: var(--sparkle-theme-action-button-hover-border, var(--sparkle-theme-border-strong, currentColor));
}
html[data-sparkle-plugin-theme] :where(button[aria-pressed="true"], button[aria-selected="true"], [role="button"][aria-pressed="true"], [role="tab"][aria-selected="true"]) {
  color: var(--sparkle-theme-control-active-text, var(--sparkle-theme-text, inherit));
  background-color: var(--sparkle-theme-control-active-background, var(--sparkle-theme-surface-active, var(--sparkle-theme-surface, transparent)));
}
html[data-sparkle-plugin-theme] :where(input:not([type="checkbox"]):not([type="radio"]), select, textarea) {
  color: var(--sparkle-theme-control-text, var(--sparkle-theme-text, inherit));
  background-color: var(--sparkle-theme-control-background, var(--sparkle-theme-surface, transparent));
  border-color: var(--sparkle-theme-border, currentColor);
}
html[data-sparkle-plugin-theme] :where(input[type="checkbox"], input[type="radio"]) {
  accent-color: var(--sparkle-theme-checkbox-accent, var(--sparkle-theme-accent, auto));
}
"""

PLUGIN_PANEL_THEME_RUNTIME = r"""
(() => {
  "use strict";
  const idPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const keyPattern = /^[a-z][A-Za-z0-9]{0,63}$/;
  const colorPattern = /^(?:#[\da-f]{6}(?:[\da-f]{2})?|rgba?\(\s*(?:\d{1,3}%?\s*,\s*){2}\d{1,3}%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\))$/i;
  const iconFilters = {
    source: "none",
    dark: "brightness(0) saturate(100%)",
    light: "brightness(0) saturate(100%) invert(1)",
  };
  const appliedProperties = new Set();
  const root = document.documentElement;

  function colorScheme(value) {
    const match = /^#([\da-f]{6})/i.exec(value || "");
    if (!match) return "light dark";
    const rgb = [0, 2, 4].map((index) => parseInt(match[1].slice(index, index + 2), 16) / 255)
      .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    const luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    return luminance > 0.45 ? "light" : "dark";
  }

  function stylesheetFor(theme) {
    let link = document.getElementById("sparkle-plugin-theme-pages");
    if (!theme) {
      link?.remove();
      return;
    }
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", () => stylesheetFor(theme), { once: true });
      return;
    }
    if (!link) {
      link = document.createElement("link");
      link.id = "sparkle-plugin-theme-pages";
      link.rel = "stylesheet";
      link.setAttribute("itemprop", "theme-stylesheet");
    }
    link.href = `/plugins/${encodeURIComponent(theme.id)}/plugin-pages.css`;
    document.body.append(link);
  }

  function apply(theme) {
    for (const property of appliedProperties) root.style.removeProperty(property);
    appliedProperties.clear();
    root.removeAttribute("data-sparkle-plugin-theme");

    if (!theme || typeof theme !== "object" || !idPattern.test(theme.id || "")) {
      stylesheetFor(null);
      return;
    }

    const colors = theme.colors && typeof theme.colors === "object" ? theme.colors : {};
    for (const [key, value] of Object.entries(colors)) {
      if (!keyPattern.test(key) || typeof value !== "string" || !colorPattern.test(value.trim())) continue;
      const property = `--sparkle-theme-${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
      root.style.setProperty(property, value.trim());
      appliedProperties.add(property);
    }
    const icons = theme.icons && typeof theme.icons === "object" ? theme.icons : {};
    for (const [key, mode] of Object.entries(icons)) {
      if (!Object.prototype.hasOwnProperty.call(iconFilters, mode)) continue;
      const property = `--sparkle-theme-${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}-icon-filter`;
      root.style.setProperty(property, iconFilters[mode]);
      appliedProperties.add(property);
    }
    root.style.setProperty("--sparkle-theme-color-scheme", colorScheme(colors.background));
    appliedProperties.add("--sparkle-theme-color-scheme");
    root.dataset.sparklePluginTheme = theme.id;
    stylesheetFor(theme);
  }

  apply(window.__SPARKLE_PLUGIN_THEME_BOOTSTRAP__ || null);
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || event.data?.type !== "sparkle-plugin-theme") return;
    apply(event.data.theme || null);
  });
})();
"""


def _safe_panel_theme_payload(theme: dict | None) -> str:
    if not isinstance(theme, dict):
        return "null"
    payload = {
        "id": theme.get("id"),
        "colors": theme.get("colors", {}),
        "icons": theme.get("icons", {}),
    }
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _inject_panel_theme_runtime(html: str, theme: dict | None) -> str:
    payload = _safe_panel_theme_payload(theme)
    script = (
        f"window.__SPARKLE_PLUGIN_THEME_BOOTSTRAP__={payload};\n"
        + PLUGIN_PANEL_THEME_RUNTIME
    )
    injection = (
        f"<style id=\"sparkle-plugin-theme-base\">{PLUGIN_PANEL_THEME_BASE_CSS}</style>"
        f"<script>{script}</script>"
    )
    closing_head = re.search(r"</head\s*>", html, flags=re.IGNORECASE)
    if closing_head:
        return html[:closing_head.start()] + injection + html[closing_head.start():]
    opening_head = re.search(r"<head\b[^>]*>", html, flags=re.IGNORECASE)
    if opening_head:
        return html[:opening_head.end()] + injection + html[opening_head.end():]
    opening_html = re.search(r"<html\b[^>]*>", html, flags=re.IGNORECASE)
    if opening_html:
        return html[:opening_html.end()] + f"<head>{injection}</head>" + html[opening_html.end():]
    return f"<head>{injection}</head>" + html


class PluginEnabledRequest(BaseModel):
    enabled: bool


class ActiveThemeRequest(BaseModel):
    plugin_id: str | None = None


class PluginStorageRequest(BaseModel):
    value: object


class PluginPermissionGrantRequest(BaseModel):
    granted: bool


class PluginAIGenerateRequest(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=4_000)
    prompt: str = Field(..., min_length=1, max_length=32_000)


class PluginNetworkRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2_048)
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=512 * 1024)


class PluginOAuthConnectionRequest(BaseModel):
    connection_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=100)
    agent_name_hint: str = Field(default="Sparkle", min_length=1, max_length=100)
    authorization_url: str = Field(..., min_length=1, max_length=2048)
    token_url: str = Field(..., min_length=1, max_length=2048)
    client_id: str = Field(..., min_length=1, max_length=256)
    dynamic_registration: bool = False
    scopes: list[str] = Field(..., min_length=1, max_length=32)
    resource: str | None = Field(default=None, max_length=2048)
    api_origin: str = Field(..., min_length=1, max_length=2048)
    issuer: str | None = Field(default=None, max_length=2048)
    jwks_url: str | None = Field(default=None, max_length=2048)
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    reauthorize: bool = False


class PluginOAuthRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=512 * 1024)


def _plugin_http_error(exc: PluginError) -> HTTPException:
    if isinstance(exc, PluginPermissionRequired):
        return HTTPException(
            status_code=403,
            detail={"permission_required": exc.permission, "message": str(exc)},
        )
    text = str(exc)
    status = 409 if "すでにあります" in text else 400
    if "見つかりません" in text:
        status = 404
    return HTTPException(status_code=status, detail=text)


def _plugin_oauth_http_error(exc: PluginOAuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@contextmanager
def _require_data_permission(plugin_id: str, permission: str) -> Iterator[None]:
    try:
        with plugin_permission_guard(plugin_id, permission):
            yield
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@contextmanager
def _require_plugin_permissions(plugin_id: str, *permissions: str) -> Iterator[None]:
    with ExitStack() as stack:
        for permission in permissions:
            stack.enter_context(_require_data_permission(plugin_id, permission))
        yield


def _plugin_note_data(note):
    if hasattr(note, "model_dump"):
        return note.model_dump(exclude={"clips"})
    result = dict(note)
    result.pop("clips", None)
    return result


def _plugin_task_data(task):
    if hasattr(task, "model_dump"):
        return task.model_dump(exclude={"clip"})
    result = dict(task)
    result.pop("clip", None)
    return result


@router.get("")
def get_plugins():
    return list_plugins()


@router.get("/ui")
def get_plugin_ui():
    return get_plugin_ui_state()


@router.get("/authoring-skill/status")
def get_plugin_authoring_skill_status():
    try:
        return get_authoring_skill_status()
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.post("/import")
async def import_plugin(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="ZIPファイルを選択してください。")
    try:
        content = await file.read(MAX_ARCHIVE_BYTES + 1)
        if len(content) > MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="ZIPファイルは20MB以下にしてください。")
        return install_plugin_archive(content)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc
    finally:
        await file.close()


@router.post("/install-authoring-skill")
def install_plugin_authoring_skill():
    try:
        return install_authoring_skill()
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.get("/active-theme")
def active_theme():
    return {"theme": get_active_theme()}


@router.put("/active-theme")
def update_active_theme(body: ActiveThemeRequest):
    try:
        return {"theme": set_active_theme(body.plugin_id)}
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.post("/{plugin_id}/enabled")
def update_plugin_enabled(plugin_id: str, body: PluginEnabledRequest):
    try:
        return set_plugin_enabled(plugin_id, body.enabled)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.put("/{plugin_id}/permissions/{permission}")
def update_plugin_permission(plugin_id: str, permission: str, body: PluginPermissionGrantRequest):
    try:
        return set_plugin_permission_grant(plugin_id, permission, body.granted)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.delete("/{plugin_id}/permissions")
def delete_plugin_permissions(plugin_id: str):
    try:
        return revoke_plugin_permissions(plugin_id)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.get("/{plugin_id}/data/clips")
def plugin_list_clips(
    plugin_id: str,
    category: str | None = Query(None),
    tag: str | None = Query(None),
    url: str | None = Query(None),
    project_id: int | None = Query(None),
    exclude_project: int | None = Query(None),
    db: Connection = Depends(get_db),
):
    with _require_data_permission(plugin_id, "clips.read"):
        return host_list_clips(
            category=category,
            tag=tag,
            url=url,
            project_id=project_id,
            exclude_project=exclude_project,
            db=db,
        )


@router.get("/{plugin_id}/data/clips/{clip_id}")
def plugin_get_clip(plugin_id: str, clip_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "clips.read"):
        return host_get_clip(clip_id, db=db)


@router.post("/{plugin_id}/data/clips", status_code=201)
def plugin_create_clip(plugin_id: str, payload: ClipCreate, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "clips.write"):
        if payload.clip_type not in (None, "url") or payload.file_ref is not None:
            raise HTTPException(status_code=422, detail="プラグインからローカルファイルのクリップは作成できません。")
        try:
            payload.url = host_validate_metadata_url(payload.url)
            if payload.thumbnail_url is not None:
                payload.thumbnail_url = host_validate_metadata_url(payload.thumbnail_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="公開WebサイトのHTTP/HTTPS URLのみ指定できます。") from exc
        if payload.project_id is not None:
            with _require_data_permission(plugin_id, "projects.write"):
                return host_create_clip(payload, db=db)
        return host_create_clip(payload, db=db)


@router.put("/{plugin_id}/data/clips/{clip_id}")
def plugin_update_clip(plugin_id: str, clip_id: int, payload: ClipUpdate, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "clips.write"):
        if "project_id" in payload.model_fields_set or "project_ids" in payload.model_fields_set:
            with _require_data_permission(plugin_id, "projects.write"):
                if payload.thumbnail_url is not None:
                    try:
                        payload.thumbnail_url = host_validate_metadata_url(payload.thumbnail_url)
                    except ValueError as exc:
                        raise HTTPException(status_code=422, detail="公開WebサイトのHTTP/HTTPS URLのみ指定できます。") from exc
                return host_update_clip(clip_id, payload, db=db)
        if payload.thumbnail_url is not None:
            try:
                payload.thumbnail_url = host_validate_metadata_url(payload.thumbnail_url)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="公開WebサイトのHTTP/HTTPS URLのみ指定できます。") from exc
        return host_update_clip(clip_id, payload, db=db)


@router.delete("/{plugin_id}/data/clips/{clip_id}", status_code=204)
def plugin_delete_clip(plugin_id: str, clip_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "clips.delete"):
        return host_delete_clip(clip_id, db=db)


@router.get("/{plugin_id}/data/projects")
def plugin_list_projects(plugin_id: str, done: bool | None = Query(None), db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "projects.read"):
        return host_list_projects(done=done, db=db)


@router.get("/{plugin_id}/data/projects/{project_id}")
def plugin_get_project(plugin_id: str, project_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "projects.read"):
        return host_get_project(project_id, db=db)


@router.post("/{plugin_id}/data/projects", status_code=201)
def plugin_create_project(plugin_id: str, payload: ProjectCreate, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "projects.write"):
        return host_create_project(payload, db=db)


@router.put("/{plugin_id}/data/projects/{project_id}")
def plugin_update_project(plugin_id: str, project_id: int, payload: ProjectUpdate, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "projects.write"):
        if "is_done" in payload.model_fields_set:
            raise HTTPException(
                status_code=422,
                detail="プロジェクトの完了状態変更はタスクやメモにも影響するため、プラグインAPIでは未対応です。",
            )
        return host_update_project(project_id, payload, db=db)


@router.delete("/{plugin_id}/data/projects/{project_id}", status_code=204)
def plugin_delete_project(plugin_id: str, project_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "projects.delete"):
        return host_delete_project(project_id, db=db)


@router.get("/{plugin_id}/data/notes")
def plugin_list_notes(
    plugin_id: str,
    project_id: int | None = Query(None),
    exclude_project: int | None = Query(None),
    db: Connection = Depends(get_db),
):
    permissions = ["notes.read"]
    if project_id is not None or exclude_project is not None:
        permissions.append("projects.read")
    with _require_plugin_permissions(plugin_id, *permissions):
        return [_plugin_note_data(note) for note in host_list_notes(project_id, exclude_project, db=db)]


@router.get("/{plugin_id}/data/notes/{note_id}")
def plugin_get_note(plugin_id: str, note_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "notes.read"):
        return _plugin_note_data(host_get_note(note_id, db=db))


@router.post("/{plugin_id}/data/notes", status_code=201)
def plugin_create_note(plugin_id: str, payload: NoteCreate, db: Connection = Depends(get_db)):
    permissions = ["notes.write"]
    if payload.project_id is not None or payload.project_ids:
        permissions.append("projects.write")
    if payload.clip_ids:
        permissions.append("clips.write")
    with _require_plugin_permissions(plugin_id, *permissions):
        return _plugin_note_data(host_create_note(payload, db=db))


@router.put("/{plugin_id}/data/notes/{note_id}")
def plugin_update_note(
    plugin_id: str,
    note_id: int,
    payload: NoteUpdate,
    db: Connection = Depends(get_db),
):
    permissions = ["notes.write"]
    if "project_id" in payload.model_fields_set or "project_ids" in payload.model_fields_set:
        permissions.append("projects.write")
    if "clip_ids" in payload.model_fields_set and payload.clip_ids is not None:
        permissions.append("clips.write")
    with _require_plugin_permissions(plugin_id, *permissions):
        return _plugin_note_data(host_update_note(note_id, payload, db=db))


@router.delete("/{plugin_id}/data/notes/{note_id}", status_code=204)
def plugin_delete_note(plugin_id: str, note_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "notes.delete"):
        return host_delete_note(note_id, db=db)


@router.get("/{plugin_id}/data/tasks")
def plugin_list_tasks(
    plugin_id: str,
    done: bool | None = Query(None),
    project_id: int | None = Query(None),
    exclude_project: int | None = Query(None),
    db: Connection = Depends(get_db),
):
    permissions = ["tasks.read"]
    if project_id is not None or exclude_project is not None:
        permissions.append("projects.read")
    with _require_plugin_permissions(plugin_id, *permissions):
        return [
            _plugin_task_data(task)
            for task in host_list_tasks(done, project_id, exclude_project, db=db)
        ]


@router.get("/{plugin_id}/data/tasks/{task_id}")
def plugin_get_task(plugin_id: str, task_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "tasks.read"):
        return _plugin_task_data(host_get_task(task_id, db=db))


@router.post("/{plugin_id}/data/tasks", status_code=201)
def plugin_create_task(plugin_id: str, payload: TaskCreate, db: Connection = Depends(get_db)):
    permissions = ["tasks.write"]
    if payload.project_id is not None:
        permissions.append("projects.write")
    if payload.clip_id is not None:
        permissions.append("clips.write")
    with _require_plugin_permissions(plugin_id, *permissions):
        return _plugin_task_data(host_create_task(payload, db=db))


@router.put("/{plugin_id}/data/tasks/{task_id}")
def plugin_update_task(
    plugin_id: str,
    task_id: int,
    payload: TaskUpdate,
    db: Connection = Depends(get_db),
):
    permissions = ["tasks.write"]
    if "project_id" in payload.model_fields_set:
        permissions.append("projects.write")
    if "clip_id" in payload.model_fields_set:
        permissions.append("clips.write")
    with _require_plugin_permissions(plugin_id, *permissions):
        return _plugin_task_data(host_update_task(task_id, payload, db=db))


@router.delete("/{plugin_id}/data/tasks/{task_id}", status_code=204)
def plugin_delete_task(plugin_id: str, task_id: int, db: Connection = Depends(get_db)):
    with _require_data_permission(plugin_id, "tasks.delete"):
        return host_delete_task(task_id, db=db)


@router.post("/{plugin_id}/ai/generate")
def plugin_ai_generate(
    plugin_id: str,
    payload: PluginAIGenerateRequest,
    db: Connection = Depends(get_db),
):
    with _require_data_permission(plugin_id, "ai.request"):
        try:
            return generate_plugin_ai_response(
                db,
                system_prompt=payload.system_prompt,
                prompt=payload.prompt,
            )
        except ProjectAssistantError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{plugin_id}/network/request")
def plugin_network_request(plugin_id: str, payload: PluginNetworkRequest):
    with _require_data_permission(plugin_id, "network.request"):
        try:
            return perform_plugin_network_request(
                url=payload.url,
                method=payload.method,
                headers=payload.headers,
                body=payload.body,
            )
        except PluginNetworkError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{plugin_id}/oauth/connect")
def plugin_oauth_connect(plugin_id: str, payload: PluginOAuthConnectionRequest):
    with _require_data_permission(plugin_id, "auth.oauth"):
        try:
            return start_plugin_oauth(plugin_id, payload.model_dump())
        except PluginOAuthError as exc:
            raise _plugin_oauth_http_error(exc) from exc


@router.get("/{plugin_id}/oauth/{connection_id}")
def plugin_oauth_status(plugin_id: str, connection_id: str):
    with _require_data_permission(plugin_id, "auth.oauth"):
        try:
            return get_plugin_oauth_status(plugin_id, connection_id)
        except PluginOAuthError as exc:
            raise _plugin_oauth_http_error(exc) from exc


@router.delete("/{plugin_id}/oauth/{connection_id}")
def plugin_oauth_disconnect(plugin_id: str, connection_id: str):
    with _require_data_permission(plugin_id, "auth.oauth"):
        try:
            return disconnect_plugin_oauth(plugin_id, connection_id)
        except PluginOAuthError as exc:
            raise _plugin_oauth_http_error(exc) from exc


@router.post("/{plugin_id}/oauth/{connection_id}/request")
def plugin_oauth_authenticated_request(plugin_id: str, connection_id: str, payload: PluginOAuthRequest):
    with _require_data_permission(plugin_id, "auth.oauth"):
        try:
            return plugin_oauth_request(
                plugin_id,
                connection_id,
                url=payload.url,
                method=payload.method,
                headers=payload.headers,
                body=payload.body,
            )
        except PluginOAuthError as exc:
            raise _plugin_oauth_http_error(exc) from exc


@router.delete("/{plugin_id}")
def delete_plugin(plugin_id: str, delete_data: bool = False):
    try:
        return remove_plugin(plugin_id, delete_data=delete_data)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.get("/{plugin_id}/export")
def export_plugin(plugin_id: str):
    try:
        content = export_plugin_archive(plugin_id)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{plugin_id}.zip"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{plugin_id}/panel")
def get_plugin_panel(plugin_id: str):
    try:
        path = plugin_resource_path(plugin_id, "panel.html")
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc
    if path.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="プラグイン画面のサイズが上限を超えています。")
    try:
        panel_html = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=415, detail="panel.htmlはUTF-8で作成してください。") from exc
    theme = get_active_theme()
    return Response(
        content=_inject_panel_theme_runtime(panel_html, theme),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": PANEL_CONTENT_SECURITY_POLICY,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/{plugin_id}/plugin-pages.css")
def get_active_theme_plugin_page_stylesheet(plugin_id: str):
    stylesheet = get_active_theme_page_stylesheet(plugin_id)
    return Response(
        content=stylesheet,
        media_type="text/css; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/{plugin_id}/assets/{relative_path:path}")
def get_plugin_asset(plugin_id: str, relative_path: str):
    try:
        path = plugin_resource_path(plugin_id, "assets/" + relative_path)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if media_type in {"text/html", "application/xhtml+xml"}:
        raise HTTPException(status_code=415, detail="HTMLファイルはプラグイン資産として配信できません。")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/{plugin_id}/storage/{key}")
def read_plugin_storage(plugin_id: str, key: str):
    try:
        return get_plugin_storage(plugin_id, key)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc


@router.put("/{plugin_id}/storage/{key}")
def write_plugin_storage(plugin_id: str, key: str, body: PluginStorageRequest):
    try:
        return put_plugin_storage(plugin_id, key, body.value)
    except PluginError as exc:
        raise _plugin_http_error(exc) from exc
