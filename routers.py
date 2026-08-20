"""API routers for clips, categories and tags."""

import base64
import binascii
import ctypes
import html
import hashlib
import ipaddress
import io
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from sqlite3 import Connection

from crud import get_or_create_category, get_or_create_tag
from command_palette import (
    CommandPaletteSearchOut,
    CommandPaletteSearchRequest,
    CommandPaletteStatusOut,
    get_command_palette_status,
    search_command_palette,
)
from db import DB_PATH, get_connection, init_db
from ai_export import (
    clear_exported_files,
    export_now,
    get_status as get_ai_export_status,
    open_export_folder,
)
from paths import get_app_data_dir, get_local_files_dir, get_profile_dir, get_uploads_dir
from ffmpeg_bootstrap import get_ffmpeg_path
from maintenance import (
    THUMBNAILS_DIR,
    cleanup_orphan_tags,
    delete_thumbnail_file,
    run_maintenance,
)
from project_assistant import (
    AIProviderUpdate,
    AIProvidersOut,
    AISettingsUpdate,
    ProjectAssistantError,
    ProjectAssistantOut,
    ProjectAssistantRequest,
    ask_project_assistant,
    configure_ai_provider,
    delete_ai_provider,
    get_ai_provider_settings,
    set_active_ai_provider,
)
from schemas import (
    BackupExportPayload,
    CategoryCreate,
    CategoryOut,
    ClipboardImage,
    ClipCreate,
    ClipOut,
    ClipUpdate,
    LightClipOut,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    ProfileIconUpdate,
    ProfileNameUpdate,
    ProfileOut,
    ProfilePickAdd,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TagCreate,
    TagOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    UrlMetadataOut,
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


def _choose_directory_with_windows_dialog(
    title: str = "バックアップの保存先を選択",
    ok_label: str = "このフォルダーを選択",
) -> Optional[str]:
    base_script = r"""
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
    public static string Pick(string title, string okLabel)
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
            dialog.SetTitle(title);
            dialog.SetOkButtonLabel(okLabel);
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
$selected = [SparkleFolderPicker]::Pick("__TITLE__", "__OK_LABEL__")
if ($selected) { [Console]::Write($selected) }
"""
    script = base_script.replace("__TITLE__", title.replace("\\", "\\\\").replace('"', '\\"'))
    script = script.replace("__OK_LABEL__", ok_label.replace("\\", "\\\\").replace('"', '\\"'))
    paths = _run_windows_forms_dialog(script)
    return paths[0] if paths else None


def _set_windows_clipboard_dib(png_bytes: bytes) -> None:
    """Write PNG data to the Windows clipboard as CF_DIB. Works without window focus."""
    from ctypes import wintypes
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    bmp_io = io.BytesIO()
    img.save(bmp_io, "BMP")
    dib = bmp_io.getvalue()[14:]  # strip the BMP file header; CF_DIB expects a DIB

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []

    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8

    if not user32.OpenClipboard(None):
        raise RuntimeError("クリップボードが他のアプリに使用されています")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            raise RuntimeError("クリップボードのメモリ確保に失敗しました")
        ptr = kernel32.GlobalLock(handle)
        try:
            ctypes.memmove(ptr, dib, len(dib))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("クリップボードへの書き込みに失敗しました")
    finally:
        user32.CloseClipboard()


router = APIRouter()


def get_db() -> Connection:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/command-palette/status", response_model=CommandPaletteStatusOut)
def command_palette_status():
    return get_command_palette_status()


@router.post("/command-palette/search", response_model=CommandPaletteSearchOut)
def command_palette_search(
    payload: CommandPaletteSearchRequest,
    db: Connection = Depends(get_db),
):
    return search_command_palette(db, payload)


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
        is_folder=bool(row["is_folder"]) if "is_folder" in row.keys() else False,
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
    cleanup_orphan_tags(conn)


def _resolve_tags(conn: Connection, names: List[str]) -> List[int]:
    return [get_or_create_tag(conn, name) for name in names]


def _resolve_category(conn: Connection, name: Optional[str]) -> Optional[int]:
    if name is None:
        return None
    return get_or_create_category(conn, name)


# --- Categories ---------------------------------------------------------


@router.post("/clipboard/image", include_in_schema=False)
def copy_image_to_clipboard(payload: ClipboardImage):
    raw = payload.data_url
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        png = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64 image")
    if len(png) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="image too large")
    try:
        _set_windows_clipboard_dib(png)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


PROXY_CACHE_DIR = THUMBNAILS_DIR / "proxy"


@router.get("/thumbnail-proxy", include_in_schema=False)
def thumbnail_proxy(url: str = Query(...)):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="unsupported url scheme")
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached_img = PROXY_CACHE_DIR / f"{key}.img"
    cached_mime = PROXY_CACHE_DIR / f"{key}.mime"
    if cached_img.is_file():
        content_type = (
            cached_mime.read_text().strip() if cached_mime.is_file() else "image/png"
        )
        return Response(
            content=cached_img.read_bytes(),
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=604800"},
        )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read(4 * 1024 * 1024)
            content_type = resp.headers.get("Content-Type", "image/png")
    except Exception:
        raise HTTPException(status_code=502, detail="failed to fetch image")
    try:
        PROXY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached_img.write_bytes(data)
        cached_mime.write_text(content_type or "image/png")
    except OSError:
        pass
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=604800"},
    )


