"""FastAPI entrypoint for the local clip-save backend."""

import os

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from db import get_connection, init_db
from ai_export import clear_exported_files, request_export
from routers import router
from maintenance import SETTING_DEFAULTS, run_maintenance
from paths import get_uploads_dir, get_thumbnails_dir, get_local_files_dir, get_resource_dir
from version import APP_VERSION
from ffmpeg_bootstrap import ensure_ffmpeg_async
from migration import get_migration_status, run_migration
from setup import (
    advance_post_migration_onboarding,
    begin_setup_tutorial,
    begin_post_migration_onboarding,
    complete_post_migration_onboarding,
    complete_setup_tutorial,
    get_post_migration_onboarding_status,
    get_setup_status,
    get_setup_tutorial_status,
    mark_setup_complete,
    start_setup_tutorial,
)
from remote_auth import get_auth_store, get_client_auth_store, get_mcp_auth_store
from remote_client import RemoteClientError, get_remote_client
from remote_proxy import RemoteClientProxy

UPLOADS_DIR = get_uploads_dir()
get_thumbnails_dir()
get_local_files_dir()

FRONTEND_DIR = get_resource_dir() / "frontend"
BRAND_ICON_PATH = get_resource_dir() / "Icon.png"

app = FastAPI(title="Sparkle API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_remote_client_proxy = RemoteClientProxy(get_remote_client())


@app.middleware("http")
async def remote_client_proxy(request: Request, call_next):
    return await _remote_client_proxy.dispatch(request, call_next)

def _initialize_application_data() -> None:
    if getattr(app.state, "data_initialized", False):
        return
    if get_remote_client().is_enabled():
        app.state.data_initialized = False
        return
    init_db()
    run_maintenance()
    request_export(0.1)
    ensure_ffmpeg_async()
    from ai_import import start_watcher

    start_watcher()
    app.state.data_initialized = True


class InitialSetupPayload(BaseModel):
    flow: str = "initial"
    file_save_method: str = SETTING_DEFAULTS["file_save_method"]
    task_auto_delete: str = SETTING_DEFAULTS["task_auto_delete"]
    auto_create_note_on_project: bool = False
    ai_export_enabled: bool = True


class RemoteAccessModePayload(BaseModel):
    mode: str


class RemoteClientConnectPayload(BaseModel):
    server_url: str
    access_key: str


@app.get("/migration/status", include_in_schema=False)
def migration_status():
    return get_migration_status()


@app.post("/migration/run", include_in_schema=False)
def migration_run():
    result = run_migration(os.environ.get("SPARKLE_EXECUTABLE"))
    if result.get("ok"):
        _initialize_application_data()
        if not result.get("already_done"):
            begin_post_migration_onboarding()
    return result


@app.get("/setup/status", include_in_schema=False)
def setup_status():
    return get_setup_status()


@app.post("/setup/complete", include_in_schema=False)
def setup_complete(payload: InitialSetupPayload):
    if get_migration_status().get("required"):
        raise HTTPException(status_code=409, detail="先にデータ移行を完了してください。")
    if payload.flow not in {"initial", "migration"}:
        raise HTTPException(status_code=422, detail="初期設定フローが不正です。")
    if payload.flow == "migration":
        onboarding = get_post_migration_onboarding_status()
        if not onboarding.get("required") or onboarding.get("stage") != "setup":
            raise HTTPException(status_code=409, detail="移行後の設定確認はすでに完了しています。")

    if payload.file_save_method not in {"copy", "reference"}:
        raise HTTPException(status_code=422, detail="ファイル保存方式が不正です。")
    if payload.task_auto_delete not in {"3d", "1w", "1m", "never"}:
        raise HTTPException(status_code=422, detail="タスク自動削除の設定が不正です。")

    _initialize_application_data()
    with get_connection() as db:
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("file_save_method", payload.file_save_method),
        )
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("task_auto_delete", payload.task_auto_delete),
        )
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("ai_export_enabled", "true" if payload.ai_export_enabled else "false"),
        )
        db.commit()

    if not payload.ai_export_enabled:
        clear_exported_files()
    mark_setup_complete(payload.model_dump(exclude={"flow"}))
    if payload.flow == "migration":
        advance_post_migration_onboarding("extension")
    else:
        begin_setup_tutorial()
    return {"ok": True, "status": get_setup_status()}


