"""FastAPI entrypoint for the local clip-save backend."""

import os

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from db import get_connection, init_db
from ai_export import clear_exported_files, request_export
from routers import router
from maintenance import SETTING_DEFAULTS, run_maintenance
from paths import get_uploads_dir, get_thumbnails_dir, get_local_files_dir, get_resource_dir
from ffmpeg_bootstrap import ensure_ffmpeg_async
from migration import get_migration_status, run_migration
from setup import get_setup_status, mark_setup_complete

UPLOADS_DIR = get_uploads_dir()
get_thumbnails_dir()
get_local_files_dir()

FRONTEND_DIR = get_resource_dir() / "frontend"
BRAND_ICON_PATH = get_resource_dir() / "Icon.png"

app = FastAPI(title="Sparkle API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _initialize_application_data() -> None:
    if getattr(app.state, "data_initialized", False):
        return
    init_db()
    run_maintenance()
    request_export(0.1)
    ensure_ffmpeg_async()
    app.state.data_initialized = True


class InitialSetupPayload(BaseModel):
    file_save_method: str = SETTING_DEFAULTS["file_save_method"]
    task_auto_delete: str = SETTING_DEFAULTS["task_auto_delete"]
    auto_create_note_on_task: bool = False
    auto_create_note_on_project: bool = False
    ai_export_enabled: bool = True


@app.get("/migration/status", include_in_schema=False)
def migration_status():
    return get_migration_status()


@app.post("/migration/run", include_in_schema=False)
def migration_run():
    result = run_migration(os.environ.get("SPARKLE_EXECUTABLE"))
    if result.get("ok"):
        _initialize_application_data()
    return result


@app.get("/setup/status", include_in_schema=False)
def setup_status():
    return get_setup_status()


@app.post("/setup/complete", include_in_schema=False)
def setup_complete(payload: InitialSetupPayload):
    if get_migration_status().get("required"):
        raise HTTPException(status_code=409, detail="先にデータ移行を完了してください。")

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
    mark_setup_complete(payload.model_dump())
    return {"ok": True, "status": get_setup_status()}


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


@app.get("/Notes", include_in_schema=False)
def notes_page():
    return _frontend_page("notes.html")


@app.get("/Projects", include_in_schema=False)
def projects_page():
    return _frontend_page("projects.html")


@app.get("/Settings", include_in_schema=False)
def settings_page():
    return _frontend_page("settings.html")


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
    _initialize_application_data()