METADATA_MAX_BYTES = 512 * 1024
METADATA_TIMEOUT_SECONDS = 8
METADATA_MAX_REDIRECTS = 3
METADATA_USER_AGENT = "Mozilla/5.0 Sparkle/metadata"
X_HOSTS = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)
X_STATUS_PATH_RE = re.compile(r"(?:^|/)status/(\d+)(?:/|$)", re.IGNORECASE)
X_OEMBED_ENDPOINT = "https://publish.twitter.com/oembed"
X_TITLE_BODY_MAX_CHARS = 240
YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
    }
)
YOUTUBE_OEMBED_ENDPOINT = "https://www.youtube.com/oembed"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


METADATA_OPENER = urllib.request.build_opener(_NoRedirectHandler())


class _PageMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.document_title_parts: List[str] = []
        self.meta_titles: dict[str, str] = {}
        self.meta_images: dict[str, str] = {}
        self._title_depth = 0

    def handle_starttag(self, tag: str, attrs):
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._title_depth += 1
            return
        if normalized_tag != "meta":
            return
        values = {
            key.lower(): html.unescape(value or "")
            for key, value in attrs
            if key
        }
        key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
        if not key or not values.get("content"):
            return
        if key in {"og:title", "twitter:title", "title"}:
            self.meta_titles.setdefault(key, values["content"])
        if key in {
            "og:image",
            "og:image:url",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
            "image",
        }:
            self.meta_images.setdefault(key, values["content"])

    def handle_endtag(self, tag: str):
        if tag.lower() == "title" and self._title_depth > 0:
            self._title_depth -= 1

    def handle_data(self, data: str):
        if self._title_depth > 0:
            self.document_title_parts.append(data)


def _clean_metadata_title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return cleaned[:500] or None


