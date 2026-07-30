"""FastAPI entrypoint for the local clip-save backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db import init_db
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


app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    run_maintenance()
    ensure_ffmpeg_async()
