"""Remote MCP runtime for Sparkle.

The MCP tool definitions and read-only data service live in ``sparkle_mcp``
and are shared with the local stdio server.  This module only adds the
Streamable HTTP transport and the small OAuth resource/authorization server
needed by web MCP clients.

The OAuth implementation is intentionally read-only and single-user for this
initial release. It uses a dedicated MCP access key as the user login, keeps
short-lived OAuth state in memory, and never stores plaintext tokens. Per-user
identity and an external identity provider can replace this layer later
without changing the MCP tools.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.streamable_http import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp_server import build_server
from remote_auth import AuthStore, get_mcp_auth_store


LOGGER = logging.getLogger("sparkle_mcp.remote")

MCP_PATH = "/mcp"
MCP_SCOPE = "sparkle.read"
DEFAULT_ACCESS_TOKEN_TTL = 60 * 60
DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60
AUTHORIZATION_REQUEST_TTL = 10 * 60
AUTHORIZATION_CODE_TTL = 5 * 60
MAX_FORM_BODY = 16 * 1024
OAUTH_PATHS = frozenset(
    {
        "/oauth/authorize",
        "/oauth/approve",
        "/oauth/token",
        "/oauth/register",
        "/oauth/revoke",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
        MCP_PATH,
    }
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _no_store_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _json_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status_code,
        headers=_no_store_headers(),
    )


async def _read_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_FORM_BODY:
        raise ValueError("OAuthリクエストが大きすぎます。")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("OAuthリクエストの形式が正しくありません。") from exc
    return {key: values[-1] for key, values in parsed.items() if values}


def _normalize_public_url(value: Optional[str], default: str) -> str:
    raw = str(value or default).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("SPARKLE_MCP_PUBLIC_URLはhttp(s)のMCP URLで指定してください。")
    if parsed.query or parsed.fragment:
        raise ValueError("SPARKLE_MCP_PUBLIC_URLにquery/fragmentは指定できません。")
    path = parsed.path.rstrip("/") or MCP_PATH
    if path != MCP_PATH:
        raise ValueError(f"SPARKLE_MCP_PUBLIC_URLのパスは{MCP_PATH}で指定してください。")
    return urlunsplit((parsed.scheme, parsed.netloc, MCP_PATH, "", ""))


def _issuer_from_resource(resource_url: str) -> str:
    parsed = urlsplit(resource_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _valid_redirect_uri(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlsplit(value)
    if parsed.fragment or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    if parsed.scheme != "http":
        return False
    return parsed.hostname in {"localhost", "127.0.0.1", "[::1]", "::1"} and bool(parsed.netloc)


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class _OAuthClient:
    client_id: str
    redirect_uris: tuple[str, ...]
    grant_types: tuple[str, ...]
    token_endpoint_auth_method: str
    client_secret_hash: Optional[str]
    client_name: str
    created_at: int


@dataclass
class _PendingAuthorization:
    request_id: str
    form_token: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    state: Optional[str]
    scope: str
    resource: str
    expires_at: float


@dataclass
class _AuthorizationCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    subject: str
    scope: str
    resource: str
    expires_at: float


@dataclass
class _RefreshGrant:
    client_id: str
    subject: str
    scope: str
    resource: str
    expires_at: float


@dataclass
class _AccessGrant:
    client_id: str
    subject: str
    scope: str
    resource: str
    expires_at: float


class OAuthInputError(ValueError):
    """An OAuth request failed validation before credentials were used."""


class _LoginRateLimiter:
    """Bound failed OAuth access-key attempts without logging credentials."""

    def __init__(self, max_failures: int = 10, window_seconds: int = 5 * 60) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._lock = threading.RLock()
        self._failures: dict[str, list[float]] = {}

    def allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            recent = [item for item in self._failures.get(key, []) if item > now - self.window_seconds]
            self._failures[key] = recent
            return len(recent) < self.max_failures

    def failed(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(time.time())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class RemoteMcpOAuth:
    """Small in-process OAuth server for the single local Sparkle owner."""

    def __init__(self, auth_store: AuthStore, issuer_url: str, resource_url: str) -> None:
        self.auth_store = auth_store
        self.issuer_url = issuer_url.rstrip("/")
        self.resource_url = resource_url
        self._lock = threading.RLock()
        self._clients: dict[str, _OAuthClient] = {}
        self._pending: dict[str, _PendingAuthorization] = {}
        self._codes: dict[str, _AuthorizationCode] = {}
        self._refresh_tokens: dict[str, _RefreshGrant] = {}
        self._access_tokens: dict[str, _AccessGrant] = {}
        self._login_limiter = _LoginRateLimiter()

    def _purge_locked(self) -> None:
        now = time.time()
        self._pending = {key: value for key, value in self._pending.items() if value.expires_at > now}
        self._codes = {key: value for key, value in self._codes.items() if value.expires_at > now}
        self._refresh_tokens = {
            key: value for key, value in self._refresh_tokens.items() if value.expires_at > now
        }
        self._access_tokens = {
            key: value for key, value in self._access_tokens.items() if value.expires_at > now
        }

    def register_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        redirects = payload.get("redirect_uris")
        if not isinstance(redirects, list) or not redirects or len(redirects) > 20:
            raise OAuthInputError("redirect_urisが必要です。")
        redirect_uris = tuple(str(item) for item in redirects)
        if any(not _valid_redirect_uri(uri) for uri in redirect_uris):
            raise OAuthInputError("redirect_urisにはHTTPSまたはloopback HTTP URIだけ指定できます。")

        auth_method = str(payload.get("token_endpoint_auth_method") or "none")
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise OAuthInputError("token_endpoint_auth_methodに対応していません。")
        grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
        response_types = payload.get("response_types") or ["code"]
        if not isinstance(grant_types, list) or any(not isinstance(item, str) for item in grant_types):
            raise OAuthInputError("grant_typesが正しくありません。")
        if not isinstance(response_types, list) or any(not isinstance(item, str) for item in response_types):
            raise OAuthInputError("response_typesが正しくありません。")
        if "authorization_code" not in grant_types or set(grant_types) - {
            "authorization_code",
            "refresh_token",
        }:
            raise OAuthInputError("authorization_codeとrefresh_tokenだけを許可しています。")
        if set(response_types) != {"code"}:
            raise OAuthInputError("response_typesはcodeだけを許可しています。")

        client_id = f"sparkle_{secrets.token_urlsafe(18)}"
        client_secret = secrets.token_urlsafe(32) if auth_method != "none" else None
        client = _OAuthClient(
            client_id=client_id,
            redirect_uris=redirect_uris,
            grant_types=tuple(grant_types),
            token_endpoint_auth_method=auth_method,
            client_secret_hash=_hash_text(client_secret) if client_secret else None,
            client_name=str(payload.get("client_name") or "MCP client")[:200],
            created_at=int(time.time()),
        )
        with self._lock:
            self._purge_locked()
            self._clients[client_id] = client

        response: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": client.created_at,
            "redirect_uris": list(redirect_uris),
            "grant_types": grant_types,
            "response_types": ["code"],
            "token_endpoint_auth_method": auth_method,
        }
        if client_secret:
            response["client_secret"] = client_secret
        return response

    def _client(self, client_id: str) -> _OAuthClient:
        with self._lock:
            self._purge_locked()
            client = self._clients.get(client_id)
        if client is None:
            raise OAuthInputError("client_idが無効です。")
        return client

    def authorization_request(self, params: Any) -> tuple[_PendingAuthorization, _OAuthClient]:
        response_type = str(params.get("response_type") or "")
        client_id = str(params.get("client_id") or "")
        redirect_uri = str(params.get("redirect_uri") or "")
        code_challenge = str(params.get("code_challenge") or "")
        code_challenge_method = str(params.get("code_challenge_method") or "S256")
        scope = str(params.get("scope") or MCP_SCOPE)
        resource = str(params.get("resource") or self.resource_url)

        if response_type != "code":
            raise OAuthInputError("response_type=codeだけを許可しています。")
        client = self._client(client_id)
        if redirect_uri not in client.redirect_uris:
            raise OAuthInputError("redirect_uriが登録値と一致しません。")
        if not code_challenge or code_challenge_method != "S256":
            raise OAuthInputError("PKCE (S256) が必要です。")
        requested_scopes = set(scope.split())
        if requested_scopes - {MCP_SCOPE}:
            raise OAuthInputError("要求されたscopeには対応していません。")
        if resource.rstrip("/") not in {self.resource_url.rstrip("/"), self.issuer_url}:
            raise OAuthInputError("resourceがこのMCPサーバーと一致しません。")

        pending = _PendingAuthorization(
            request_id=secrets.token_urlsafe(18),
            form_token=secrets.token_urlsafe(24),
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=str(params.get("state")) if params.get("state") is not None else None,
            scope=MCP_SCOPE,
            resource=self.resource_url,
            expires_at=time.time() + AUTHORIZATION_REQUEST_TTL,
        )
        with self._lock:
            self._purge_locked()
            self._pending[pending.request_id] = pending
        return pending, client

    def _issue_tokens_locked(
        self,
        client_id: str,
        subject: str,
        scope: str,
        resource: str,
        include_refresh: bool,
    ) -> dict[str, Any]:
        now = time.time()
        access_token = secrets.token_urlsafe(32)
        access_expires = now + DEFAULT_ACCESS_TOKEN_TTL
        self._access_tokens[_hash_text(access_token)] = _AccessGrant(
            client_id=client_id,
            subject=subject,
            scope=scope,
            resource=resource,
            expires_at=access_expires,
        )
        response = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": DEFAULT_ACCESS_TOKEN_TTL,
            "scope": scope,
        }
        if include_refresh:
            refresh_token = secrets.token_urlsafe(32)
            self._refresh_tokens[_hash_text(refresh_token)] = _RefreshGrant(
                client_id=client_id,
                subject=subject,
                scope=scope,
                resource=resource,
                expires_at=now + DEFAULT_REFRESH_TOKEN_TTL,
            )
            response["refresh_token"] = refresh_token
        return response

    def approve_access(
        self,
        request_id: str,
        form_token: str,
        access_key: str,
        attempt_key: str = "unknown",
    ) -> str:
        with self._lock:
            self._purge_locked()
            pending = self._pending.get(request_id)
        if pending is None or not hmac.compare_digest(pending.form_token, form_token):
            raise OAuthInputError("認証リクエストが期限切れです。最初から再試行してください。")
        if not self._login_limiter.allowed(attempt_key):
            raise OAuthInputError("認証試行が多すぎます。5分後に再試行してください。")
        if not self.auth_store.validate_access_key(access_key):
            self._login_limiter.failed(attempt_key)
            raise OAuthInputError("MCP公開用アクセスキーが正しくありません。")
        self._login_limiter.succeeded(attempt_key)

        code = secrets.token_urlsafe(32)
        with self._lock:
            self._pending.pop(request_id, None)
            self._codes[_hash_text(code)] = _AuthorizationCode(
                client_id=pending.client_id,
                redirect_uri=pending.redirect_uri,
                code_challenge=pending.code_challenge,
                subject="local-user",
                scope=pending.scope,
                resource=pending.resource,
                expires_at=time.time() + AUTHORIZATION_CODE_TTL,
            )
        query = {"code": code}
        if pending.state is not None:
            query["state"] = pending.state
        separator = "&" if "?" in pending.redirect_uri else "?"
        return f"{pending.redirect_uri}{separator}{urlencode(query)}"

    def _check_client_auth(self, data: dict[str, str], request: Request) -> _OAuthClient:
        client_id = data.get("client_id", "")
        client_secret = data.get("client_secret")
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                raw = base64.b64decode(auth_header[6:].strip(), validate=True).decode("utf-8")
                client_id, client_secret = raw.split(":", 1)
            except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
                raise OAuthInputError("client認証が正しくありません。") from exc
        client = self._client(client_id)
        if client.token_endpoint_auth_method == "none":
            if auth_header:
                raise OAuthInputError("このclientはclient_secretを使いません。")
            return client
        if not client_secret or not client.client_secret_hash:
            raise OAuthInputError("client_secretが必要です。")
        if not hmac.compare_digest(client.client_secret_hash, _hash_text(client_secret)):
            raise OAuthInputError("client認証が正しくありません。")
        return client

    def exchange(self, data: dict[str, str], request: Request) -> dict[str, Any]:
        client = self._check_client_auth(data, request)
        grant_type = data.get("grant_type", "")
        if grant_type == "authorization_code":
            code_value = data.get("code", "")
            redirect_uri = data.get("redirect_uri", "")
            verifier = data.get("code_verifier", "")
            with self._lock:
                self._purge_locked()
                code = self._codes.pop(_hash_text(code_value), None)
            if code is None or code.client_id != client.client_id:
                raise OAuthInputError("authorization codeが無効または期限切れです。")
            if code.redirect_uri != redirect_uri or not verifier:
                raise OAuthInputError("redirect_uriまたはPKCE検証値が正しくありません。")
            try:
                pkce_matches = hmac.compare_digest(code.code_challenge, _pkce_s256(verifier))
            except (UnicodeEncodeError, ValueError):
                pkce_matches = False
            if not pkce_matches:
                raise OAuthInputError("PKCE検証に失敗しました。")
            with self._lock:
                return self._issue_tokens_locked(
                    client.client_id,
                    code.subject,
                    code.scope,
                    code.resource,
                    "refresh_token" in client.grant_types,
                )

        if grant_type == "refresh_token":
            if "refresh_token" not in client.grant_types:
                raise OAuthInputError("このclientはrefresh_tokenに対応していません。")
            refresh_value = data.get("refresh_token", "")
            with self._lock:
                self._purge_locked()
                refresh = self._refresh_tokens.pop(_hash_text(refresh_value), None)
                if refresh is None or refresh.client_id != client.client_id:
                    raise OAuthInputError("refresh_tokenが無効または期限切れです。")
                return self._issue_tokens_locked(
                    client.client_id,
                    refresh.subject,
                    refresh.scope,
                    refresh.resource,
                    True,
                )

        raise OAuthInputError("grant_typeに対応していません。")

    def revoke(self, token: str) -> None:
        token_hash = _hash_text(token)
        with self._lock:
            self._access_tokens.pop(token_hash, None)
            self._refresh_tokens.pop(token_hash, None)

    def revoke_all(self) -> None:
        """Invalidate every in-memory OAuth client, grant, and pending request."""

        with self._lock:
            self._clients.clear()
            self._pending.clear()
            self._codes.clear()
            self._refresh_tokens.clear()
            self._access_tokens.clear()
            self._login_limiter = _LoginRateLimiter()

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        with self._lock:
            self._purge_locked()
            grant = self._access_tokens.get(_hash_text(token))
        if grant is None:
            return None
        return AccessToken(
            token=token,
            client_id=grant.client_id,
            scopes=grant.scope.split(),
            expires_at=int(grant.expires_at),
            resource=grant.resource,
            subject=grant.subject,
        )

    def _authorize_page(self, pending: _PendingAuthorization, client: _OAuthClient, error: str = "") -> HTMLResponse:
        safe_error = f'<p class="error">{html.escape(error)}</p>' if error else ""
        body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Sparkle MCP 認証</title>
<style>body{{font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem;line-height:1.6}}label{{display:block;margin:.8rem 0 .3rem}}input{{box-sizing:border-box;width:100%;padding:.65rem;border:1px solid #aaa;border-radius:.4rem}}button{{margin-top:1rem;padding:.65rem 1rem;border:0;border-radius:.4rem;background:#2563eb;color:#fff;cursor:pointer}}.error{{color:#b91c1c}}</style>
</head><body><h1>Sparkle MCP</h1><p>{html.escape(client.client_name)}が読み取り専用データへの接続を要求しています。</p>
{safe_error}<form method="post" action="/oauth/approve">
<input type="hidden" name="request_id" value="{html.escape(pending.request_id)}">
<input type="hidden" name="form_token" value="{html.escape(pending.form_token)}">
<label for="access_key">MCP公開用アクセスキー</label><input id="access_key" name="access_key" type="password" autocomplete="current-password" required>
<button type="submit">読み取り接続を許可</button></form></body></html>"""
        return HTMLResponse(body, headers=_no_store_headers())

    async def authorize(self, request: Request) -> Response:
        try:
            pending, client = self.authorization_request(request.query_params)
        except OAuthInputError as exc:
            return _json_error("invalid_request", str(exc))
        return self._authorize_page(pending, client)

    async def approve(self, request: Request) -> Response:
        try:
            data = await _read_form(request)
            request_id = data.get("request_id", "")
            form_token = data.get("form_token", "")
            access_key = data.get("access_key", "")
            with self._lock:
                pending = self._pending.get(request_id)
                client = self._clients.get(pending.client_id) if pending else None
            if pending is None or client is None:
                raise OAuthInputError("認証リクエストが期限切れです。最初から再試行してください。")
            attempt_key = request.client.host if request.client else "unknown"
            redirect_url = self.approve_access(request_id, form_token, access_key, attempt_key)
            return RedirectResponse(redirect_url, status_code=303, headers=_no_store_headers())
        except (OAuthInputError, ValueError) as exc:
            if "pending" in locals() and pending is not None and client is not None:
                return self._authorize_page(pending, client, str(exc))
            return _json_error("invalid_request", str(exc))

    async def register(self, request: Request) -> Response:
        try:
            body = await request.body()
            if len(body) > MAX_FORM_BODY * 2:
                raise OAuthInputError("client登録リクエストが大きすぎます。")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise OAuthInputError("client登録リクエストが正しくありません。")
            result = self.register_client(payload)
            return JSONResponse(result, status_code=201, headers=_no_store_headers())
        except (OAuthInputError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _json_error("invalid_client_metadata", str(exc))

    async def token(self, request: Request) -> Response:
        try:
            data = await _read_form(request)
            result = self.exchange(data, request)
            return JSONResponse(result, headers=_no_store_headers())
        except (OAuthInputError, ValueError) as exc:
            status = 401 if "client" in str(exc) else 400
            return _json_error("invalid_client" if status == 401 else "invalid_grant", str(exc), status)

    async def revoke_endpoint(self, request: Request) -> Response:
        try:
            data = await _read_form(request)
            self._check_client_auth(data, request)
            self.revoke(data.get("token", ""))
            return Response(status_code=200, headers=_no_store_headers())
        except (OAuthInputError, ValueError) as exc:
            return _json_error("invalid_request", str(exc))

    def authorization_server_metadata(self) -> JSONResponse:
        return JSONResponse(
            {
                "issuer": self.issuer_url,
                "authorization_endpoint": f"{self.issuer_url}/oauth/authorize",
                "token_endpoint": f"{self.issuer_url}/oauth/token",
                "registration_endpoint": f"{self.issuer_url}/oauth/register",
                "revocation_endpoint": f"{self.issuer_url}/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_post",
                    "client_secret_basic",
                ],
                "scopes_supported": [MCP_SCOPE],
            },
            headers=_no_store_headers(),
        )