@app.post("/setup/post-migration/complete", include_in_schema=False)
def complete_post_migration_setup():
    onboarding = get_post_migration_onboarding_status()
    if not onboarding.get("required"):
        return {"ok": True, "already_done": True}
    if onboarding.get("stage") != "extension":
        raise HTTPException(status_code=409, detail="先に移行後の設定確認を完了してください。")
    complete_post_migration_onboarding()
    return {"ok": True}


@app.get("/setup/tutorial/status", include_in_schema=False)
def setup_tutorial_status():
    return get_setup_tutorial_status()


@app.post("/setup/tutorial/start", include_in_schema=False)
def setup_tutorial_start():
    start_setup_tutorial()
    return {"ok": True, "status": get_setup_tutorial_status()}


@app.post("/setup/tutorial/complete", include_in_schema=False)
def setup_tutorial_complete():
    complete_setup_tutorial()
    return {"ok": True, "status": get_setup_tutorial_status()}


def _remote_access_manager():
    return getattr(app.state, "remote_access_manager", None)


@app.get("/settings/remote-client", include_in_schema=False)
def remote_client_status():
    return get_remote_client().status()


@app.post("/settings/remote-client/connect", include_in_schema=False)
def remote_client_connect(payload: RemoteClientConnectPayload):
    try:
        status = get_remote_client().configure(payload.server_url, payload.access_key)
        try:
            from ai_import import stop_watcher

            stop_watcher()
        except Exception:
            pass
        app.state.remote_data_mode = True
        return {"ok": True, "status": status, "reload_required": True}
    except RemoteClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/settings/remote-client/test", include_in_schema=False)
def remote_client_test():
    try:
        return {"ok": True, "status": get_remote_client().test_connection()}
    except RemoteClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/settings/remote-client/disconnect", include_in_schema=False)
def remote_client_disconnect():
    try:
        get_remote_client().disconnect()
    except RemoteClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    app.state.remote_data_mode = False
    if not get_migration_status().get("required") and not get_setup_status().get("required"):
        _initialize_application_data()
    return {"ok": True, "status": get_remote_client().status(), "reload_required": True}


@app.get("/settings/remote-access", include_in_schema=False)
def remote_access_status():
    manager = _remote_access_manager()
    if manager is not None:
        return manager.status()
    return {
        "mode": "tailscale",
        "web_mode": "funnel",
        "auth": get_auth_store().status(),
        "mcp_auth": get_mcp_auth_store().status(),
        "client_auth": get_client_auth_store().status(),
        "remote_server": False,
        "mcp_url": os.environ.get("SPARKLE_MCP_PUBLIC_URL"),
        "web_route": {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "Sparkleの実行管理がまだ開始されていません。",
        },
        "android": {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "Sparkleの実行管理がまだ開始されていません。",
        },
        "mcp_route": {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "Sparkleの実行管理がまだ開始されていません。",
        },
        "remote": {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "SparkleのリモートWeb管理を初期化できません。",
        },
        "funnel": {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "Sparkleの実行管理がまだ開始されていません。",
        },
        "last_error": None,
    }


app.include_router(router)


def _require_remote_access_manager():
    manager = _remote_access_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="SparkleのリモートWeb管理を初期化できません。")
    return manager


@app.post("/settings/remote-access/enable", include_in_schema=False)
def remote_access_enable():
    return _require_remote_access_manager().enable()


@app.post("/settings/remote-access/mcp/enable", include_in_schema=False)
def remote_mcp_enable():
    return _require_remote_access_manager().enable_mcp()


@app.post("/settings/remote-access/client/enable", include_in_schema=False)
def remote_client_enable():
    return _require_remote_access_manager().enable_client()


@app.post("/settings/remote-access/mode", include_in_schema=False)
def remote_access_set_mode(payload: RemoteAccessModePayload):
    return _require_remote_access_manager().set_mode(payload.mode)


@app.post("/settings/remote-access/retry", include_in_schema=False)
def remote_access_retry():
    return _require_remote_access_manager().retry()