class _OEmbedTextParser(HTMLParser):
    """Extract the post paragraph from the public X embed response."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._paragraph_depth = 0

    def handle_starttag(self, tag: str, attrs):
        normalized_tag = tag.lower()
        if normalized_tag == "p" and self._paragraph_depth == 0:
            self._paragraph_depth = 1
        elif normalized_tag == "br" and self._paragraph_depth > 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag.lower() == "p" and self._paragraph_depth > 0:
            self._paragraph_depth = 0

    def handle_data(self, data: str):
        if self._paragraph_depth > 0:
            self.parts.append(data)


def _is_x_status_url(raw_url: str) -> bool:
    parsed = urllib.parse.urlsplit(raw_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    return host in X_HOSTS and X_STATUS_PATH_RE.search(parsed.path or "") is not None


def _youtube_video_id(raw_url: str) -> Optional[str]:
    parsed = urllib.parse.urlsplit(raw_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in YOUTUBE_HOSTS:
        return None

    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    candidate = None
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path_parts[0] if path_parts else None
    elif path_parts and path_parts[0].lower() == "watch":
        candidate = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
    else:
        for marker in ("shorts", "embed", "live", "v"):
            if marker in [part.lower() for part in path_parts]:
                marker_index = [part.lower() for part in path_parts].index(marker)
                if marker_index + 1 < len(path_parts):
                    candidate = path_parts[marker_index + 1]
                    break
    if not candidate or re.fullmatch(r"[A-Za-z0-9_-]{6,64}", candidate) is None:
        return None
    return candidate


def _youtube_thumbnail_url(raw_url: str) -> Optional[str]:
    video_id = _youtube_video_id(raw_url)
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _normalize_x_title(value: Optional[str]) -> Optional[str]:
    cleaned = _clean_metadata_title(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"\s*(?:/|\||-)\s*X\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned.startswith("Xユーザーの") and "さん" in cleaned and "「" in cleaned:
        return cleaned
    return None


def _truncate_x_body(value: str) -> str:
    if len(value) <= X_TITLE_BODY_MAX_CHARS:
        return value
    return value[: X_TITLE_BODY_MAX_CHARS - 1].rstrip() + "…"


def _format_x_title(author_name: Optional[str], post_text: Optional[str]) -> Optional[str]:
    author = _clean_metadata_title(author_name)
    body = _clean_metadata_title(post_text)
    if not author or not body:
        return None
    author = author.lstrip("@")
    if not author:
        return None
    return f"Xユーザーの{author}さん: 「{_truncate_x_body(body)}」"


def _extract_oembed_post_text(fragment: Optional[str]) -> Optional[str]:
    if not fragment:
        return None
    parser = _OEmbedTextParser()
    try:
        parser.feed(fragment)
        parser.close()
    except (TypeError, ValueError):
        return None
    return _clean_metadata_title("".join(parser.parts))


def _extract_x_page_title(page: str) -> Optional[str]:
    parser = _PageMetadataParser()
    try:
        parser.feed(page)
        parser.close()
    except (TypeError, ValueError):
        return None

    # X's document title is the same browser-visible value that the Chrome
    # extension reads. Prefer it over generic og:title values such as
    # "Post by ... on X" and remove only the site suffix.
    candidates = [
        _clean_metadata_title("".join(parser.document_title_parts)),
        _clean_metadata_title(parser.meta_titles.get("og:title")),
        _clean_metadata_title(parser.meta_titles.get("twitter:title")),
        _clean_metadata_title(parser.meta_titles.get("title")),
    ]
    for candidate in candidates:
        normalized = _normalize_x_title(candidate)
        if normalized:
            return normalized
    return None


def _fetch_x_oembed_title(url: str) -> Optional[str]:
    endpoint = f"{X_OEMBED_ENDPOINT}?{urllib.parse.urlencode({'url': url, 'omit_script': '1'})}"
    try:
        response = _fetch_metadata_page(endpoint)
        if response is None:
            return None
        payload = json.loads(response[0])
        if not isinstance(payload, dict):
            return None
        return _format_x_title(
            payload.get("author_name"),
            _extract_oembed_post_text(payload.get("html")),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _fetch_youtube_oembed_title(url: str) -> Optional[str]:
    endpoint = f"{YOUTUBE_OEMBED_ENDPOINT}?{urllib.parse.urlencode({'url': url, 'format': 'json'})}"
    try:
        response = _fetch_metadata_page(endpoint)
        if response is None:
            return None
        payload = json.loads(response[0])
        if not isinstance(payload, dict):
            return None
        return _clean_metadata_title(payload.get("title"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _validate_metadata_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported url scheme")
    if parsed.username or parsed.password:
        raise ValueError("userinfo is not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise ValueError("invalid port") from error

    host = parsed.hostname
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            addresses = {
                str(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
                for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as error:
            raise ValueError("host could not be resolved") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("private or non-global host is not allowed")
    return parsed._replace(fragment="").geturl()


def _fetch_metadata_page(url: str) -> Optional[tuple[str, str]]:
    current_url = url
    for _ in range(METADATA_MAX_REDIRECTS + 1):
        current_url = _validate_metadata_url(current_url)
        request = urllib.request.Request(
            current_url,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "User-Agent": METADATA_USER_AGENT,
            },
        )
        try:
            with METADATA_OPENER.open(request, timeout=METADATA_TIMEOUT_SECONDS) as response:
                status = response.getcode()
                if 300 <= status < 400:
                    location = response.headers.get("Location")
                    if not location:
                        return None
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                if status < 200 or status >= 300:
                    return None
                raw = response.read(METADATA_MAX_BYTES + 1)
                if len(raw) > METADATA_MAX_BYTES:
                    raw = raw[:METADATA_MAX_BYTES]
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    page = raw.decode(charset, errors="replace")
                except LookupError:
                    page = raw.decode("utf-8", errors="replace")
                return page, response.geturl() or current_url
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                location = error.headers.get("Location")
                if not location:
                    return None
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            return None
        except (OSError, ValueError):
            return None
    return None


def _extract_page_title(page: str) -> Optional[str]:
    parser = _PageMetadataParser()
    try:
        parser.feed(page)
        parser.close()
    except (TypeError, ValueError):
        return None
    for key in ("og:title", "twitter:title", "title"):
        title = _clean_metadata_title(parser.meta_titles.get(key))
        if title:
            return title
    return _clean_metadata_title("".join(parser.document_title_parts))


def _extract_page_image(page: str) -> Optional[str]:
    parser = _PageMetadataParser()
    try:
        parser.feed(page)
        parser.close()
    except (TypeError, ValueError):
        return None
    for key in (
        "og:image:secure_url",
        "og:image",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
        "image",
    ):
        image = parser.meta_images.get(key)
        if image:
            return image.strip()
    return None


def _resolve_metadata_image(raw_image: Optional[str], base_url: str) -> Optional[str]:
    if not raw_image:
        return None
    candidate = urllib.parse.urljoin(base_url, html.unescape(raw_image.strip()))
    try:
        return _validate_metadata_url(candidate)
    except ValueError:
        return None


def _collect_url_metadata(validated_url: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    is_x_status = _is_x_status_url(validated_url)
    youtube_thumbnail = _youtube_thumbnail_url(validated_url)
    page = _fetch_metadata_page(validated_url)
    if page is None:
        title = None
        if is_x_status:
            title = _fetch_x_oembed_title(validated_url)
        elif _youtube_video_id(validated_url):
            title = _fetch_youtube_oembed_title(validated_url)
        if title or youtube_thumbnail:
            return validated_url, title, youtube_thumbnail
        return None

    page_html, final_url = page
    if is_x_status or _is_x_status_url(final_url):
        title = _extract_x_page_title(page_html) or _fetch_x_oembed_title(final_url)
        if title is None:
            title = _extract_page_title(page_html)
    else:
        title = _extract_page_title(page_html)
        if title is None and _youtube_video_id(final_url):
            title = _fetch_youtube_oembed_title(final_url)
    thumbnail = _resolve_metadata_image(_extract_page_image(page_html), final_url)
    if thumbnail is None:
        thumbnail = _youtube_thumbnail_url(final_url) or youtube_thumbnail
    return final_url, title, thumbnail


def _enrich_url_clip_metadata(
    url: str,
    title: Optional[str],
    thumbnail_url: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    resolved_title = title.strip() if isinstance(title, str) and title.strip() else None
    resolved_thumbnail = (
        thumbnail_url.strip()
        if isinstance(thumbnail_url, str) and thumbnail_url.strip()
        else None
    )
    if resolved_title and resolved_thumbnail:
        return resolved_title, resolved_thumbnail
    try:
        validated_url = _validate_metadata_url(url)
        metadata = _collect_url_metadata(validated_url)
    except (OSError, TypeError, ValueError):
        return resolved_title, resolved_thumbnail
    if metadata is None:
        return resolved_title, resolved_thumbnail
    _, fetched_title, fetched_thumbnail = metadata
    return resolved_title or fetched_title, resolved_thumbnail or fetched_thumbnail


@router.get("/url-metadata", response_model=UrlMetadataOut)
def get_url_metadata(url: str = Query(..., min_length=1, max_length=4096)):
    try:
        validated_url = _validate_metadata_url(url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    metadata = _collect_url_metadata(validated_url)
    if metadata is None:
        raise HTTPException(status_code=502, detail="failed to fetch page metadata")
    final_url, title, thumbnail_url = metadata
    return UrlMetadataOut(url=final_url, title=title, thumbnail_url=thumbnail_url)


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


@router.post("/projects/{project_id}/assistant", response_model=ProjectAssistantOut)
def project_assistant(
    project_id: int,
    payload: ProjectAssistantRequest,
    db: Connection = Depends(get_db),
):
    """Ask the configured provider about this project's attached data only."""
    try:
        return ask_project_assistant(db, project_id, payload)
    except ProjectAssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _cascade_project_done(db: Connection, project_id: int, row) -> None:
    """Mark the project done and cascade completion to its undone tasks and notes."""
    undone_tasks = db.execute(
        "SELECT id FROM tasks WHERE project_id = ? AND is_done = 0", (project_id,)
    ).fetchall()
    task_snapshot = [t["id"] for t in undone_tasks]
    undone_notes = db.execute(
        "SELECT note_id FROM project_notes WHERE project_id = ? "
        "AND note_id IN (SELECT id FROM notes WHERE is_done = 0)",
        (project_id,),
    ).fetchall()
    note_snapshot = [n["note_id"] for n in undone_notes]
    db.execute(
        "UPDATE projects SET is_done = 1, done_snapshot = ?, notes_done_snapshot = ? WHERE id = ?",
        (json.dumps(task_snapshot) if task_snapshot else "[]",
         json.dumps(note_snapshot) if note_snapshot else "[]",
         project_id),
    )
    if task_snapshot:
        db.execute(
            "UPDATE tasks SET is_done = 1, completed_at = datetime('now') WHERE id IN ({})".format(
                ",".join("?" for _ in task_snapshot)
            ),
            task_snapshot,
        )
    if note_snapshot:
        db.execute(
            "UPDATE notes SET is_done = 1, completed_at = datetime('now') WHERE id IN ({})".format(
                ",".join("?" for _ in note_snapshot)
            ),
            note_snapshot,
        )


