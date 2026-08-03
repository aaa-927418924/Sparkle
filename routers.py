"""API routers for clips, categories and tags."""

import base64
import binascii
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from sqlite3 import Connection

from crud import get_or_create_category, get_or_create_tag
from db import DB_PATH, get_connection, init_db
from ai_export import (
    clear_exported_files,
    export_now,
    get_status as get_ai_export_status,
    open_export_folder,
)
from paths import get_local_files_dir, get_uploads_dir
from ffmpeg_bootstrap import get_ffmpeg_path
from maintenance import (
    THUMBNAILS_DIR,
    delete_thumbnail_file,
    run_maintenance,
)
from schemas import (
    CategoryCreate,
    CategoryOut,
    ClipCreate,
    ClipOut,
    ClipUpdate,
    LightClipOut,
    LightNoteOut,
    LightTaskOut,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TagCreate,
    TagOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)


def _run_windows_forms_dialog(script: str) -> List[str]:
    """Run a Windows picker and return record-separator-delimited paths."""
    if os.name != "nt":
        raise RuntimeError("Windowsのファイル選択ダイアログは利用できません")

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = (
        system_root
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-STA",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise RuntimeError("Windows標準ダイアログを起動できませんでした") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "Windows標準ダイアログがエラーを返しました"
        raise RuntimeError(detail)
    return [path for path in result.stdout.split("\x1e") if path]


def _choose_files_with_windows_dialog() -> List[str]:
    return _run_windows_forms_dialog(
        r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'アップロードするファイルを選択'
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Write(($dialog.FileNames -join [char]30))
}
"""
    )


def _choose_directory_with_windows_dialog() -> Optional[str]:
    paths = _run_windows_forms_dialog(
        r"""
Add-Type @'
using System;
using System.Runtime.InteropServices;

[Flags]
public enum SparkleFileOpenOptions : uint
{
    FOS_OVERWRITEPROMPT = 0x00000002,
    FOS_STRICTFILETYPES = 0x00000004,
    FOS_NOCHANGEDIR = 0x00000008,
    FOS_PICKFOLDERS = 0x00000020,
    FOS_FORCEFILESYSTEM = 0x00000040,
    FOS_PATHMUSTEXIST = 0x00000800,
    FOS_FILEMUSTEXIST = 0x00001000,
}

public enum SparkleSigdn : uint
{
    SIGDN_FILESYSPATH = 0x80058000,
}

[ComImport]
[Guid("42f85136-db7e-439c-85f1-e4075d135fc8")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface SparkleIFileDialog
{
    [PreserveSig] int Show(IntPtr parent);
    [PreserveSig] int SetFileTypes(uint count, IntPtr filters);
    [PreserveSig] int SetFileTypeIndex(uint index);
    [PreserveSig] int GetFileTypeIndex(out uint index);
    [PreserveSig] int Advise(IntPtr events, out uint cookie);
    [PreserveSig] int Unadvise(uint cookie);
    [PreserveSig] int SetOptions(SparkleFileOpenOptions options);
    [PreserveSig] int GetOptions(out SparkleFileOpenOptions options);
    [PreserveSig] int SetDefaultFolder(SparkleIShellItem item);
    [PreserveSig] int SetFolder(SparkleIShellItem item);
    [PreserveSig] int GetFolder(out SparkleIShellItem item);
    [PreserveSig] int GetCurrentSelection(out SparkleIShellItem item);
    [PreserveSig] int SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
    [PreserveSig] int GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
    [PreserveSig] int SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    [PreserveSig] int SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    [PreserveSig] int SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    [PreserveSig] int GetResult(out SparkleIShellItem item);
    [PreserveSig] int AddPlace(SparkleIShellItem item, uint placement);
    [PreserveSig] int SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
    [PreserveSig] int Close(int result);
    [PreserveSig] int SetClientGuid(ref Guid guid);
    [PreserveSig] int ClearClientData();
    [PreserveSig] int SetFilter(IntPtr filter);
}

[ComImport]
[Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface SparkleIShellItem
{
    [PreserveSig] int BindToHandler(IntPtr bindingContext, ref Guid handlerId, ref Guid interfaceId, out IntPtr result);
    [PreserveSig] int GetParent(out SparkleIShellItem parent);
    [PreserveSig] int GetDisplayName(SparkleSigdn nameType, out IntPtr name);
    [PreserveSig] int GetAttributes(uint mask, out uint attributes);
    [PreserveSig] int Compare(SparkleIShellItem item, uint hint, out int order);
}

public static class SparkleFolderPicker
{
    public static string Pick()
    {
        var dialogType = Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"));
        var dialog = (SparkleIFileDialog)Activator.CreateInstance(dialogType);
        try
        {
            SparkleFileOpenOptions options;
            dialog.GetOptions(out options);
            options |= SparkleFileOpenOptions.FOS_PICKFOLDERS
                | SparkleFileOpenOptions.FOS_FORCEFILESYSTEM
                | SparkleFileOpenOptions.FOS_PATHMUSTEXIST;
            dialog.SetOptions(options);
            dialog.SetTitle("バックアップの保存先を選択");
            dialog.SetOkButtonLabel("このフォルダーを選択");
            if (dialog.Show(IntPtr.Zero) != 0) return string.Empty;

            SparkleIShellItem item;
            if (dialog.GetResult(out item) != 0 || item == null) return string.Empty;
            IntPtr name;
            if (item.GetDisplayName(SparkleSigdn.SIGDN_FILESYSPATH, out name) != 0 || name == IntPtr.Zero) return string.Empty;
            try { return Marshal.PtrToStringUni(name) ?? string.Empty; }
            finally { Marshal.FreeCoTaskMem(name); }
        }
        finally
        {
            if (dialog != null) Marshal.ReleaseComObject(dialog);
        }
    }
}
'@
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$selected = [SparkleFolderPicker]::Pick()
if ($selected) { [Console]::Write($selected) }
"""
    )
    return paths[0] if paths else None


router = APIRouter()


def get_db() -> Connection:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _fetch_tags(conn: Connection, clip_id: int) -> List[TagOut]:
    rows = conn.execute(
        "SELECT t.id, t.name FROM tags t "
        "JOIN clip_tags ct ON ct.tag_id = t.id "
        "WHERE ct.clip_id = ? ORDER BY t.name",
        (clip_id,),
    ).fetchall()
    return [TagOut(id=r["id"], name=r["name"]) for r in rows]


def _fetch_project_ids(conn: Connection, table: str, entity_column: str, entity_id: int) -> List[int]:
    rows = conn.execute(
        f"SELECT project_id FROM {table} WHERE {entity_column} = ? ORDER BY project_id",
        (entity_id,),
    ).fetchall()
    return [int(r["project_id"]) for r in rows]


def _fetch_task_ids(conn: Connection, note_id: int) -> List[int]:
    rows = conn.execute(
        "SELECT task_id FROM task_notes WHERE note_id = ? ORDER BY task_id",
        (note_id,),
    ).fetchall()
    return [int(r["task_id"]) for r in rows]


def _row_to_clip(conn: Connection, row) -> ClipOut:
    return ClipOut(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        thumbnail_url=row["thumbnail_url"],
        comment=row["comment"],
        category_id=row["category_id"],
        is_favorite=bool(row["is_favorite"]),
        created_at=row["created_at"],
        clip_type=row["clip_type"] or "url",
        file_ref=row["file_ref"],
        file_size=row["file_size"],
        project_id=row["project_id"],
        project_ids=_fetch_project_ids(conn, "project_clips", "clip_id", row["id"]) or (
            [row["project_id"]] if row["project_id"] is not None else []
        ),
        tags=_fetch_tags(conn, row["id"]),
    )


def _set_tags(conn: Connection, clip_id: int, tag_ids: List[int]) -> None:
    conn.execute("DELETE FROM clip_tags WHERE clip_id = ?", (clip_id,))
    for tag_id in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id) VALUES (?, ?)",
            (clip_id, tag_id),
        )


def _resolve_tags(conn: Connection, names: List[str]) -> List[int]:
    return [get_or_create_tag(conn, name) for name in names]


def _resolve_category(conn: Connection, name: Optional[str]) -> Optional[int]:
    if name is None:
        return None
    return get_or_create_category(conn, name)


# --- Categories ---------------------------------------------------------


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(db: Connection = Depends(get_db)):
    rows = db.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
    return [CategoryOut(id=r["id"], name=r["name"]) for r in rows]


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Connection = Depends(get_db)):
    try:
        cur = db.execute("INSERT INTO categories(name) VALUES (?)", (payload.name,))
        db.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="Category already exists")
    return CategoryOut(id=cur.lastrowid, name=payload.name)


# --- Tags ---------------------------------------------------------------


@router.get("/tags", response_model=List[TagOut])
def list_tags(db: Connection = Depends(get_db)):
    rows = db.execute("SELECT id, name FROM tags ORDER BY name").fetchall()
    return [TagOut(id=r["id"], name=r["name"]) for r in rows]


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(payload: TagCreate, db: Connection = Depends(get_db)):
    try:
        cur = db.execute("INSERT INTO tags(name) VALUES (?)", (payload.name,))
        db.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="Tag already exists")
    return TagOut(id=cur.lastrowid, name=payload.name)


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM categories WHERE id = ?", (category_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    db.commit()


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM tags WHERE id = ?", (tag_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    db.commit()


# --- Projects ------------------------------------------------------------


@router.get("/projects", response_model=List[ProjectOut])
def list_projects(
    done: Optional[bool] = Query(None),
    db: Connection = Depends(get_db),
):
    sql = "SELECT * FROM projects"
    params: list = []
    if done is not None:
        sql += " WHERE is_done = ?"
        params.append(1 if done else 0)
    sql += " ORDER BY created_at DESC"
    rows = db.execute(sql, params).fetchall()
    return [ProjectOut(id=r["id"], name=r["name"], description=r["description"], is_done=bool(r["is_done"]), created_at=r["created_at"]) for r in rows]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Connection = Depends(get_db)):
    cur = db.execute(
        "INSERT INTO projects(name, description) VALUES (?, ?)",
        (payload.name, payload.description),
    )
    db.commit()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return ProjectOut(id=row["id"], name=row["name"], description=row["description"], is_done=bool(row["is_done"]), created_at=row["created_at"])


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut(id=row["id"], name=row["name"], description=row["description"], is_done=bool(row["is_done"]), created_at=row["created_at"])


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id, is_done, done_snapshot FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.name is not None:
        db.execute("UPDATE projects SET name = ? WHERE id = ?", (payload.name, project_id))
    if payload.description is not None:
        db.execute("UPDATE projects SET description = ? WHERE id = ?", (payload.description, project_id))
    if payload.is_done is not None and payload.is_done != bool(row["is_done"]):
        if payload.is_done:
            # Going done → save snapshot of currently undone tasks
            undone = db.execute(
                "SELECT id FROM tasks WHERE project_id = ? AND is_done = 0", (project_id,)
            ).fetchall()
            snapshot = [t["id"] for t in undone]
            db.execute("UPDATE projects SET is_done = 1, done_snapshot = ? WHERE id = ?",
                       (json.dumps(snapshot) if snapshot else "[]", project_id))
            if snapshot:
                db.execute(
                    "UPDATE tasks SET is_done = 1, completed_at = datetime('now') WHERE id IN ({})".format(
                        ",".join("?" for _ in snapshot)
                    ),
                    snapshot,
                )
        else:
            # Going undone → restore only the tasks that were cascaded
            current_snapshot = row["done_snapshot"]
            if current_snapshot:
                task_ids = json.loads(current_snapshot)
                if task_ids:
                    db.execute(
                        "UPDATE tasks SET is_done = 0, completed_at = NULL WHERE id IN ({}) AND is_done = 1".format(
                            ",".join("?" for _ in task_ids)
                        ),
                        task_ids,
                    )
            db.execute("UPDATE projects SET is_done = 0, done_snapshot = NULL WHERE id = ?", (project_id,))
    elif payload.is_done is not None:
        # Same state — no-op, but update snapshot if explicitly passed
        pass
    db.commit()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return ProjectOut(id=row["id"], name=row["name"], description=row["description"], is_done=bool(row["is_done"]), created_at=row["created_at"])


@router.patch("/projects/{project_id}/toggle", response_model=ProjectOut)
def toggle_project(project_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if row["is_done"]:
        # Going undone → restore only the tasks that were cascaded
        current_snapshot = row["done_snapshot"]
        if current_snapshot:
            task_ids = json.loads(current_snapshot)
            if task_ids:
                db.execute(
                    "UPDATE tasks SET is_done = 0, completed_at = NULL WHERE id IN ({}) AND is_done = 1".format(
                        ",".join("?" for _ in task_ids)
                    ),
                    task_ids,
                )
        db.execute("UPDATE projects SET is_done = 0, done_snapshot = NULL WHERE id = ?", (project_id,))
    else:
        # Going done → save snapshot of currently undone tasks
        undone = db.execute(
            "SELECT id FROM tasks WHERE project_id = ? AND is_done = 0", (project_id,)
        ).fetchall()
        snapshot = [t["id"] for t in undone]
        db.execute("UPDATE projects SET is_done = 1, done_snapshot = ? WHERE id = ?",
                   (json.dumps(snapshot) if snapshot else "[]", project_id))
        if snapshot:
            db.execute(
                "UPDATE tasks SET is_done = 1, completed_at = datetime('now') WHERE id IN ({})".format(
                    ",".join("?" for _ in snapshot)
                ),
                snapshot,
            )
    db.commit()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return ProjectOut(id=row["id"], name=row["name"], description=row["description"], is_done=bool(row["is_done"]), created_at=row["created_at"])


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()


@router.post("/projects/{project_id}/clips/{clip_id}", response_model=ClipOut)
def link_project_clip(project_id: int, clip_id: int, db: Connection = Depends(get_db)):
    project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    clip = db.execute("SELECT id, project_id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    db.execute(
        "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
        (project_id, clip_id),
    )
    if clip["project_id"] is None:
        db.execute("UPDATE clips SET project_id = ? WHERE id = ?", (project_id, clip_id))
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


@router.delete("/projects/{project_id}/clips/{clip_id}", status_code=204)
def unlink_project_clip(project_id: int, clip_id: int, db: Connection = Depends(get_db)):
    clip = db.execute("SELECT id, project_id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    db.execute(
        "DELETE FROM project_clips WHERE project_id = ? AND clip_id = ?",
        (project_id, clip_id),
    )
    if clip["project_id"] == project_id:
        next_link = db.execute(
            "SELECT MIN(project_id) AS project_id FROM project_clips WHERE clip_id = ?",
            (clip_id,),
        ).fetchone()
        db.execute(
            "UPDATE clips SET project_id = ? WHERE id = ?",
            (next_link["project_id"], clip_id),
        )
    db.commit()


@router.post("/projects/{project_id}/notes/{note_id}", response_model=NoteOut)
def link_project_note(project_id: int, note_id: int, db: Connection = Depends(get_db)):
    project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    note = db.execute("SELECT id, project_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.execute(
        "INSERT OR IGNORE INTO project_notes(project_id, note_id) VALUES (?, ?)",
        (project_id, note_id),
    )
    if note["project_id"] is None:
        db.execute("UPDATE notes SET project_id = ? WHERE id = ?", (project_id, note_id))
    db.commit()
    row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row_to_note(db, row)


@router.delete("/projects/{project_id}/notes/{note_id}", status_code=204)
def unlink_project_note(project_id: int, note_id: int, db: Connection = Depends(get_db)):
    note = db.execute("SELECT id, project_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.execute(
        "DELETE FROM project_notes WHERE project_id = ? AND note_id = ?",
        (project_id, note_id),
    )
    if note["project_id"] == project_id:
        next_link = db.execute(
            "SELECT MIN(project_id) AS project_id FROM project_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()
        db.execute(
            "UPDATE notes SET project_id = ? WHERE id = ?",
            (next_link["project_id"], note_id),
        )
    db.commit()


# --- Clips --------------------------------------------------------------


@router.post("/clips", response_model=ClipOut, status_code=201)
def create_clip(payload: ClipCreate, db: Connection = Depends(get_db)):
    category_id = _resolve_category(db, payload.category)
    tag_ids = _resolve_tags(db, payload.tags)

    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, project_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            payload.url,
            payload.title,
            payload.thumbnail_url,
            payload.comment,
            category_id,
            payload.clip_type or "url",
            payload.file_ref,
            payload.project_id,
        ),
    )
    clip_id = cur.lastrowid
    _set_tags(db, clip_id, tag_ids)
    if payload.project_id is not None:
        db.execute(
            "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
            (payload.project_id, clip_id),
        )
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


@router.get("/clips", response_model=List[ClipOut])
def list_clips(
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    exclude_project: Optional[int] = Query(None),
    db: Connection = Depends(get_db),
):
    sql = "SELECT * FROM clips"
    conditions = []
    params: list = []
    if category is not None:
        conditions.append(
            "category_id = (SELECT id FROM categories WHERE name = ?)"
        )
        params.append(category)
    if tag is not None:
        conditions.append(
            "id IN (SELECT clip_id FROM clip_tags "
            "WHERE tag_id = (SELECT id FROM tags WHERE name = ?))"
        )
        params.append(tag)
    if project_id is not None:
        conditions.append(
            "id IN (SELECT clip_id FROM project_clips WHERE project_id = ?)"
        )
        params.append(project_id)
    if exclude_project is not None:
        conditions.append(
            "id NOT IN (SELECT clip_id FROM project_clips WHERE project_id = ?)"
        )
        params.append(exclude_project)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC"

    rows = db.execute(sql, params).fetchall()
    return [_row_to_clip(db, r) for r in rows]


@router.get("/clips/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _row_to_clip(db, row)


@router.put("/clips/{clip_id}", response_model=ClipOut)
def update_clip(clip_id: int, payload: ClipUpdate, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")

    if "title" in payload.model_fields_set:
        db.execute("UPDATE clips SET title = ? WHERE id = ?", (payload.title, clip_id))
    if "comment" in payload.model_fields_set:
        db.execute("UPDATE clips SET comment = ? WHERE id = ?", (payload.comment, clip_id))
    if "category" in payload.model_fields_set:
        category_id = _resolve_category(db, payload.category)
        db.execute(
            "UPDATE clips SET category_id = ? WHERE id = ?", (category_id, clip_id)
        )
    if payload.tags is not None:
        tag_ids = _resolve_tags(db, payload.tags)
        _set_tags(db, clip_id, tag_ids)
    if payload.thumbnail_url is not None:
        db.execute(
            "UPDATE clips SET thumbnail_url = ? WHERE id = ?",
            (payload.thumbnail_url, clip_id),
        )
    if "project_ids" in payload.model_fields_set and payload.project_ids is not None:
        for project_id in payload.project_ids:
            project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not project:
                raise HTTPException(status_code=400, detail=f"project_id {project_id} does not exist")
        db.execute("DELETE FROM project_clips WHERE clip_id = ?", (clip_id,))
        for project_id in payload.project_ids:
            db.execute(
                "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
                (project_id, clip_id),
            )
        legacy_project_id = payload.project_ids[0] if payload.project_ids else None
        db.execute("UPDATE clips SET project_id = ? WHERE id = ?", (legacy_project_id, clip_id))
    elif "project_id" in payload.model_fields_set:
        if payload.project_id is None:
            db.execute("DELETE FROM project_clips WHERE clip_id = ?", (clip_id,))
        else:
            project = db.execute("SELECT id FROM projects WHERE id = ?", (payload.project_id,)).fetchone()
            if not project:
                raise HTTPException(status_code=400, detail="project_id does not exist")
            db.execute(
                "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
                (payload.project_id, clip_id),
            )
        db.execute("UPDATE clips SET project_id = ? WHERE id = ?", (payload.project_id, clip_id))
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


@router.delete("/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: int, db: Connection = Depends(get_db)):
    row = db.execute(
        "SELECT id, thumbnail_url, url, file_ref FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    thumbnail_url = row["thumbnail_url"]
    clip_url = row["url"]
    file_ref = row["file_ref"]
    db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    db.commit()
    delete_thumbnail_file(thumbnail_url)
    # Only delete the file from disk for copy mode (we own the file).
    # Reference mode stores the original path — never delete that.
    if file_ref == "copy" and clip_url and clip_url.startswith("local://"):
        local_file = LOCAL_DIR / clip_url.split("/")[-1]
        if local_file.is_file():
            local_file.unlink(missing_ok=True)


class FavoriteOut(BaseModel):
    id: int
    is_favorite: bool


@router.patch("/clips/{clip_id}/favorite", response_model=FavoriteOut)
def toggle_favorite(clip_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id, is_favorite FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    new_value = 0 if row["is_favorite"] else 1
    db.execute("UPDATE clips SET is_favorite = ? WHERE id = ?", (new_value, clip_id))
    db.commit()
    return FavoriteOut(id=clip_id, is_favorite=bool(new_value))


# --- Tasks ---------------------------------------------------------------


def _light_clip(db: Connection, clip_id: Optional[int]) -> Optional[LightClipOut]:
    if clip_id is None:
        return None
    row = db.execute(
        "SELECT id, title, url FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        return None
    return LightClipOut(id=row["id"], title=row["title"], url=row["url"])


def _linked_notes(db: Connection, task_id: int) -> List["LightNoteOut"]:
    rows = db.execute(
        "SELECT DISTINCT n.id, n.title FROM notes n "
        "LEFT JOIN task_notes tn ON tn.note_id = n.id "
        "WHERE n.task_id = ? OR tn.task_id = ? "
        "ORDER BY n.updated_at DESC",
        (task_id, task_id),
    ).fetchall()
    return [LightNoteOut(id=r["id"], title=r["title"]) for r in rows]


def _row_to_task(db: Connection, row) -> TaskOut:
    return TaskOut(
        id=row["id"],
        title=row["title"],
        is_done=bool(row["is_done"]),
        clip_id=row["clip_id"],
        due_date=row["due_date"],
        priority=row["priority"],
        created_at=row["created_at"],
        project_id=row["project_id"],
        clip=_light_clip(db, row["clip_id"]),
        notes=_linked_notes(db, row["id"]),
    )


def _check_priority(priority: Optional[int]) -> None:
    if priority is not None and not (1 <= priority <= 5):
        raise HTTPException(status_code=400, detail="priority must be between 1 and 5")


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Connection = Depends(get_db)):
    _check_priority(payload.priority)
    if payload.clip_id is not None:
        clip = db.execute("SELECT id FROM clips WHERE id = ?", (payload.clip_id,)).fetchone()
        if not clip:
            raise HTTPException(status_code=400, detail="clip_id does not exist")
    cur = db.execute(
        "INSERT INTO tasks(title, clip_id, due_date, priority, project_id) VALUES (?, ?, ?, ?, ?)",
        (payload.title, payload.clip_id, payload.due_date, payload.priority, payload.project_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_task(db, row)


@router.get("/tasks", response_model=List[TaskOut])
def list_tasks(
    done: Optional[bool] = Query(None),
    project_id: Optional[int] = Query(None),
    exclude_project: Optional[int] = Query(None),
    db: Connection = Depends(get_db),
):
    sql = "SELECT * FROM tasks"
    conditions = []
    params: list = []
    if done is not None:
        conditions.append("is_done = ?")
        params.append(1 if done else 0)
    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)
    if exclude_project is not None:
        conditions.append("project_id != ?")
        params.append(exclude_project)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC"
    rows = db.execute(sql, params).fetchall()
    return [_row_to_task(db, r) for r in rows]


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return _row_to_task(db, row)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    _check_priority(payload.priority)

    if payload.title is not None:
        db.execute("UPDATE tasks SET title = ? WHERE id = ?", (payload.title, task_id))
    if payload.is_done is not None:
        if payload.is_done:
            db.execute(
                "UPDATE tasks SET is_done = 1, completed_at = datetime('now') WHERE id = ?",
                (task_id,),
            )
        else:
            db.execute(
                "UPDATE tasks SET is_done = 0, completed_at = NULL WHERE id = ?",
                (task_id,),
            )
    if payload.clip_id is not None:
        clip = db.execute(
            "SELECT id FROM clips WHERE id = ?", (payload.clip_id,)
        ).fetchone()
        if not clip:
            raise HTTPException(status_code=400, detail="clip_id does not exist")
        db.execute("UPDATE tasks SET clip_id = ? WHERE id = ?", (payload.clip_id, task_id))
    if "due_date" in payload.model_fields_set:
        db.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (payload.due_date, task_id))
    if "priority" in payload.model_fields_set:
        db.execute("UPDATE tasks SET priority = ? WHERE id = ?", (payload.priority, task_id))
    if "project_id" in payload.model_fields_set:
        db.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (payload.project_id, task_id))
    db.commit()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(db, row)


@router.patch("/tasks/{task_id}/toggle", response_model=TaskOut)
def toggle_task(task_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    new_value = 0 if row["is_done"] else 1
    if new_value:
        db.execute(
            "UPDATE tasks SET is_done = ?, completed_at = datetime('now') WHERE id = ?",
            (new_value, task_id),
        )
    else:
        db.execute(
            "UPDATE tasks SET is_done = ?, completed_at = NULL WHERE id = ?",
            (new_value, task_id),
        )
    db.commit()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(db, row)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()


# --- Notes ---------------------------------------------------------------


def _fetch_note_clips(db: Connection, note_id: int) -> List[LightClipOut]:
    rows = db.execute(
        "SELECT c.id, c.title, c.url, c.thumbnail_url, c.comment FROM clips c "
        "JOIN note_clips nc ON nc.clip_id = c.id "
        "WHERE nc.note_id = ? ORDER BY c.id",
        (note_id,),
    ).fetchall()
    return [
        LightClipOut(
            id=r["id"],
            title=r["title"],
            url=r["url"],
            thumbnail_url=r["thumbnail_url"],
            comment=r["comment"],
            tags=_fetch_tags(db, r["id"]),
        )
        for r in rows
    ]


def _linked_task(db: Connection, task_id: Optional[int]) -> Optional[LightTaskOut]:
    if task_id is None:
        return None
    row = db.execute(
        "SELECT id, title, is_done FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        return None
    return LightTaskOut(id=row["id"], title=row["title"], is_done=bool(row["is_done"]))


def _row_to_note(db: Connection, row) -> NoteOut:
    task_ids = _fetch_task_ids(db, row["id"]) or (
        [row["task_id"]] if row["task_id"] is not None else []
    )
    project_ids = _fetch_project_ids(db, "project_notes", "note_id", row["id"]) or (
        [row["project_id"]] if row["project_id"] is not None else []
    )
    legacy_task_id = task_ids[0] if task_ids else None
    return NoteOut(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        clips=_fetch_note_clips(db, row["id"]),
        task_id=legacy_task_id,
        task=_linked_task(db, legacy_task_id),
        task_ids=task_ids,
        project_id=project_ids[0] if project_ids else None,
        project_ids=project_ids,
    )


def _set_note_task_links(db: Connection, note_id: int, task_ids: List[int]) -> None:
    for task_id in task_ids:
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=400, detail=f"task_id {task_id} does not exist")
    db.execute("DELETE FROM task_notes WHERE note_id = ?", (note_id,))
    for task_id in task_ids:
        db.execute(
            "INSERT OR IGNORE INTO task_notes(task_id, note_id) VALUES (?, ?)",
            (task_id, note_id),
        )
    legacy_task_id = task_ids[0] if task_ids else None
    db.execute("UPDATE notes SET task_id = ? WHERE id = ?", (legacy_task_id, note_id))


def _set_note_project_links(db: Connection, note_id: int, project_ids: List[int]) -> None:
    for project_id in project_ids:
        project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=400, detail=f"project_id {project_id} does not exist")
    db.execute("DELETE FROM project_notes WHERE note_id = ?", (note_id,))
    for project_id in project_ids:
        db.execute(
            "INSERT OR IGNORE INTO project_notes(project_id, note_id) VALUES (?, ?)",
            (project_id, note_id),
        )
    legacy_project_id = project_ids[0] if project_ids else None
    db.execute("UPDATE notes SET project_id = ? WHERE id = ?", (legacy_project_id, note_id))


def _set_note_clips(db: Connection, note_id: int, clip_ids: List[int]) -> None:
    db.execute("DELETE FROM note_clips WHERE note_id = ?", (note_id,))
    for clip_id in clip_ids:
        db.execute(
            "INSERT OR IGNORE INTO note_clips(note_id, clip_id) VALUES (?, ?)",
            (note_id, clip_id),
        )


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(payload: NoteCreate, db: Connection = Depends(get_db)):
    task_ids = list(payload.task_ids) if payload.task_ids else (
        [payload.task_id] if payload.task_id is not None else []
    )
    project_ids = list(payload.project_ids) if payload.project_ids else (
        [payload.project_id] if payload.project_id is not None else []
    )
    for task_id in task_ids:
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=400, detail=f"task_id {task_id} does not exist")
    for project_id in project_ids:
        project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=400, detail=f"project_id {project_id} does not exist")
    for clip_id in payload.clip_ids:
        clip = db.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip:
            raise HTTPException(status_code=400, detail=f"clip_id {clip_id} does not exist")
    cur = db.execute(
        "INSERT INTO notes(title, body, task_id, project_id) VALUES (?, ?, ?, ?)",
        (
            payload.title,
            payload.body,
            task_ids[0] if task_ids else None,
            project_ids[0] if project_ids else None,
        ),
    )
    note_id = cur.lastrowid
    _set_note_clips(db, note_id, payload.clip_ids)
    _set_note_task_links(db, note_id, task_ids)
    _set_note_project_links(db, note_id, project_ids)
    db.commit()
    row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row_to_note(db, row)


@router.get("/notes", response_model=List[NoteOut])
def list_notes(
    project_id: Optional[int] = Query(None),
    exclude_project: Optional[int] = Query(None),
    db: Connection = Depends(get_db),
):
    sql = "SELECT * FROM notes"
    conditions = []
    params: list = []
    if project_id is not None:
        conditions.append(
            "id IN (SELECT note_id FROM project_notes WHERE project_id = ?)"
        )
        params.append(project_id)
    if exclude_project is not None:
        conditions.append(
            "id NOT IN (SELECT note_id FROM project_notes WHERE project_id = ?)"
        )
        params.append(exclude_project)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY updated_at DESC"
    rows = db.execute(sql, params).fetchall()
    return [_row_to_note(db, r) for r in rows]


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    return _row_to_note(db, row)


@router.put("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, payload: NoteUpdate, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")

    if payload.title is not None:
        db.execute("UPDATE notes SET title = ? WHERE id = ?", (payload.title, note_id))
    if payload.body is not None:
        db.execute("UPDATE notes SET body = ? WHERE id = ?", (payload.body, note_id))
    if "task_ids" in payload.model_fields_set and payload.task_ids is not None:
        _set_note_task_links(db, note_id, list(payload.task_ids))
    elif "task_id" in payload.model_fields_set:
        _set_note_task_links(
            db,
            note_id,
            [payload.task_id] if payload.task_id is not None else [],
        )
    if payload.clip_ids is not None:
        for clip_id in payload.clip_ids:
            clip = db.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if not clip:
                raise HTTPException(status_code=400, detail=f"clip_id {clip_id} does not exist")
        _set_note_clips(db, note_id, payload.clip_ids)
    if "project_ids" in payload.model_fields_set and payload.project_ids is not None:
        _set_note_project_links(db, note_id, list(payload.project_ids))
    elif "project_id" in payload.model_fields_set:
        _set_note_project_links(
            db,
            note_id,
            [payload.project_id] if payload.project_id is not None else [],
        )
    db.execute("UPDATE notes SET updated_at = datetime('now') WHERE id = ?", (note_id,))
    db.commit()
    row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row_to_note(db, row)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.commit()


# --- Settings -------------------------------------------------------------

class SettingValue(BaseModel):
    value: str


@router.get("/settings/{key}", response_model=SettingValue)
def get_setting(key: str, db: Connection = Depends(get_db)):
    from maintenance import SETTING_DEFAULTS

    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        return SettingValue(value=row["value"])
    if key in SETTING_DEFAULTS:
        return SettingValue(value=SETTING_DEFAULTS[key])
    raise HTTPException(status_code=404, detail="Unknown setting")


@router.put("/settings/{key}", response_model=SettingValue)
def put_setting(key: str, payload: SettingValue, db: Connection = Depends(get_db)):
    value = payload.value
    if key == "ai_export_enabled":
        value = payload.value.strip().lower()
        if value not in {"true", "false"}:
            raise HTTPException(status_code=422, detail="AI向けエクスポートの設定値が不正です。")
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()
    if key == "ai_export_enabled" and value == "false":
        clear_exported_files()
    return SettingValue(value=value)


@router.get("/data/ai-export/status")
def ai_export_status():
    return get_ai_export_status()


@router.post("/data/ai-export")
def ai_export_now():
    try:
        return export_now()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI向けMarkdownの生成に失敗しました: {exc}") from exc


@router.post("/data/ai-export/open")
def open_ai_export_folder():
    try:
        return open_export_folder()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI向けエクスポートフォルダを開けませんでした: {exc}") from exc


# --- Database migration ---------------------------------------------------

_MAX_DB_IMPORT_BYTES = 512 * 1024 * 1024


def _remove_temp_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _validate_database_file(path: Path) -> None:
    try:
        with sqlite3.connect(str(path)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("データベースの整合性チェックに失敗しました")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
    except (sqlite3.DatabaseError, OSError) as exc:
        raise ValueError("有効なSQLiteデータベースではありません") from exc

    required = {"clips", "notes", "tasks", "settings"}
    if not required.issubset(tables):
        missing = ", ".join(sorted(required - tables))
        raise ValueError(f"AIリファレンス保存アプリのデータベースではありません（不足: {missing}）")


def _source_rows(conn: sqlite3.Connection, table: str):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if table not in tables:
        return []
    return conn.execute(f'SELECT * FROM "{table}"').fetchall()


def _source_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _source_value(row, columns: set[str], key: str, default=None):
    return row[key] if key in columns else default


def _source_id(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _migration_timestamp(value) -> str:
    return str(value) if value else datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _merge_database(source: sqlite3.Connection, dest: Connection) -> dict:
    """Append source data into the current DB while remapping every foreign key."""
    category_map = {}
    for row in _source_rows(source, "categories"):
        if row["name"] is None:
            continue
        dest.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (row["name"],))
        target = dest.execute(
            "SELECT id FROM categories WHERE name = ?", (row["name"],)
        ).fetchone()
        category_map[int(row["id"])] = int(target[0])

    tag_map = {}
    for row in _source_rows(source, "tags"):
        if row["name"] is None:
            continue
        dest.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (row["name"],))
        target = dest.execute("SELECT id FROM tags WHERE name = ?", (row["name"],)).fetchone()
        tag_map[int(row["id"])] = int(target[0])

    project_map = {}
    for row in _source_rows(source, "projects"):
        cur = dest.execute(
            "INSERT INTO projects(name, description, is_done, done_snapshot, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row["name"],
                row["description"],
                row["is_done"] or 0,
                row["done_snapshot"] if "done_snapshot" in row.keys() else None,
                _migration_timestamp(row["created_at"]),
            ),
        )
        project_map[int(row["id"])] = int(cur.lastrowid)

    clip_columns = _source_columns(source, "clips")
    clip_map = {}
    for row in _source_rows(source, "clips"):
        source_id = _source_id(row["id"])
        if source_id is None:
            continue
        project_id = project_map.get(
            _source_id(_source_value(row, clip_columns, "project_id"))
        )
        cur = dest.execute(
            "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, "
            "is_favorite, embedding, created_at, clip_type, file_ref, file_size, project_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["url"],
                row["title"],
                row["thumbnail_url"],
                row["comment"],
                category_map.get(_source_id(row["category_id"])),
                row["is_favorite"] or 0,
                row["embedding"],
                _migration_timestamp(row["created_at"]),
                _source_value(row, clip_columns, "clip_type", "url") or "url",
                _source_value(row, clip_columns, "file_ref"),
                _source_value(row, clip_columns, "file_size"),
                project_id,
            ),
        )
        clip_map[source_id] = int(cur.lastrowid)
        if project_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
                (project_id, int(cur.lastrowid)),
            )

    task_columns = _source_columns(source, "tasks")
    task_map = {}
    for row in _source_rows(source, "tasks"):
        source_id = _source_id(row["id"])
        if source_id is None:
            continue
        clip_id = clip_map.get(_source_id(row["clip_id"]))
        project_id = project_map.get(
            _source_id(_source_value(row, task_columns, "project_id"))
        )
        cur = dest.execute(
            "INSERT INTO tasks(title, is_done, clip_id, created_at, due_date, priority, "
            "completed_at, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["title"],
                row["is_done"] or 0,
                clip_id,
                _migration_timestamp(row["created_at"]),
                _source_value(row, task_columns, "due_date"),
                _source_value(row, task_columns, "priority"),
                _source_value(row, task_columns, "completed_at"),
                project_id,
            ),
        )
        task_map[source_id] = int(cur.lastrowid)

    note_columns = _source_columns(source, "notes")
    note_map = {}
    for row in _source_rows(source, "notes"):
        source_id = _source_id(row["id"])
        if source_id is None:
            continue
        task_id = task_map.get(_source_id(_source_value(row, note_columns, "task_id")))
        project_id = project_map.get(
            _source_id(_source_value(row, note_columns, "project_id"))
        )
        cur = dest.execute(
            "INSERT INTO notes(title, body, created_at, updated_at, task_id, project_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["title"],
                row["body"],
                _migration_timestamp(row["created_at"]),
                _migration_timestamp(row["updated_at"]),
                task_id,
                project_id,
            ),
        )
        note_map[source_id] = int(cur.lastrowid)
        if task_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO task_notes(task_id, note_id) VALUES (?, ?)",
                (task_id, int(cur.lastrowid)),
            )
        if project_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO project_notes(project_id, note_id) VALUES (?, ?)",
                (project_id, int(cur.lastrowid)),
            )

    for row in _source_rows(source, "clip_tags"):
        clip_id = clip_map.get(_source_id(row["clip_id"]))
        tag_id = tag_map.get(_source_id(row["tag_id"]))
        if clip_id is not None and tag_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id) VALUES (?, ?)",
                (clip_id, tag_id),
            )

    for row in _source_rows(source, "note_clips"):
        note_id = note_map.get(_source_id(row["note_id"]))
        clip_id = clip_map.get(_source_id(row["clip_id"]))
        if note_id is not None and clip_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO note_clips(note_id, clip_id) VALUES (?, ?)",
                (note_id, clip_id),
            )

    for row in _source_rows(source, "project_clips"):
        project_id = project_map.get(_source_id(row["project_id"]))
        clip_id = clip_map.get(_source_id(row["clip_id"]))
        if project_id is not None and clip_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO project_clips(project_id, clip_id) VALUES (?, ?)",
                (project_id, clip_id),
            )

    for row in _source_rows(source, "project_notes"):
        project_id = project_map.get(_source_id(row["project_id"]))
        note_id = note_map.get(_source_id(row["note_id"]))
        if project_id is not None and note_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO project_notes(project_id, note_id) VALUES (?, ?)",
                (project_id, note_id),
            )

    for row in _source_rows(source, "task_notes"):
        task_id = task_map.get(_source_id(row["task_id"]))
        note_id = note_map.get(_source_id(row["note_id"]))
        if task_id is not None and note_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO task_notes(task_id, note_id) VALUES (?, ?)",
                (task_id, note_id),
            )

    # Keep the current app's settings when keys collide; add only missing keys.
    for row in _source_rows(source, "settings"):
        dest.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (row["key"], row["value"]),
        )

    return {
        "categories": len(category_map),
        "tags": len(tag_map),
        "projects": len(project_map),
        "clips": len(clip_map),
        "tasks": len(task_map),
        "notes": len(note_map),
    }

@router.get("/data/export")
def export_database():
    """Create a consistent SQLite snapshot for data migration."""
    if not DB_PATH.is_file():
        init_db()

    fd, raw_path = tempfile.mkstemp(prefix="sparkle-export-", suffix=".db")
    os.close(fd)
    export_path = Path(raw_path)
    try:
        with sqlite3.connect(str(DB_PATH)) as source, sqlite3.connect(str(export_path)) as target:
            source.backup(target)
    except Exception:
        _remove_temp_file(str(export_path))
        raise HTTPException(status_code=500, detail="データベースのエクスポートに失敗しました")

    filename = f"Sparkle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    return FileResponse(
        str(export_path),
        media_type="application/x-sqlite3",
        filename=filename,
        background=BackgroundTask(_remove_temp_file, str(export_path)),
    )


@router.post("/data/import")
async def import_database(file: UploadFile = File(...)):
    """Validate an SQLite file and merge its data into the current database."""
    fd, raw_path = tempfile.mkstemp(prefix="sparkle-import-", suffix=".db")
    os.close(fd)
    import_path = Path(raw_path)
    try:
        total = 0
        with import_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_DB_IMPORT_BYTES:
                    raise HTTPException(status_code=413, detail="ファイルサイズが大きすぎます（上限512MB）")
                output.write(chunk)
        await file.close()

        try:
            _validate_database_file(import_path)
            init_db()
            with sqlite3.connect(str(import_path)) as source:
                source.row_factory = sqlite3.Row
                with get_connection() as dest:
                    dest.execute("BEGIN")
                    merged = _merge_database(source, dest)
                    dest.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (sqlite3.DatabaseError, OSError) as exc:
            raise HTTPException(status_code=400, detail="データの結合に失敗しました。ファイル形式を確認してください。") from exc

        return {
            "ok": True,
            "message": "既存データを残したまま、データベースの内容を結合しました。",
            "merged": merged,
        }
    finally:
        _remove_temp_file(str(import_path))

# --- ZIP backup migration --------------------------------------------------

_MAX_BACKUP_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
_MAX_BACKUP_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024


def _choose_backup_directory() -> Optional[Path]:
    """Open the native Windows folder picker for the local desktop app."""
    try:
        selected = _choose_directory_with_windows_dialog()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存先ダイアログを開けませんでした: {exc}") from exc
    return Path(selected) if selected else None


def _safe_backup_member_name(raw_name: str) -> str:
    name = raw_name.replace("\\", "/")
    if name.startswith("/"):
        raise ValueError("ZIP内のパスが不正です")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError("ZIP内のパスが不正です")
    return "/".join(parts)


def _inspect_backup_zip(archive: zipfile.ZipFile):
    db_info = None
    upload_infos = []
    total_size = 0
    for info in archive.infolist():
        name = _safe_backup_member_name(info.filename)
        total_size += info.file_size
        if total_size > _MAX_BACKUP_UNPACKED_BYTES:
            raise ValueError("ZIP展開後のサイズが大きすぎます")
        if info.file_size > _MAX_BACKUP_UNPACKED_BYTES:
            raise ValueError("ZIP内のファイルサイズが大きすぎます")
        # Do not allow symbolic links to escape the staging directory.
        if ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError("ZIP内に対応していないリンクがあります")
        if name == "clips.db" and not info.is_dir():
            db_info = info
        elif name == "uploads" or name.startswith("uploads/"):
            upload_infos.append((info, name))

    if db_info is None:
        raise ValueError("ZIP内にclips.dbがありません")
    return db_info, upload_infos


def _copy_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, name: str, root: Path) -> None:
    relative_parts = name.split("/")[1:]
    target = root.joinpath(*relative_parts)
    if info.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info, "r") as source, target.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


@router.post("/data/export-backup")
def export_backup_archive():
    """Create a ZIP containing clips.db and the complete uploads directory."""
    if not DB_PATH.is_file():
        init_db()
    selected_dir = _choose_backup_directory()
    if selected_dir is None:
        return {"ok": False, "cancelled": True}
    if not selected_dir.is_dir():
        raise HTTPException(status_code=400, detail="保存先フォルダが見つかりません")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = selected_dir / f"Sparkle-backup-{stamp}.zip"
    suffix = 2
    while archive_path.exists():
        archive_path = selected_dir / f"Sparkle-backup-{stamp}-{suffix}.zip"
        suffix += 1
    temp_archive = selected_dir / f".sparkle-backup-{uuid.uuid4().hex}.tmp"
    fd, raw_db_path = tempfile.mkstemp(prefix="sparkle-export-", suffix=".db")
    os.close(fd)
    snapshot_path = Path(raw_db_path)
    try:
        with sqlite3.connect(str(DB_PATH)) as source, sqlite3.connect(str(snapshot_path)) as target:
            source.backup(target)
        uploads_dir = get_uploads_dir()
        with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "clips.db")
            archive.writestr("uploads/", b"")
            for path in uploads_dir.rglob("*"):
                relative = path.relative_to(uploads_dir)
                member_name = str(PurePosixPath("uploads") / PurePosixPath(relative.as_posix()))
                if path.is_dir():
                    archive.writestr(member_name.rstrip("/") + "/", b"")
                elif path.is_file():
                    archive.write(path, member_name)
        os.replace(temp_archive, archive_path)
    except Exception as exc:
        _remove_temp_file(str(temp_archive))
        raise HTTPException(status_code=500, detail=f"バックアップの作成に失敗しました: {exc}") from exc
    finally:
        _remove_temp_file(str(snapshot_path))

    return {
        "ok": True,
        "filename": archive_path.name,
        "path": str(archive_path),
        "message": "clips.dbとuploadsをZIPに保存しました。",
    }


@router.post("/data/import-backup")
async def import_backup_archive(file: UploadFile = File(...)):
    """Import a ZIP backup, merging its DB and copying its uploads into app data."""
    fd, raw_zip_path = tempfile.mkstemp(prefix="sparkle-import-", suffix=".zip")
    os.close(fd)
    zip_path = Path(raw_zip_path)
    staging_dir = Path(tempfile.mkdtemp(prefix="sparkle-backup-"))
    snapshot_path = staging_dir / "clips.db"
    uploads_staging = staging_dir / "uploads"
    try:
        total = 0
        with zip_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_BACKUP_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="ZIPファイルが大きすぎます（上限2GB）")
                output.write(chunk)
        await file.close()

        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                db_info, upload_infos = _inspect_backup_zip(archive)
                if archive.testzip() is not None:
                    raise ValueError("ZIP内のファイルを読み込めません")
                with archive.open(db_info, "r") as source, snapshot_path.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                uploads_staging.mkdir(parents=True, exist_ok=True)
                for info, name in upload_infos:
                    _copy_zip_member(archive, info, name, uploads_staging)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=f"有効なSparkleバックアップZIPではありません: {exc}") from exc

        _validate_database_file(snapshot_path)
        init_db()
        with sqlite3.connect(str(snapshot_path)) as source:
            source.row_factory = sqlite3.Row
            with get_connection() as dest:
                dest.execute("BEGIN")
                merged = _merge_database(source, dest)
                dest.commit()

        app_uploads = get_uploads_dir()
        if uploads_staging.is_dir():
            shutil.copytree(uploads_staging, app_uploads, dirs_exist_ok=True)

        return {
            "ok": True,
            "message": "clips.dbを既存データに結合し、uploadsをアプリ内へ展開しました。",
            "merged": merged,
        }
    except HTTPException:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"バックアップのインポートに失敗しました: {exc}") from exc
    finally:
        await file.close()
        _remove_temp_file(str(zip_path))
        shutil.rmtree(staging_dir, ignore_errors=True)
# --- Maintenance ----------------------------------------------------------


@router.post("/maintenance/cleanup")
def trigger_cleanup():
    return run_maintenance()


# --- Uploads -------------------------------------------------------------

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
}

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w.+/-]+);base64,(?P<data>.+)$", re.DOTALL)


class ThumbnailUploadIn(BaseModel):
    data_url: str


class ThumbnailUploadOut(BaseModel):
    url: str


@router.post("/uploads/thumbnail", response_model=ThumbnailUploadOut)
def upload_thumbnail(payload: ThumbnailUploadIn, request: Request):
    match = _DATA_URL_RE.match(payload.data_url.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Invalid data URL format")

    mime = match.group("mime").lower()
    ext = _MIME_EXT.get(mime)
    if ext is None:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {mime}")

    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 data")

    if not raw:
        raise HTTPException(status_code=400, detail="Empty image data")

    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (THUMBNAILS_DIR / filename).write_bytes(raw)

    base_url = str(request.base_url).rstrip("/")
    return ThumbnailUploadOut(url=f"{base_url}/uploads/thumbnails/{filename}")


# --- Local files -----------------------------------------------------------

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
VIDEO_EXTS = {".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".h", ".rs", ".go", ".rb", ".php", ".sh", ".bat", ".sql"}


def _generate_image_thumbnail(data: bytes, ext: str) -> Optional[str]:
    """Generate a thumbnail from image bytes. Returns data URL or None."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((400, 400))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def _generate_video_thumbnail(file_path: Path) -> Optional[str]:
    """Extract a frame from a video using ffmpeg. Returns data URL or None."""
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path is None:
        return None
    try:
        result = subprocess.run(
            [ffmpeg_path, "-i", str(file_path), "-ss", "00:00:01", "-vframes", "1",
             "-f", "image2", "-"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        b64 = base64.b64encode(result.stdout).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


LOCAL_DIR = get_local_files_dir()


@router.post("/clips/local", response_model=ClipOut, status_code=201)
async def upload_local_clip(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    tags: str = Form(""),
    db: Connection = Depends(get_db),
):
    """Upload a local file as a clip (copy mode). File is stored in app folder."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    category_id = _resolve_category(db, category)
    tag_ids = _resolve_tags(db, tag_list)

    original_name = file.filename or "unnamed"
    clip_title = title or original_name
    ext_lower = Path(original_name).suffix.lower()

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(original_name).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = LOCAL_DIR / stored_name
    content = await file.read()
    dest.write_bytes(content)
    url = f"local://copy/{stored_name}"

    thumbnail_url = None
    if ext_lower in IMAGE_EXTS:
        thumbnail_url = _generate_image_thumbnail(content, ext_lower)
    elif ext_lower in VIDEO_EXTS:
        thumbnail_url = _generate_video_thumbnail(dest)

    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, file_size) "
        "VALUES (?, ?, ?, ?, ?, 'local', 'copy', ?)",
        (url, clip_title, thumbnail_url, comment, category_id, len(content)),
    )
    clip_id = cur.lastrowid
    _set_tags(db, clip_id, tag_ids)
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


class ReferenceClipIn(BaseModel):
    file_path: str
    title: Optional[str] = None
    comment: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = ""


@router.post("/clips/local/reference", response_model=ClipOut, status_code=201)
def create_reference_clip(
    payload: ReferenceClipIn,
    db: Connection = Depends(get_db),
):
    """Create a clip that references the original file path without copying."""
    tag_list = [t.strip() for t in (payload.tags or "").split(",") if t.strip()]
    category_id = _resolve_category(db, payload.category)
    tag_ids = _resolve_tags(db, tag_list)

    file_path = Path(payload.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="File not found at the specified path")

    original_name = file_path.name
    clip_title = payload.title or original_name
    ext_lower = file_path.suffix.lower()

    url = f"local://reference/{file_path}"

    thumbnail_url = None
    if ext_lower in IMAGE_EXTS:
        try:
            content = file_path.read_bytes()
            thumbnail_url = _generate_image_thumbnail(content, ext_lower)
        except Exception:
            pass
    elif ext_lower in VIDEO_EXTS:
        thumbnail_url = _generate_video_thumbnail(file_path)

    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = None

    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, file_size) "
        "VALUES (?, ?, ?, ?, ?, 'local', 'reference', ?)",
        (url, clip_title, thumbnail_url, payload.comment, category_id, file_size),
    )
    clip_id = cur.lastrowid
    _set_tags(db, clip_id, tag_ids)
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


class OpenFileEntry(BaseModel):
    path: str
    size: int


class OpenFilesOut(BaseModel):
    files: List[OpenFileEntry]


class LocalFilePathOut(BaseModel):
    path: str


@router.post("/dialog/open-files", response_model=OpenFilesOut)
def open_file_dialog():
    """サーバー(このアプリを動かしているPC)上でネイティブのファイル選択ダイアログを開き、
    選択されたファイルの絶対パスとサイズを返す。
    ブラウザ側のFile System Access APIでは絶対パスを取得できないため、
    reference(元ファイル参照)モードではこちらを使う。
    Windows標準のファイル選択ダイアログを使うため、exe内のTkには依存しない。
    """
    try:
        raw_paths = _choose_files_with_windows_dialog()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ダイアログを開けませんでした: {e}") from e

    files = []
    for p in raw_paths:
        try:
            size = Path(p).stat().st_size
        except OSError:
            size = 0
        files.append(OpenFileEntry(path=p, size=size))
    return OpenFilesOut(files=files)


@router.get("/clips/{clip_id}/path", response_model=LocalFilePathOut)
def get_local_file_path(clip_id: int, db: Connection = Depends(get_db)):
    """Return the absolute path for a local clip so the UI can copy it."""
    row = db.execute(
        "SELECT url, clip_type FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    if row["clip_type"] != "local":
        raise HTTPException(status_code=400, detail="Not a local clip")

    url = row["url"] or ""
    if not url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Invalid local URL")

    if "/reference/" in url:
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        name = url.rsplit("/", 1)[-1]
        if not name:
            raise HTTPException(status_code=400, detail="Invalid file path")
        file_path = LOCAL_DIR / name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return LocalFilePathOut(path=str(file_path))


@router.get("/clips/{clip_id}/file")
def get_local_file(clip_id: int, db: Connection = Depends(get_db)):
    """Serve a local clip's file. Returns FileResponse for local clips."""
    row = db.execute(
        "SELECT url, clip_type FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    if row["clip_type"] != "local":
        raise HTTPException(status_code=400, detail="Not a local clip")

    url = row["url"] or ""
    if not url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Invalid local URL")

    # Extract file path based on mode
    if "/reference/" in url:
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        name = url.rsplit("/", 1)[-1]
        if not name:
            raise HTTPException(status_code=400, detail="Invalid file path")
        file_path = LOCAL_DIR / name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(str(file_path), filename=file_path.name)


@router.post("/clips/{clip_id}/open")
def open_local_file(clip_id: int, db: Connection = Depends(get_db)):
    """Open a local clip's file with the OS default application."""
    row = db.execute(
        "SELECT url, clip_type FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    if row["clip_type"] != "local":
        raise HTTPException(status_code=400, detail="Not a local clip")

    url = row["url"] or ""
    if not url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Invalid local URL")

    # Extract file path based on mode
    if "/reference/" in url:
        # Reference mode: local://reference/{full/path/to/file}
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        # Copy mode: local://copy/{stored_name}
        name = url.rsplit("/", 1)[-1]
        file_path = LOCAL_DIR / name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    try:
        if os.name == "nt":
            os.startfile(str(file_path))
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", str(file_path)])
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot open file: {e}")


@router.post("/clips/{clip_id}/explorer")
def reveal_in_explorer(clip_id: int, db: Connection = Depends(get_db)):
    """Reveal a local clip's file in the system file manager (Explorer/Finder)."""
    row = db.execute(
        "SELECT url, clip_type FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    if row["clip_type"] != "local":
        raise HTTPException(status_code=400, detail="Not a local clip")

    url = row["url"] or ""
    if not url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Invalid local URL")

    if "/reference/" in url:
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        name = url.rsplit("/", 1)[-1]
        file_path = LOCAL_DIR / name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(file_path)])
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", str(file_path.parent)])
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot open explorer: {e}")


class TextPreviewOut(BaseModel):
    preview: str


@router.get("/clips/{clip_id}/text-preview", response_model=TextPreviewOut)
def get_text_preview(clip_id: int, db: Connection = Depends(get_db)):
    """Return the first ~300 chars of a text-based local clip."""
    row = db.execute(
        "SELECT url, clip_type FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    if row["clip_type"] != "local":
        raise HTTPException(status_code=400, detail="Not a local clip")

    url = row["url"] or ""
    if not url.startswith("local://"):
        raise HTTPException(status_code=400, detail="Invalid local URL")

    # Extract file path based on mode
    if "/reference/" in url:
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        name = url.rsplit("/", 1)[-1]
        file_path = LOCAL_DIR / name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    ext = file_path.suffix.lower()
    if ext not in TEXT_EXTS:
        raise HTTPException(status_code=400, detail="Not a text file")

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")[:300]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}")

    return TextPreviewOut(preview=text)