@app.post("/settings/remote-access/disable", include_in_schema=False)
def remote_access_disable():
    return _require_remote_access_manager().disable()


@app.post("/settings/remote-access/rotate", include_in_schema=False)
def remote_access_rotate():
    return _require_remote_access_manager().rotate()


@app.post("/settings/remote-access/revoke-all", include_in_schema=False)
def remote_access_revoke_all():
    return _require_remote_access_manager().revoke_all()


@app.post("/settings/remote-access/mcp/retry", include_in_schema=False)
def remote_mcp_retry():
    return _require_remote_access_manager().retry()


@app.post("/settings/remote-access/mcp/disable", include_in_schema=False)
def remote_mcp_disable():
    return _require_remote_access_manager().disable_mcp()


@app.post("/settings/remote-access/mcp/rotate", include_in_schema=False)
def remote_mcp_rotate():
    return _require_remote_access_manager().rotate_mcp()


@app.post("/settings/remote-access/mcp/revoke-all", include_in_schema=False)
def remote_mcp_revoke_all():
    return _require_remote_access_manager().revoke_mcp_all()


@app.post("/settings/remote-access/client/retry", include_in_schema=False)
def remote_client_retry():
    return _require_remote_access_manager().retry()


@app.post("/settings/remote-access/client/disable", include_in_schema=False)
def remote_client_disable():
    return _require_remote_access_manager().disable_client()


@app.post("/settings/remote-access/client/rotate", include_in_schema=False)
def remote_client_rotate():
    return _require_remote_access_manager().rotate_client()


@app.post("/settings/remote-access/client/revoke-all", include_in_schema=False)
def remote_client_revoke_all():
    return _require_remote_access_manager().revoke_client_all()


@app.get("/health")
def health():
    return {"status": "ok", "app": "Sparkle"}


@app.post("/app/activate", include_in_schema=False)
def activate_app() -> Response:
    """Bring the already-running desktop window to the foreground."""
    callback = getattr(app.state, "desktop_activate", None)
    if callable(callback):
        callback()
    return Response(status_code=204)


def _frontend_page(filename: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / filename, media_type="text/html")


@app.get("/icon.png", include_in_schema=False)
def brand_icon() -> FileResponse:
    return FileResponse(BRAND_ICON_PATH, media_type="image/png")


@app.get("/", include_in_schema=False)
def root_page():
    return RedirectResponse(url="/Home")


@app.get("/Home", include_in_schema=False)
def home_page():
    if get_migration_status().get("required"):
        return RedirectResponse(url="/Migration")
    if get_setup_status().get("required"):
        return RedirectResponse(url="/Setup")
    return _frontend_page("index.html")


@app.get("/Migration", include_in_schema=False)
def migration_page():
    return _frontend_page("migration.html")


@app.get("/Setup", include_in_schema=False)
def setup_page():
    return _frontend_page("setup.html")


@app.get("/Tutorial", include_in_schema=False)
def tutorial_page():
    return _frontend_page("tutorial.html")


@app.get("/ExtensionGuide", include_in_schema=False)
def extension_guide_page():
    return _frontend_page("extension-guide.html")


@app.get("/Notes", include_in_schema=False)
def notes_page():
    return _frontend_page("notes.html")


@app.get("/Projects", include_in_schema=False)
def projects_page():
    return _frontend_page("projects.html")


@app.get("/Settings", include_in_schema=False)
def settings_page():
    return _frontend_page("settings.html")


@app.get("/Profile", include_in_schema=False)
def profile_page():
    return _frontend_page("profile.html")


@app.get("/Note", include_in_schema=False)
def note_page():
    return _frontend_page("note-editor.html")


app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.on_event("startup")
def _startup() -> None:
    if get_migration_status().get("required") or get_setup_status().get("required"):
        app.state.data_initialized = False
        return
    if get_remote_client().is_enabled():
        # The client shell still serves its local HTML and connection settings,
        # but must not run maintenance/export/watchers against the fallback DB
        # while remote data mode is active.
        app.state.data_initialized = False
        app.state.remote_data_mode = True
        return
    app.state.remote_data_mode = False
    _initialize_application_data()