def _restore_project_done(db: Connection, project_id: int, row) -> None:
    """Revert project done state, restoring only the tasks and notes it cascaded."""
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
    notes_snapshot = row["notes_done_snapshot"]
    if notes_snapshot:
        note_ids = json.loads(notes_snapshot)
        if note_ids:
            db.execute(
                "UPDATE notes SET is_done = 0, completed_at = NULL WHERE id IN ({}) AND is_done = 1".format(
                    ",".join("?" for _ in note_ids)
                ),
                note_ids,
            )
    db.execute("UPDATE projects SET is_done = 0, done_snapshot = NULL, notes_done_snapshot = NULL WHERE id = ?", (project_id,))


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Connection = Depends(get_db)):
    row = db.execute("SELECT id, is_done, done_snapshot, notes_done_snapshot FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.name is not None:
        db.execute("UPDATE projects SET name = ? WHERE id = ?", (payload.name, project_id))
    if payload.description is not None:
        db.execute("UPDATE projects SET description = ? WHERE id = ?", (payload.description, project_id))
    if payload.is_done is not None and payload.is_done != bool(row["is_done"]):
        if payload.is_done:
            _cascade_project_done(db, project_id, row)
        else:
            _restore_project_done(db, project_id, row)
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
        _restore_project_done(db, project_id, row)
    else:
        _cascade_project_done(db, project_id, row)
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
    title = payload.title
    thumbnail_url = payload.thumbnail_url
    if (payload.clip_type or "url") != "local":
        title, thumbnail_url = _enrich_url_clip_metadata(
            payload.url,
            title,
            thumbnail_url,
        )
    category_id = _resolve_category(db, payload.category)
    tag_ids = _resolve_tags(db, payload.tags)

    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, project_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            payload.url,
            title,
            thumbnail_url,
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
    _increment_total_saved(db)
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


@router.get("/clips", response_model=List[ClipOut])
def list_clips(
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    url: Optional[str] = Query(None),
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
    if url is not None:
        conditions.append("url = ?")
        params.append(url)
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
    cleanup_orphan_tags(db)
    db.commit()
    delete_thumbnail_file(thumbnail_url)
    # Only delete the file from disk for copy mode (we own the file).
    # Reference mode stores the original path — never delete that.
    if file_ref == "copy" and clip_url and clip_url.startswith("local://"):
        local_file = LOCAL_DIR / clip_url.split("/")[-1]
        if local_file.is_dir():
            shutil.rmtree(local_file, ignore_errors=True)
        elif local_file.is_file():
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


def _row_to_note(db: Connection, row) -> NoteOut:
    project_ids = _fetch_project_ids(db, "project_notes", "note_id", row["id"]) or (
        [row["project_id"]] if row["project_id"] is not None else []
    )
    return NoteOut(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        is_done=bool(row["is_done"]) if "is_done" in row.keys() else False,
        completed_at=row["completed_at"] if "completed_at" in row.keys() else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        clips=_fetch_note_clips(db, row["id"]),
        project_id=project_ids[0] if project_ids else None,
        project_ids=project_ids,
    )


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
    project_ids = list(payload.project_ids) if payload.project_ids else (
        [payload.project_id] if payload.project_id is not None else []
    )
    for project_id in project_ids:
        project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=400, detail=f"project_id {project_id} does not exist")
    for clip_id in payload.clip_ids:
        clip = db.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip:
            raise HTTPException(status_code=400, detail=f"clip_id {clip_id} does not exist")
    cur = db.execute(
        "INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)",
        (
            payload.title,
            payload.body,
            project_ids[0] if project_ids else None,
        ),
    )
    note_id = cur.lastrowid
    _set_note_clips(db, note_id, payload.clip_ids)
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
    row = db.execute("SELECT id, updated_at FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    if payload.expected_updated_at is not None and payload.expected_updated_at != row["updated_at"]:
        raise HTTPException(status_code=409, detail="Note was updated elsewhere")

    if payload.title is not None:
        db.execute("UPDATE notes SET title = ? WHERE id = ?", (payload.title, note_id))
    if payload.body is not None:
        db.execute("UPDATE notes SET body = ? WHERE id = ?", (payload.body, note_id))
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
    db.execute(
        "UPDATE notes SET updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
        (note_id,),
    )
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


@router.get("/ai/providers", response_model=AIProvidersOut)
def list_ai_providers(db: Connection = Depends(get_db)):
    """Return provider availability without exposing API keys."""
    return get_ai_provider_settings(db)


@router.put("/ai/providers/{provider_id}", response_model=AIProvidersOut)
def update_ai_provider(
    provider_id: str,
    payload: AIProviderUpdate,
    db: Connection = Depends(get_db),
):
    try:
        return configure_ai_provider(db, provider_id, payload)
    except ProjectAssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.delete("/ai/providers/{provider_id}", response_model=AIProvidersOut)
def remove_ai_provider(provider_id: str, db: Connection = Depends(get_db)):
    try:
        return delete_ai_provider(db, provider_id)
    except ProjectAssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put("/ai/settings", response_model=AIProvidersOut)
def update_ai_settings(
    payload: AISettingsUpdate,
    db: Connection = Depends(get_db),
):
    try:
        return set_active_ai_provider(db, payload.active_provider)
    except ProjectAssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class SettingValue(BaseModel):
    value: str


@router.get("/settings/{key}", response_model=SettingValue)
def get_setting(key: str, db: Connection = Depends(get_db)):
    from maintenance import SETTING_DEFAULTS

    if key == "auto_create_note_on_task":
        raise HTTPException(status_code=404, detail="Unknown setting")
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        return SettingValue(value=row["value"])
    if key in SETTING_DEFAULTS:
        return SettingValue(value=SETTING_DEFAULTS[key])
    raise HTTPException(status_code=404, detail="Unknown setting")


@router.put("/settings/{key}", response_model=SettingValue)
def put_setting(key: str, payload: SettingValue, db: Connection = Depends(get_db)):
    if key == "auto_create_note_on_task":
        raise HTTPException(status_code=404, detail="Unknown setting")
    value = payload.value
    if key == "auto_create_note_on_project":
        value = payload.value.strip().lower()
        if value not in {"true", "false"}:
            raise HTTPException(status_code=422, detail="自動メモ作成の設定値が不正です。")
    elif key == "task_auto_delete":
        value = payload.value.strip().lower()
        if value not in {"3d", "1w", "1m", "never"}:
            raise HTTPException(status_code=422, detail="タスク自動削除の設定値が不正です。")
    elif key == "ai_export_enabled":
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
        # Editing depends on the export toggle, so turning the export off also
        # forces the edit setting off.
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("ai_edit_enabled", "false"),
        )
        db.commit()
    return SettingValue(value=value)


# --- Profile --------------------------------------------------------------

PROFILE_ICON_FILENAME = "icon.png"
PROFILE_USERNAME_DEFAULT = "ユーザー"
PROFILE_PICKS_LIMIT = 3
STATS_TOTAL_SAVED_KEY = "stats_total_saved"
PROFILE_FIRST_USED_KEY = "profile_first_used_at"


def _increment_total_saved(db: Connection) -> None:
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", (STATS_TOTAL_SAVED_KEY,)
    ).fetchone()
    current = int(row["value"]) if row and row["value"].isdigit() else 0
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (STATS_TOTAL_SAVED_KEY, str(current + 1)),
    )


