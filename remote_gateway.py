"""Authenticated remote Web gateway for Sparkle.

The normal desktop FastAPI application stays on 127.0.0.1:8000 and keeps its
existing no-login behavior.  This ASGI gateway is bound to a separate local
port and exposes only the dedicated mobile Web UI plus an allow-listed subset
of the data API.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from paths import get_resource_dir
from remote_auth import AuthStore, InvalidAccessKey, get_mcp_auth_store


LOGGER = logging.getLogger("sparkle.remote_gateway")
SESSION_COOKIE = "__Host-sparkle_remote_session"
CSRF_COOKIE = "__Host-sparkle_remote_csrf"
REMOTE_DIR = get_resource_dir() / "frontend" / "remote"


class RemoteLoginPayload(BaseModel):
    access_key: str = Field(..., min_length=1, max_length=256)
    trust_device: bool = False
    device_label: str = Field(default="ブラウザ", max_length=80)


def _cookie_secure(request: Request) -> bool:
    # Tailscale terminates HTTPS before forwarding to this local listener. The
    # secure flag is therefore always correct for the public URL.  Keeping it
    # enabled for direct local tests also prevents accidental bearer-cookie
    # transmission over an ordinary network HTTP connection.
    return True


def _set_auth_cookies(response, request: Request, token: str, csrf_token: str, persistent: bool) -> None:
    max_age = 365 * 24 * 60 * 60 if persistent else None
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response, request: Request) -> None:
    secure = _cookie_secure(request)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


def _auth_from_request(request: Request, store: AuthStore) -> Optional[dict[str, Any]]:
    return store.authenticate(request.cookies.get(SESSION_COOKIE))


def _build_public_app(store: AuthStore) -> FastAPI:
    public_app = FastAPI(
        title="Sparkle Remote Web",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @public_app.get("/", include_in_schema=False)
    def remote_root(request: Request):
        filename = "remote.html" if _auth_from_request(request, store) else "remote-login.html"
        return FileResponse(
            REMOTE_DIR / filename,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @public_app.get("/remote-login", include_in_schema=False)
    def remote_login_page():
        return FileResponse(
            REMOTE_DIR / "remote-login.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @public_app.get("/remote/session", include_in_schema=False)
    def remote_session(request: Request):
        record = _auth_from_request(request, store)
        if record is None:
            return JSONResponse({"authenticated": False})
        return JSONResponse(
            {
                "authenticated": True,
                "persistent": bool(record.get("persistent")),
                "expires_at": record.get("expires_at"),
            },
            headers={"Cache-Control": "no-store"},
        )

    @public_app.post("/remote/login", include_in_schema=False)
    def remote_login(payload: RemoteLoginPayload, request: Request):
        try:
            result = store.login(
                payload.access_key,
                trust_device=payload.trust_device,
                device_label=payload.device_label,
            )
        except InvalidAccessKey:
            return JSONResponse(
                {"ok": False, "detail": "アクセスキーが正しくありません。"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        response = JSONResponse(
            {
                "ok": True,
                "authenticated": True,
                "persistent": result["persistent"],
                "expires_at": result["expires_at"],
            },
            headers={"Cache-Control": "no-store"},
        )
        _set_auth_cookies(
            response,
            request,
            result["token"],
            csrf_token=secrets.token_urlsafe(24),
            persistent=result["persistent"],
        )
        return response

    @public_app.post("/remote/logout", include_in_schema=False)
    def remote_logout(request: Request):
        store.logout(request.cookies.get(SESSION_COOKIE))
        response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        _clear_auth_cookies(response, request)
        return response

    public_app.mount(
        "/remote/static",
        StaticFiles(directory=str(REMOTE_DIR), check_dir=True),
        name="remote-static",
    )
    return public_app


class RemoteGateway:
    """Route the public remote shell and protect the selected main API routes."""

    _PUBLIC_PATHS = {
        "/",
        "/remote-login",
        "/remote/session",
        "/remote/login",
        "/remote/logout",
        "/health",
    }
    _SAFE_SETTINGS = {
        "auto_create_note_on_project",
        "task_auto_delete",
        "file_save_method",
    }
    _PROTECTED_ROOTS = {
        "/clips",
        "/categories",
        "/tags",
        "/tasks",
        "/notes",
        "/projects",
        "/url-metadata",
        "/thumbnail-proxy",
        "/uploads",
    }
    _DENIED_PATHS = {
        "/clips/local/reference",
        "/clips/local/copy-path",
        "/dialog/open-files",
        "/dialog/open-folder",
        "/dialog/inspect-paths",
    }
    _DENIED_SUFFIXES = ("/path", "/open", "/explorer")

    def __init__(
        self,
        main_app: ASGIApp,
        store: AuthStore,
        mcp_runtime: Any = None,
        mcp_auth_store: Optional[AuthStore] = None,
    ) -> None:
        self.main_app = main_app
        self.store = store
        self.public_app = _build_public_app(store)
        self.mcp_auth_store = mcp_auth_store or get_mcp_auth_store()
        self.mcp_runtime = mcp_runtime
        if self.mcp_runtime is None:
            try:
                import os

                from remote_mcp import build_remote_mcp_runtime

                self.mcp_runtime = build_remote_mcp_runtime(
                    auth_store=self.mcp_auth_store,
                    host="127.0.0.1",
                    port=8001,
                    public_url=os.environ.get("SPARKLE_MCP_PUBLIC_URL"),
                    static_token=os.environ.get("SPARKLE_MCP_TOKEN"),
                )
            except (ImportError, ValueError) as exc:
                # The MCP dependency is optional for existing Remote Web
                # deployments.  The Web gateway remains usable when only the
                # original GUI requirements are installed.
                LOGGER.warning("Remote MCP is unavailable: %s", exc)
                self.mcp_runtime = None

    @staticmethod
    def _path_matches_root(path: str, root: str) -> bool:
        return path == root or path.startswith(root + "/")

    def _is_public(self, path: str) -> bool:
        return (
            path in self._PUBLIC_PATHS
            or path in {"/remote/static", "/remote/static/"}
            or path.startswith("/remote/static/")
        )

    def _is_allowed_setting(self, path: str) -> bool:
        parts = path.split("/")
        return len(parts) == 3 and parts[1] == "settings" and parts[2] in self._SAFE_SETTINGS

    def _is_protected(self, path: str) -> bool:
        if path in self._DENIED_PATHS:
            return False
        if path.startswith("/clips/") and path.endswith(self._DENIED_SUFFIXES):
            return False
        if self._is_allowed_setting(path):
            return True
        return any(self._path_matches_root(path, root) for root in self._PROTECTED_ROOTS)

    @staticmethod
    def _origin_is_same_request(scope: Scope) -> bool:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        origin = headers.get("origin")
        if not origin:
            return True
        host = headers.get("host", "")
        return origin in {f"http://{host}", f"https://{host}"}

    def _has_csrf(self, scope: Scope, receive: Receive) -> bool:
        # The receive callable is intentionally unused; keeping this check
        # synchronous avoids buffering upload bodies before authorization.
        del receive
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        cookie_header = headers.get("cookie", "")
        csrf_cookie = None
        for chunk in cookie_header.split(";"):
            name, separator, value = chunk.strip().partition("=")
            if separator and name == CSRF_COOKIE:
                csrf_cookie = value
                break
        submitted = headers.get("x-sparkle-csrf")
        return bool(
            csrf_cookie
            and submitted
            and hmac.compare_digest(csrf_cookie, submitted)
            and self._origin_is_same_request(scope)
        )

    @staticmethod
    async def _send_json(
        scope: Scope,
        receive: Receive,
        send: Send,
        body: dict[str, Any],
        status_code: int,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        response = JSONResponse(body, status_code=status_code, headers=headers or {})
        await response(scope, receive, send)

    async def _forward_main(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        record: dict[str, Any],
    ) -> None:
        state = dict(scope.get("state") or {})
        state["remote_auth"] = record
        forwarded_scope = dict(scope)
        forwarded_scope["state"] = state
        forwarded_scope["headers"] = list(scope.get("headers", []))
        async def send_with_private_headers(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                header_names = {
                    key.decode("latin-1").lower()
                    for key, _ in headers
                }
                if "cache-control" not in header_names:
                    headers.append((b"cache-control", b"private, no-store"))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.main_app(forwarded_scope, receive, send_with_private_headers)

    async def _handle_lifespan(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run FastAPI and MCP startup/shutdown in the same ASGI process."""

        if self.mcp_runtime is None:
            await self.main_app(scope, receive, send)
            return

        router = getattr(self.main_app, "router", None)
        main_lifespan = getattr(router, "lifespan_context", None)
        if main_lifespan is None:
            await self.main_app(scope, receive, send)
            return

        started = False
        try:
            async with main_lifespan(self.main_app):
                async with self.mcp_runtime.lifespan_context():
                    await receive()
                    await send({"type": "lifespan.startup.complete"})
                    started = True
                    while True:
                        message = await receive()
                        if message.get("type") == "lifespan.shutdown":
                            await send({"type": "lifespan.shutdown.complete"})
                            return
        except BaseException as exc:
            LOGGER.exception("Remote gateway lifespan failed")
            await send(
                {
                    "type": "lifespan.shutdown.failed" if started else "lifespan.startup.failed",
                    "message": str(exc)[:500],
                }
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return
        if scope_type == "websocket":
            await self.main_app(scope, receive, send)
            return
        if scope_type != "http":
            await self.main_app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        if self.mcp_runtime is not None and self.mcp_runtime.handles_path(path):
            await self.mcp_runtime.app(scope, receive, send)
            return
        if path == "/health":
            await JSONResponse({"status": "ok", "app": "Sparkle Remote"})(scope, receive, send)
            return
        if self._is_public(path):
            await self.public_app(scope, receive, send)
            return

        if not self._is_protected(path):
            await self._send_json(
                scope,
                receive,
                send,
                {"detail": "このURLはリモートWebから利用できません。"},
                404,
                {"Cache-Control": "no-store"},
            )
            return

        record = _auth_from_request(
            Request(scope, receive),
            self.store,
        )
        if record is None:
            await self._send_json(
                scope,
                receive,
                send,
                {"detail": "ログインが必要です。"},
                401,
                {
                    "Cache-Control": "no-store",
                    "WWW-Authenticate": "Bearer",
                },
            )
            return

        if method in {"POST", "PUT", "PATCH", "DELETE"} and not self._has_csrf(scope, receive):
            await self._send_json(
                scope,
                receive,
                send,
                {"detail": "CSRF検証に失敗しました。ページを再読み込みしてください。"},
                403,
                {"Cache-Control": "no-store"},
            )
            return

        await self._forward_main(scope, receive, send, record)
