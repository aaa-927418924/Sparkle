"""Same-origin proxy for Sparkle's desktop remote-data mode."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from email.message import Message
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from paths import get_ai_export_dir
from remote_client import RemoteClient, RemoteClientError, RemoteResponse, RemoteStreamResponse


_PROXY_ROOTS = (
    "/clipboard",
    "/clips",
    "/categories",
    "/tags",
    "/tasks",
    "/notes",
    "/projects",
    "/url-metadata",
    "/thumbnail-proxy",
    "/uploads",
    "/ai",
    "/profile",
    "/settings",
    "/data",
    "/maintenance",
)
_LOCAL_ONLY_PREFIXES = (
    "/settings/remote-access",
    "/settings/remote-client",
    "/setup",
    "/migration",
    "/dialog",
    "/update",
)
_REMOTE_DENIED_PATHS = {
    "/data/export-backup",
    "/data/import-backup",
}
_LOCAL_FILE_OPERATION_RE = re.compile(r"^/clips/(\d+)/(path|open|explorer)$")
_LOCAL_FILE_NAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\'|"?)([^";]+)', re.IGNORECASE)
_MAX_REMOTE_PATH_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _path_matches_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def should_proxy_path(path: str) -> bool:
    if any(path == prefix or path.startswith(prefix + "/") for prefix in _LOCAL_ONLY_PREFIXES):
        return False
    return any(_path_matches_root(path, root) for root in _PROXY_ROOTS)


def _json_response(status_code: int, body: Mapping[str, Any]) -> JSONResponse:
    return JSONResponse(dict(body), status_code=status_code, headers={"Cache-Control": "no-store"})


def _response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "accept-ranges",
        "cache-control",
        "content-disposition",
        "content-length",
        "content-range",
        "content-type",
        "etag",
        "last-modified",
    }
    return {str(key): str(value) for key, value in headers.items() if str(key).lower() in allowed}


def _rewrite_local_resource_url(client: RemoteClient, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    base = client.base_url()
    if base and value.startswith(base):
        parsed = urlsplit(value)
        if parsed.path.startswith(("/uploads/", "/thumbnail-proxy", "/clips/")):
            return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
    return value


def _rewrite_remote_payload(client: RemoteClient, value: Any, path: str) -> Any:
    if isinstance(value, list):
        return [_rewrite_remote_payload(client, item, path) for item in value]
    if not isinstance(value, dict):
        return value

    rewritten: dict[str, Any] = {}
    kind = value.get("kind")
    source_id = value.get("id")
    for key, item in value.items():
        if key in {"thumbnail_url", "href", "icon_url"}:
            rewritten[key] = _rewrite_local_resource_url(client, item)
        elif key == "path" and path.startswith("/data/ai-export"):
            rewritten[key] = str(get_ai_export_dir())
        else:
            rewritten[key] = _rewrite_remote_payload(client, item, path)
    if kind == "clip" and isinstance(source_id, int) and not str(rewritten.get("href") or "").strip():
        rewritten["href"] = f"/clips/{source_id}/file"
    return rewritten


def _response_from_remote(client: RemoteClient, response: RemoteResponse, path: str = "") -> Response:
    body = response.body
    headers = _response_headers(response.headers)
    content_type = next(
        (value for key, value in response.headers.items() if key.lower() == "content-type"),
        "",
    )
    if "application/json" in content_type.lower():
        try:
            payload = json.loads(body.decode("utf-8"))
            body = json.dumps(
                _rewrite_remote_payload(client, payload, path),
                ensure_ascii=False,
            ).encode("utf-8")
            headers = {
                key: value
                for key, value in headers.items()
                if key.lower() != "content-length"
            }
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=None,
    )


def _next_stream_chunk(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _stream_response_from_remote(response: RemoteStreamResponse) -> StreamingResponse:
    headers = _response_headers(response.headers)
    headers = {key: value for key, value in headers.items() if key.lower() != "content-length"}
    headers["Cache-Control"] = "no-cache, no-store"
    headers["X-Accel-Buffering"] = "no"

    async def body():
        while True:
            chunk = await asyncio.to_thread(_next_stream_chunk, response.body)
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        headers=headers,
        media_type=None,
    )


def _parse_remote_json(response: RemoteResponse) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _filename_from_response(response: RemoteResponse, fallback: str) -> str:
    raw = ""
    for key, value in response.headers.items():
        if key.lower() == "content-disposition":
            raw = value
            break
    match = _LOCAL_FILE_NAME_RE.search(raw)
    candidate = match.group(1) if match else fallback
    candidate = str(candidate or fallback).strip().replace("\\", "_").replace("/", "_")
    candidate = re.sub(r'[<>:"|?*\x00-\x1f]', "_", candidate).strip(" .")
    return candidate[:180] or fallback


def _cache_remote_file(client: RemoteClient, clip_id: int) -> Path:
    response = client.request(f"/clips/{clip_id}/file", method="GET")
    if response.status_code < 200 or response.status_code >= 300:
        detail = _parse_remote_json(response).get("detail") or "サーバー上のファイルを取得できませんでした。"
        raise RemoteClientError(str(detail), response.status_code)
    filename = _filename_from_response(response, f"clip-{clip_id}")
    target = client.cache_dir() / f"clip-{clip_id}-{filename}"
    target.write_bytes(response.body)
    return target


def _open_cached_file(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))
    elif os.name == "posix":
        subprocess.Popen(["xdg-open", str(path)])


def _reveal_cached_file(path: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif os.name == "posix":
        subprocess.Popen(["xdg-open", str(path.parent)])


def _handle_cached_file_operation(client: RemoteClient, path: str) -> Optional[Response]:
    match = _LOCAL_FILE_OPERATION_RE.match(path)
    if not match:
        return None
    clip_id = int(match.group(1))
    operation = match.group(2)
    cached = _cache_remote_file(client, clip_id)
    if operation == "path":
        return _json_response(200, {"path": str(cached)})
    if operation == "open":
        _open_cached_file(cached)
    else:
        _reveal_cached_file(cached)
    return _json_response(200, {"status": "ok", "path": str(cached)})


def _multipart_body(
    file_path: Path,
    filename: str,
    fields: Mapping[str, Any],
) -> tuple[bytes, str]:
    boundary = f"----SparkleRemote{os.urandom(12).hex()}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        if value is None:
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename.replace(chr(34), "_")}\"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _zip_folder(path: Path) -> Path:
    temporary = Path(tempfile.mkstemp(prefix="sparkle-remote-folder-", suffix=".zip")[1])
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for child in path.rglob("*"):
                if child.is_symlink() or not child.is_file():
                    continue
                archive.write(child, child.relative_to(path.parent).as_posix())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _handle_local_path_upload(client: RemoteClient, path: str, body: bytes) -> RemoteResponse:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteClientError("ファイル情報を読み取れませんでした。", 422) from exc
    if not isinstance(payload, dict):
        raise RemoteClientError("ファイル情報が不正です。", 422)
    raw_path = payload.get("path") or payload.get("file_path")
    source = Path(str(raw_path or ""))
    if not source.exists() or not (source.is_file() or source.is_dir()):
        raise RemoteClientError("クライアント側のファイルが見つかりません。", 400)
    if source.is_file() and source.stat().st_size > _MAX_REMOTE_PATH_UPLOAD_BYTES:
        raise RemoteClientError("ファイルサイズが大きすぎます。", 413)

    temporary: Optional[Path] = None
    upload_path = source
    is_folder = source.is_dir()
    try:
        if is_folder:
            temporary = _zip_folder(source)
            upload_path = temporary
        fields = {
            "title": payload.get("title") or source.name,
            "comment": payload.get("comment") or "",
            "category": payload.get("category") or "",
            "tags": payload.get("tags") or "",
            "is_folder": "true" if is_folder else "false",
        }
        multipart, content_type = _multipart_body(upload_path, source.name if not is_folder else f"{source.name}.zip", fields)
        return client.request(
            "/clips/local",
            method="POST",
            body=multipart,
            headers={"Content-Type": content_type, "Accept": "application/json"},
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _download_ai_export_to_client(client: RemoteClient) -> Response:
    response = client.request("/data/ai-export/files", method="GET")
    if response.status_code < 200 or response.status_code >= 300:
        return _response_from_remote(client, response, "/data/ai-export/files")
    data = _parse_remote_json(response)
    files = data.get("files") if isinstance(data, dict) else None
    target_dir = get_ai_export_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    for item in files or []:
        name = str(item or "").strip()
        if not name or Path(name).name != name or name not in {
            "README.md", "index.md", "all.md", "clips.md", "notes.md", "tasks.md", "projects.md", "taxonomy.md"
        }:
            continue
        file_response = client.request(f"/data/ai-export/files/{name}", method="GET")
        if 200 <= file_response.status_code < 300:
            (target_dir / name).write_bytes(file_response.body)
            downloaded.append(name)
    if os.name == "nt":
        os.startfile(str(target_dir))
    elif os.name == "posix":
        subprocess.Popen(["xdg-open", str(target_dir)])
    return _json_response(200, {"ok": True, "path": str(target_dir), "files": downloaded})


class RemoteClientProxy:
    """FastAPI middleware implementation for remote mode."""

    def __init__(self, client: RemoteClient):
        self.client = client
        # A desktop remote session can receive a burst of writes from several
        # WebView pages at once. Keep ordinary requests in one order so a
        # read-after-write cannot overtake a pending mutation. Streaming Ask
        # AI requests remain separate because their response is long-lived.
        self._request_lock = threading.RLock()

    def _serialized_request(self, path, method, body, headers):
        with self._request_lock:
            return self.client.request(path, method, body, headers)

    def _serialized_call(self, callback, *args):
        with self._request_lock:
            return callback(*args)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        query = str(request.url.query or "")
        forward_path = f"{path}?{query}" if query else path
        # RemoteGateway forwards authenticated client requests into the same
        # FastAPI app. If this process also has its own client mode enabled,
        # never proxy that already-forwarded request back out to another
        # server.
        remote_auth = (request.scope.get("state") or {}).get("remote_auth")
        if isinstance(remote_auth, dict) and remote_auth.get("client"):
            return await call_next(request)
        if not self.client.is_enabled() or not should_proxy_path(path):
            return await call_next(request)
        if path in _REMOTE_DENIED_PATHS:
            return _json_response(409, {"detail": "この操作はサーバーモードでは利用できません。"})

        try:
            if path == "/data/ai-export/open" and request.method.upper() == "POST":
                return await asyncio.to_thread(
                    self._serialized_call,
                    _download_ai_export_to_client,
                    self.client,
                )

            local_file_response = await asyncio.to_thread(
                self._serialized_call,
                _handle_cached_file_operation,
                self.client,
                path,
            )
            if local_file_response is not None:
                return local_file_response

            body = await request.body()
            if path in {"/clips/local/reference", "/clips/local/copy-path"}:
                response = await asyncio.to_thread(
                    self._serialized_call,
                    _handle_local_path_upload,
                    self.client,
                    path,
                    body,
                )
            elif path.endswith("/assistant/stream") and request.method.upper() == "POST":
                response = await asyncio.to_thread(
                    self.client.stream_request,
                    forward_path,
                    request.method,
                    body,
                    dict(request.headers),
                )
                return _stream_response_from_remote(response)
            else:
                response = await asyncio.to_thread(
                    self._serialized_request,
                    forward_path,
                    request.method,
                    body,
                    dict(request.headers),
                )
            return _response_from_remote(self.client, response, path)
        except RemoteClientError as exc:
            return _json_response(exc.status_code, {"detail": exc.message})
        except (OSError, ValueError) as exc:
            return _json_response(422, {"detail": f"リモート操作に失敗しました: {exc}"})
