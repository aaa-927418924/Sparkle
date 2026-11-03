"""HTTP routes for local Sparkle plugin management."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from plugin_manager import (
    MAX_ARCHIVE_BYTES,
    PluginError,
    export_plugin_archive,
    get_active_theme,
    install_authoring_skill,
    install_plugin_archive,
    list_plugins,
    plugin_resource_path,
    put_plugin_storage,
    get_plugin_storage,
    remove_plugin,
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


class PluginEnabledRequest(BaseModel):
    enabled: bool


class ActiveThemeRequest(BaseModel):
    plugin_id: str | None = None


class PluginStorageRequest(BaseModel):
    value: object


def _plugin_http_error(exc: PluginError) -> HTTPException:
    text = str(exc)
    status = 409 if "すでにあります" in text else 400
    if "見つかりません" in text:
        status = 404
    return HTTPException(status_code=status, detail=text)


@router.get("")
def get_plugins():
    return list_plugins()


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
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": PANEL_CONTENT_SECURITY_POLICY,
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