def _get_profile_username(db: Connection) -> str:
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", ("profile_username",)
    ).fetchone()
    name = row["value"].strip() if row and row["value"] else ""
    return name or PROFILE_USERNAME_DEFAULT


def _get_profile_icon_url(request: Request) -> Optional[str]:
    icon_file = get_profile_dir() / PROFILE_ICON_FILENAME
    if not icon_file.is_file():
        return None
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/uploads/profile/{PROFILE_ICON_FILENAME}"


def _ensure_profile_first_used(db: Connection) -> str:
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", (PROFILE_FIRST_USED_KEY,)
    ).fetchone()
    if row and row["value"]:
        return row["value"]

    earliest: Optional[str] = None
    for table in ("clips", "tasks", "notes", "projects"):
        result = db.execute(f"SELECT MIN(created_at) AS m FROM {table}").fetchone()
        if result and result["m"]:
            if earliest is None or result["m"] < earliest:
                earliest = result["m"]
    setup_marker = get_app_data_dir() / ".initial-setup-complete.json"
    if setup_marker.is_file():
        marker_time = datetime.fromtimestamp(setup_marker.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        if earliest is None or marker_time < earliest:
            earliest = marker_time
    if earliest is None:
        earliest = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (PROFILE_FIRST_USED_KEY, earliest),
    )
    db.commit()
    return earliest


def _days_since(date_str: str) -> int:
    try:
        first = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return max((datetime.now().date() - first).days, 0)
    except (ValueError, TypeError):
        return 0