class SparkleTokenVerifier(TokenVerifier):
    """Verify OAuth-issued tokens and an optional operator-provided token."""

    def __init__(self, oauth: RemoteMcpOAuth, static_token: Optional[str]) -> None:
        self.oauth = oauth
        self._static_token_hash = _hash_text(static_token) if static_token else None

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if self._static_token_hash and hmac.compare_digest(self._static_token_hash, _hash_text(token)):
            return AccessToken(
                token=token,
                client_id="sparkle-static-token",
                scopes=[MCP_SCOPE],
                subject="local-user",
                resource=self.oauth.resource_url,
            )
        return await self.oauth.verify_token(token)


class RemoteMcpRuntime:
    """Reusable MCP ASGI runtime for a standalone process or RemoteGateway."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        auth_store: Optional[AuthStore] = None,
        host: str = "127.0.0.1",
        port: int = 8002,
        public_url: Optional[str] = None,
        static_token: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.public_url = _normalize_public_url(
            public_url or os.environ.get("SPARKLE_MCP_PUBLIC_URL"),
            f"http://{host}:{self.port}{MCP_PATH}",
        )
        if static_token is not None and static_token and len(static_token) < 16:
            raise ValueError("SPARKLE_MCP_TOKENは16文字以上で指定してください。")
        self.issuer_url = _issuer_from_resource(self.public_url)
        self.auth_store = auth_store or get_mcp_auth_store()
        self.oauth = RemoteMcpOAuth(self.auth_store, self.issuer_url, self.public_url)
        self.token_verifier = SparkleTokenVerifier(self.oauth, static_token)
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer_url),
            resource_server_url=AnyHttpUrl(self.public_url),
            required_scopes=[MCP_SCOPE],
        )
        self.server = build_server(db_path, token_verifier=self.token_verifier, auth=auth)
        security = self._transport_security()
        self.mcp_app = self.server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            json_response=True,
            stateless_http=True,
            transport_security=security,
            host=host,
        )
        self.app = Starlette(
            routes=[
                Route("/oauth/authorize", self.oauth.authorize, methods=["GET"]),
                Route("/oauth/approve", self.oauth.approve, methods=["POST"]),
                Route("/oauth/token", self.oauth.token, methods=["POST"]),
                Route("/oauth/register", self.oauth.register, methods=["POST"]),
                Route("/oauth/revoke", self.oauth.revoke_endpoint, methods=["POST"]),
                Route(
                    "/.well-known/oauth-authorization-server",
                    lambda request: self.oauth.authorization_server_metadata(),
                    methods=["GET"],
                ),
                Mount("/", app=self.mcp_app),
            ],
            lifespan=self._app_lifespan,
        )

    def _transport_security(self) -> TransportSecuritySettings:
        parsed = urlsplit(self.public_url)
        allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        allowed_origins = [
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ]
        if parsed.netloc:
            allowed_hosts.append(parsed.netloc)
            allowed_origins.append(f"{parsed.scheme}://{parsed.netloc}")
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            allowed_hosts.append(f"{self.host}:*")
            allowed_origins.append(f"http://{self.host}:*")
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    @asynccontextmanager
    async def lifespan_context(self) -> AsyncIterator[None]:
        async with self.server.session_manager.run():
            yield

    @asynccontextmanager
    async def _app_lifespan(self, app: Starlette) -> AsyncIterator[None]:
        del app
        async with self.lifespan_context():
            yield

    def handles_path(self, path: str) -> bool:
        return path in OAUTH_PATHS

    def revoke_all(self) -> None:
        """Invalidate OAuth state without affecting Web sessions."""

        self.oauth.revoke_all()


def build_remote_mcp_runtime(
    db_path: Optional[str] = None,
    auth_store: Optional[AuthStore] = None,
    host: str = "127.0.0.1",
    port: int = 8002,
    public_url: Optional[str] = None,
    static_token: Optional[str] = None,
) -> RemoteMcpRuntime:
    """Build the Remote MCP runtime without starting a process."""

    return RemoteMcpRuntime(
        db_path=db_path,
        auth_store=auth_store,
        host=host,
        port=port,
        public_url=public_url,
        static_token=static_token,
    )


__all__ = [
    "MCP_PATH",
    "MCP_SCOPE",
    "OAUTH_PATHS",
    "RemoteMcpRuntime",
    "build_remote_mcp_runtime",
]
