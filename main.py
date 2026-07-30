"""FastAPI entrypoint for the local clip-save backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from db import init_db
from ai_export import request_export
from routers import router
from maintenance import run_maintenance
from paths import get_uploads_dir, get_thumbnails_dir, get_local_files_dir, get_resource_dir
from ffmpeg_bootstrap import ensure_ffmpeg_async

UPLOADS_DIR = get_uploads_dir()
get_thumbnails_dir()
get_local_files_dir()

FRONTEND_DIR = get_resource_dir() / "frontend"

app = FastAPI(title="AI Clip Save API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


def _frontend_page(filename: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / filename, media_type="text/html")


@app.get("/", include_in_schema=False)
def root_page():
    return RedirectResponse(url="/Home")


@app.get("/Home", include_in_schema=False)
def home_page():
    return _frontend_page("index.html")


@app.get("/Notes", include_in_schema=False)
def notes_page():
    return _frontend_page("notes.html")


@app.get("/Projects", include_in_schema=False)
def projects_page():
    return _frontend_page("projects.html")


@app.get("/Note", include_in_schema=False)
def note_page():
    return _frontend_page("note-editor.html")


app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    run_maintenance()
    request_export(0.1)
    ensure_ffmpeg_async()