def _get_profile_picks(db: Connection) -> List[ClipOut]:
    rows = db.execute(
        "SELECT clip_id FROM profile_picks ORDER BY position"
    ).fetchall()
    picks: List[ClipOut] = []
    for row in rows:
        clip = db.execute("SELECT * FROM clips WHERE id = ?", (row["clip_id"],)).fetchone()
        if clip:
            picks.append(_row_to_clip(db, clip))
    return picks


def _build_profile_response(request: Request, db: Connection) -> ProfileOut:
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", (STATS_TOTAL_SAVED_KEY,)
    ).fetchone()
    total_saved = int(row["value"]) if row and row["value"].isdigit() else 0
    first_used = _ensure_profile_first_used(db)
    week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    week_count = db.execute(
        "SELECT COUNT(*) AS c FROM clips WHERE created_at >= ?", (week_cutoff,)
    ).fetchone()["c"]
    return ProfileOut(
        username=_get_profile_username(db),
        icon_url=_get_profile_icon_url(request),
        total_saved=total_saved,
        first_used_at=first_used[:10],
        days_since_first=_days_since(first_used),
        saved_last_7_days=week_count,
        picks=_get_profile_picks(db),
    )


@router.get("/profile", response_model=ProfileOut)
def get_profile(request: Request, db: Connection = Depends(get_db)):
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", (STATS_TOTAL_SAVED_KEY,)
    ).fetchone()
    if not (row and row["value"].isdigit()):
        total_saved = db.execute("SELECT COUNT(*) AS c FROM clips").fetchone()["c"]
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (STATS_TOTAL_SAVED_KEY, str(total_saved)),
        )
        db.commit()
    return _build_profile_response(request, db)


@router.put("/profile/name", response_model=ProfileOut)
def update_profile_name(
    payload: ProfileNameUpdate, request: Request, db: Connection = Depends(get_db)
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="ユーザー名を入力してください。")
    if len(name) > 30:
        raise HTTPException(status_code=422, detail="ユーザー名は30文字以内にしてください。")
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        ("profile_username", name),
    )
    db.commit()
    return _build_profile_response(request, db)


@router.post("/profile/icon", response_model=ProfileOut)
def update_profile_icon(
    payload: ProfileIconUpdate, request: Request, db: Connection = Depends(get_db)
):
    match = _DATA_URL_RE.match(payload.data_url.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Invalid data URL format")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 data")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image data")

    saved = raw
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.thumbnail((256, 256))
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        saved = buf.getvalue()
    except Exception:
        pass
    profile_dir = get_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    target = profile_dir / PROFILE_ICON_FILENAME
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_bytes(saved)
    temporary.replace(target)
    return _build_profile_response(request, db)


@router.post("/profile/picks", response_model=ProfileOut, status_code=201)
def add_profile_pick(
    payload: ProfilePickAdd, request: Request, db: Connection = Depends(get_db)
):
    count = db.execute("SELECT COUNT(*) AS c FROM profile_picks").fetchone()["c"]
    if count >= PROFILE_PICKS_LIMIT:
        raise HTTPException(status_code=400, detail="おすすめのクリップは3つまで登録できます。")
    clip = db.execute("SELECT id FROM clips WHERE id = ?", (payload.clip_id,)).fetchone()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    db.execute(
        "INSERT OR IGNORE INTO profile_picks(clip_id, position) VALUES(?, ?)",
        (payload.clip_id, count),
    )
    db.commit()
    return _build_profile_response(request, db)


@router.delete("/profile/picks/{clip_id}", response_model=ProfileOut)
def remove_profile_pick(
    clip_id: int, request: Request, db: Connection = Depends(get_db)
):
    db.execute("DELETE FROM profile_picks WHERE clip_id = ?", (clip_id,))
    for position, row in enumerate(
        db.execute("SELECT clip_id FROM profile_picks ORDER BY position").fetchall()
    ):
        db.execute(
            "UPDATE profile_picks SET position = ? WHERE clip_id = ?",
            (position, row["clip_id"]),
        )
    db.commit()
    return _build_profile_response(request, db)


@router.post("/profile/stats/reset", response_model=ProfileOut)
def reset_profile_stats(request: Request, db: Connection = Depends(get_db)):
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (STATS_TOTAL_SAVED_KEY, "0"),
    )
    db.commit()
    return _build_profile_response(request, db)


@router.get("/data/ai-export/status")
def ai_export_status():
    return get_ai_export_status()


@router.get("/data/ai-edit/status", include_in_schema=False)
def ai_edit_status():
    from ai_import import get_edit_status

    return get_edit_status()


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
        proj_columns = _source_columns(source, "projects")
        cur = dest.execute(
            "INSERT INTO projects(name, description, is_done, done_snapshot, notes_done_snapshot, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["name"],
                row["description"],
                row["is_done"] or 0,
                row["done_snapshot"] if "done_snapshot" in row.keys() else None,
                _source_value(row, proj_columns, "notes_done_snapshot"),
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
            "is_favorite, embedding, created_at, clip_type, file_ref, file_size, is_folder, project_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                _source_value(row, clip_columns, "is_folder", 0) or 0,
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
        project_id = project_map.get(
            _source_id(_source_value(row, note_columns, "project_id"))
        )
        cur = dest.execute(
            "INSERT INTO notes(title, body, is_done, completed_at, created_at, updated_at, project_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["title"],
                row["body"],
                _source_value(row, note_columns, "is_done") or 0,
                _source_value(row, note_columns, "completed_at"),
                _migration_timestamp(row["created_at"]),
                _migration_timestamp(row["updated_at"]),
                project_id,
            ),
        )
        note_map[source_id] = int(cur.lastrowid)
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

    # Restore app settings and profile data from the source (migration semantics:
    # the imported backup wins on key collisions).
    for row in _source_rows(source, "settings"):
        dest.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (row["key"], row["value"]),
        )

    for row in _source_rows(source, "profile_picks"):
        clip_id = clip_map.get(_source_id(row["clip_id"]))
        if clip_id is not None:
            dest.execute(
                "INSERT OR IGNORE INTO profile_picks(clip_id, position) VALUES (?, ?)",
                (clip_id, int(row["position"] or 0)),
            )

    cleanup_orphan_tags(dest)

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
    settings_info = None
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
        elif name == "settings.json" and not info.is_dir():
            settings_info = info
        elif name == "uploads" or name.startswith("uploads/"):
            upload_infos.append((info, name))

    if db_info is None:
        raise ValueError("ZIP内にclips.dbがありません")
    return db_info, upload_infos, settings_info


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
def export_backup_archive(payload: Optional[BackupExportPayload] = None):
    """Create a ZIP containing clips.db, the uploads directory, and app settings."""
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
        settings_payload = {
            "browser": payload.browser_settings if payload else {},
        }
        with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "clips.db")
            archive.writestr(
                "settings.json", json.dumps(settings_payload, ensure_ascii=False)
            )
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
        "message": "clips.db、uploads、設定・プロフィール情報をZIPに保存しました。",
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
                db_info, upload_infos, settings_info = _inspect_backup_zip(archive)
                if archive.testzip() is not None:
                    raise ValueError("ZIP内のファイルを読み込めません")
                with archive.open(db_info, "r") as source, snapshot_path.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                settings_data = {}
                if settings_info is not None:
                    with archive.open(settings_info, "r") as source:
                        raw_settings = source.read(1024 * 1024)
                    try:
                        parsed = json.loads(raw_settings.decode("utf-8"))
                        if isinstance(parsed, dict):
                            settings_data = parsed
                    except (ValueError, UnicodeDecodeError):
                        settings_data = {}
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
            "message": "clips.dbを既存データに結合し、uploadsと設定・プロフィール情報を復元しました。",
            "merged": merged,
            "settings": settings_data,
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
    "image/avif": "avif",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
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


def _folder_total_size(path: Path) -> int:
    """Return the total size in bytes of every file under ``path``."""
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


class OpenFolderOut(BaseModel):
    path: Optional[str] = None
    name: Optional[str] = None
    size: int = 0


class InspectPathsIn(BaseModel):
    paths: List[str] = []


class InspectedPathOut(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int


class InspectPathsOut(BaseModel):
    entries: List[InspectedPathOut] = []


class CopyPathClipIn(BaseModel):
    path: str
    title: Optional[str] = None
    comment: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = ""


@router.post("/dialog/open-folder", response_model=OpenFolderOut)
def open_folder_dialog():
    """Open the native Windows folder picker and return the folder's path,
    name and total size (used to warn before a large copy-mode upload)."""
    try:
        selected = _choose_directory_with_windows_dialog(
            title="アップロードするフォルダーを選択",
            ok_label="このフォルダーを選択",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"フォルダ選択ダイアログを開けませんでした: {exc}") from exc
    if not selected:
        return OpenFolderOut()
    path = Path(selected)
    return OpenFolderOut(path=str(path), name=path.name, size=_folder_total_size(path))


@router.post("/dialog/inspect-paths", response_model=InspectPathsOut)
def inspect_paths(payload: InspectPathsIn):
    """Classify a list of dropped paths (file or directory) with their sizes."""
    entries = []
    for raw in payload.paths:
        path = Path(raw)
        name = path.name or raw
        if path.is_dir():
            entries.append(
                InspectedPathOut(path=raw, name=name, is_dir=True, size=_folder_total_size(path))
            )
        else:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            entries.append(InspectedPathOut(path=raw, name=name, is_dir=False, size=size))
    return InspectPathsOut(entries=entries)


def _resolve_clip_metadata(
    db: Connection,
    title: Optional[str],
    comment: Optional[str],
    category: Optional[str],
    tags: Optional[str],
):
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    category_id = _resolve_category(db, category)
    tag_ids = _resolve_tags(db, tag_list)
    return tag_ids, category_id


@router.post("/clips/local/copy-path", response_model=ClipOut, status_code=201)
def create_copy_path_clip(payload: CopyPathClipIn, db: Connection = Depends(get_db)):
    """Copy a file or a folder from the filesystem into the app folder and create
    one clip for it (copy mode). Folders are copied recursively as a single clip."""
    source = Path(payload.path)
    if not source.exists():
        raise HTTPException(status_code=400, detail="指定されたパスが見つかりません")

    tag_ids, category_id = _resolve_clip_metadata(
        db, payload.title, payload.comment, payload.category, payload.tags
    )

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = uuid.uuid4().hex
    try:
        if source.is_dir():
            dest = LOCAL_DIR / stored_name
            shutil.copytree(source, dest)
            url = f"local://copy/{stored_name}"
            is_folder = 1
            file_size = _folder_total_size(dest)
            original_name = source.name
        else:
            dest = LOCAL_DIR / f"{stored_name}{source.suffix}"
            shutil.copyfile(source, dest)
            url = f"local://copy/{stored_name}{source.suffix}"
            is_folder = 0
            try:
                file_size = source.stat().st_size
            except OSError:
                file_size = None
            original_name = source.name
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"ファイル/フォルダをコピーできませんでした（{type(exc).__name__}: {exc}）。"
            "読み取り権限、OneDrive などクラウド同期中のファイル、ロック中のファイルが"
            "原因の可能性があります。",
        ) from exc

    clip_title = payload.title or original_name
    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, file_size, is_folder) "
        "VALUES (?, ?, ?, ?, ?, 'local', 'copy', ?, ?)",
        (url, clip_title, None, payload.comment, category_id, file_size, is_folder),
    )
    clip_id = cur.lastrowid
    _set_tags(db, clip_id, tag_ids)
    _increment_total_saved(db)
    db.commit()
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _row_to_clip(db, row)


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
    _increment_total_saved(db)
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
    """Create a clip that references the original file or folder without copying."""
    tag_list = [t.strip() for t in (payload.tags or "").split(",") if t.strip()]
    category_id = _resolve_category(db, payload.category)
    tag_ids = _resolve_tags(db, tag_list)

    file_path = Path(payload.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="File not found at the specified path")

    is_folder = file_path.is_dir()
    original_name = file_path.name
    clip_title = payload.title or original_name
    ext_lower = file_path.suffix.lower()

    url = f"local://reference/{file_path}"

    thumbnail_url = None
    if not is_folder and ext_lower in IMAGE_EXTS:
        try:
            content = file_path.read_bytes()
            thumbnail_url = _generate_image_thumbnail(content, ext_lower)
        except Exception:
            pass
    elif not is_folder and ext_lower in VIDEO_EXTS:
        thumbnail_url = _generate_video_thumbnail(file_path)

    try:
        file_size = _folder_total_size(file_path) if is_folder else file_path.stat().st_size
    except OSError:
        file_size = None

    cur = db.execute(
        "INSERT INTO clips(url, title, thumbnail_url, comment, category_id, clip_type, file_ref, file_size, is_folder) "
        "VALUES (?, ?, ?, ?, ?, 'local', 'reference', ?, ?)",
        (url, clip_title, thumbnail_url, payload.comment, category_id, file_size, 1 if is_folder else 0),
    )
    clip_id = cur.lastrowid
    _set_tags(db, clip_id, tag_ids)
    _increment_total_saved(db)
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
    if not (file_path.is_file() or file_path.is_dir()):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return LocalFilePathOut(path=str(file_path))


@router.get("/clips/{clip_id}/file")
def get_local_file(
    clip_id: int,
    request: Request,
    db: Connection = Depends(get_db),
):
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

    if "/reference/" in url:
        file_path = Path(url.split("/reference/", 1)[1])
    else:
        name = url.rsplit("/", 1)[-1]
        if not name:
            raise HTTPException(status_code=400, detail="Invalid file path")
        file_path = LOCAL_DIR / name
    if file_path.is_dir():
        raise HTTPException(status_code=400, detail="フォルダはプレビューできません")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    total_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            str(file_path),
            filename=file_path.name,
            headers={"Accept-Ranges": "bytes"},
        )

    byte_range = _parse_single_byte_range(range_header, total_size)
    if byte_range is None:
        return Response(
            status_code=416,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{total_size}",
            },
        )

    start, end = byte_range
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    length = end - start + 1
    return StreamingResponse(
        _iter_file_range(file_path, start, length),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{total_size}",
        },
    )


def _parse_single_byte_range(value: str, total_size: int) -> Optional[tuple[int, int]]:
    """Parse one RFC 7233 byte range and return inclusive start/end offsets."""
    if total_size <= 0 or not value.lower().startswith("bytes="):
        return None
    raw_range = value[6:].strip()
    if not raw_range or "," in raw_range or "-" not in raw_range:
        return None
    raw_start, raw_end = (part.strip() for part in raw_range.split("-", 1))
    try:
        if not raw_start:
            suffix_length = int(raw_end)
            if suffix_length <= 0:
                return None
            return max(total_size - suffix_length, 0), total_size - 1

        start = int(raw_start)
        if start < 0 or start >= total_size:
            return None
        end = total_size - 1 if not raw_end else int(raw_end)
        if end < start:
            return None
        return start, min(end, total_size - 1)
    except ValueError:
        return None


def _iter_file_range(path: Path, start: int, length: int):
    with path.open("rb") as source:
        source.seek(start)
        remaining = length
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


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
    if not (file_path.is_file() or file_path.is_dir()):
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
    if not (file_path.is_file() or file_path.is_dir()):
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
    if file_path.is_dir():
        raise HTTPException(status_code=400, detail="Not a previewable folder")
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


# --- App update -----------------------------------------------------------

@router.get("/update/status", include_in_schema=False)
def update_status(request: Request):
    """Return the cached auto-update state (stage, versions, progress)."""
    from updater import get_update_state

    return get_update_state()


@router.post("/update/check", include_in_schema=False)
def update_check():
    """Force a re-check against the release endpoint."""
    from updater import check_for_update

    check_for_update()
    return {"ok": True}


@router.post("/update/download", include_in_schema=False)
def update_download():
    """Start downloading and verifying the pending release (async)."""
    from updater import start_download

    ok = start_download()
    return {"ok": ok}


@router.post("/update/apply", include_in_schema=False)
def update_apply(request: Request):
    """Install the staged update and restart the app."""
    callback = getattr(request.app.state, "update_apply", None)
    if not callable(callback):
        raise HTTPException(status_code=400, detail="更新機能は現在利用できません。")
    result = callback()
    if not result:
        from updater import get_update_state

        state = get_update_state()
        raise HTTPException(status_code=500, detail=state.get("error") or "更新に失敗しました。")
    return {"ok": True, "restarting": True}
