"""Host-mediated, per-plugin OAuth connections.

OAuth tokens never leave Sparkle. A plugin can start a PKCE flow and make
authenticated requests only to the API origin declared for that connection.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import urllib.parse
import uuid
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import jwt

from plugin_network import (
    OAUTH_REQUEST_TIMEOUT_SECONDS,
    PluginNetworkError,
    _public_address,
    perform_plugin_network_request,
)


LOGGER = logging.getLogger(__name__)
MAX_PROFILE_BYTES = 128 * 1024
MAX_OAUTH_RESPONSE_BYTES = 1024 * 1024
# Keep each Credential Manager blob below its size limit, including UTF-16 storage.
MAX_SECRET_CHUNK_CHARS = 1000
MAX_SECRET_CHUNKS = 20
CALLBACK_TIMEOUT_SECONDS = 300
TOKEN_REFRESH_MARGIN_SECONDS = 90
CONNECTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_AUTH_PARAMS = {
    "client_id", "response_type", "redirect_uri", "scope", "state", "nonce",
    "code_challenge", "code_challenge_method", "resource", "ext_agent_host_id",
    "agent_name_hint",
}


class PluginOAuthError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class _PendingAuthorization:
    plugin_id: str
    connection_id: str
    profile: dict[str, Any]
    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    client_id: str
    server: HTTPServer


_lock = threading.RLock()
_refresh_lock = threading.Lock()
_pending: dict[tuple[str, str], _PendingAuthorization] = {}
_flow_status: dict[tuple[str, str], dict[str, Any]] = {}


def _secret_store():
    from project_assistant import _get_secret_store

    return _get_secret_store()


def _plugin_root(directory: Path | None = None) -> Path:
    from plugin_manager import _plugin_data_root

    return _plugin_data_root(directory)


def _valid_connection_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 64
        and bool(CONNECTION_ID_PATTERN.fullmatch(value))
    )


def _profile_path(plugin_id: str, directory: Path | None = None) -> Path:
    from plugin_manager import _valid_plugin_id

    if not _valid_plugin_id(plugin_id):
        raise PluginOAuthError(400, "プラグインIDが正しくありません。")
    root = _plugin_root(directory)
    plugin_root = root / plugin_id
    if plugin_root.is_symlink() or (plugin_root.exists() and plugin_root.resolve().parent != root):
        raise PluginOAuthError(400, "プラグインの接続データ保存先を安全に確認できません。")
    plugin_root.mkdir(parents=True, exist_ok=True)
    path = plugin_root / "oauth-connections.json"
    if path.is_symlink() or (path.exists() and path.resolve().parent != plugin_root.resolve()):
        raise PluginOAuthError(400, "プラグインの接続データ保存先を安全に確認できません。")
    return path


def _host_id_path(plugin_id: str, directory: Path | None = None) -> Path:
    path = _profile_path(plugin_id, directory).with_name("oauth-host-id.txt")
    plugin_root = path.parent
    if path.is_symlink() or (path.exists() and path.resolve().parent != plugin_root.resolve()):
        raise PluginOAuthError(400, "プラグインのOAuthホストIDを安全に確認できません。")
    return path


def _valid_host_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("urn:uuid:"):
        return False
    try:
        return str(uuid.UUID(value.removeprefix("urn:uuid:"))) == value.removeprefix("urn:uuid:")
    except (ValueError, AttributeError):
        return False


def _persistent_host_id(
    plugin_id: str,
    profiles: dict[str, dict[str, Any]],
    directory: Path | None = None,
) -> str:
    with _lock:
        path = _host_id_path(plugin_id, directory)
        if path.exists():
            try:
                value = path.read_text(encoding="ascii").strip()
            except (OSError, UnicodeError) as exc:
                raise PluginOAuthError(500, "OAuthホストIDを読み取れません。") from exc
            if not _valid_host_id(value):
                raise PluginOAuthError(500, "OAuthホストIDの形式が正しくありません。")
            return value

        value = next(
            (profile.get("host_id") for profile in profiles.values() if _valid_host_id(profile.get("host_id"))),
            f"urn:uuid:{uuid.uuid4()}",
        )
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(value, encoding="ascii")
            temporary.replace(path)
        except OSError as exc:
            raise PluginOAuthError(500, "OAuthホストIDを保存できません。") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return value


def _read_profiles(plugin_id: str, directory: Path | None = None) -> dict[str, dict[str, Any]]:
    with _lock:
        path = _profile_path(plugin_id, directory)
        if not path.exists():
            return {}
        try:
            if path.stat().st_size > MAX_PROFILE_BYTES:
                raise PluginOAuthError(400, "プラグインのOAuth接続データが上限を超えています。")
            data = json.loads(path.read_text(encoding="utf-8"))
        except PluginOAuthError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PluginOAuthError(500, "プラグインのOAuth接続データを読み取れません。") from exc
        if not isinstance(data, dict):
            raise PluginOAuthError(500, "プラグインのOAuth接続データが正しくありません。")
        return {key: value for key, value in data.items() if _valid_connection_id(key) and isinstance(value, dict)}


def _write_profiles(plugin_id: str, profiles: dict[str, dict[str, Any]], directory: Path | None = None) -> None:
    with _lock:
        path = _profile_path(plugin_id, directory)
        encoded = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
        raw = encoded.encode("utf-8")
        if len(raw) > MAX_PROFILE_BYTES:
            raise PluginOAuthError(413, "プラグインのOAuth接続データが上限を超えています。")
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_bytes(raw)
            temp.replace(path)
        except OSError as exc:
            raise PluginOAuthError(500, "プラグインのOAuth接続データを保存できません。") from exc
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _key(plugin_id: str, connection_id: str, part: str) -> str:
    return f"plugin-oauth-{plugin_id}-{connection_id}-{part}"


def _secret_chunk_count_key(key: str) -> str:
    return f"{key}-chunks"


def _secret_chunk_key(key: str, index: int) -> str:
    return key if index == 0 else f"{key}-chunk-{index}"


def _get_secret(plugin_id: str, connection_id: str, part: str, store: Any | None = None) -> str | None:
    credential_store = store or _secret_store()
    key = _key(plugin_id, connection_id, part)
    raw_count = credential_store.get(_secret_chunk_count_key(key))
    if raw_count is None:
        value = credential_store.get(key)
        return value if isinstance(value, str) and value else None
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise PluginOAuthError(500, "保存されたOAuth資格情報の形式が正しくありません。") from exc
    if not 2 <= count <= MAX_SECRET_CHUNKS:
        raise PluginOAuthError(500, "保存されたOAuth資格情報の形式が正しくありません。")
    chunks = [credential_store.get(_secret_chunk_key(key, index)) for index in range(count)]
    if any(not isinstance(chunk, str) or not chunk for chunk in chunks):
        raise PluginOAuthError(500, "保存されたOAuth資格情報を完全に読み出せませんでした。")
    return "".join(chunks)


def _delete_secret(key: str, store: Any) -> None:
    raw_count = store.get(_secret_chunk_count_key(key))
    if raw_count is None:
        chunk_count = 1
    else:
        try:
            chunk_count = int(raw_count)
        except (TypeError, ValueError):
            chunk_count = MAX_SECRET_CHUNKS
        if not 2 <= chunk_count <= MAX_SECRET_CHUNKS:
            chunk_count = MAX_SECRET_CHUNKS
    store.delete(_secret_chunk_count_key(key))
    for index in range(chunk_count):
        store.delete(_secret_chunk_key(key, index))


def _set_secret(plugin_id: str, connection_id: str, part: str, value: str, store: Any | None = None) -> None:
    credential_store = store or _secret_store()
    key = _key(plugin_id, connection_id, part)
    raw_previous_count = credential_store.get(_secret_chunk_count_key(key))
    try:
        previous_count = int(raw_previous_count) if raw_previous_count is not None else 1
    except (TypeError, ValueError):
        previous_count = MAX_SECRET_CHUNKS
    previous_count = max(1, min(previous_count, MAX_SECRET_CHUNKS))
    chunks = [value[index:index + MAX_SECRET_CHUNK_CHARS] for index in range(0, len(value), MAX_SECRET_CHUNK_CHARS)] or [""]
    if len(chunks) > MAX_SECRET_CHUNKS:
        raise PluginOAuthError(413, "OAuth資格情報が保存上限を超えています。")
    for index, chunk in enumerate(chunks):
        credential_store.set(_secret_chunk_key(key, index), chunk)
    if len(chunks) > 1:
        credential_store.set(_secret_chunk_count_key(key), str(len(chunks)))
    else:
        credential_store.delete(_secret_chunk_count_key(key))
    for index in range(len(chunks), previous_count):
        credential_store.delete(_secret_chunk_key(key, index))


def _delete_secrets(plugin_id: str, connection_id: str, store: Any | None = None) -> None:
    credential_store = store or _secret_store()
    for part in ("access", "refresh", "expires", "scopes"):
        _delete_secret(_key(plugin_id, connection_id, part), credential_store)


def _validate_https_url(value: Any, *, allow_path: bool = True, check_public: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise PluginOAuthError(422, "OAuth接続先URLが正しくありません。")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port or 443
    except ValueError as exc:
        raise PluginOAuthError(422, "OAuth接続先URLが正しくありません。") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or port != 443
        or (not allow_path and parsed.path not in {"", "/"})
    ):
        raise PluginOAuthError(422, "OAuth接続先はクエリのない公開HTTPS URL（443番）にしてください。")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if check_public:
            _public_address(host, 443)
    except (UnicodeError, PluginNetworkError) as exc:
        raise PluginOAuthError(422, "OAuth接続先には公開ホストを指定してください。") from exc
    path = urllib.parse.quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    return f"https://{host}{path}"


def _normalize_origin(value: Any) -> str:
    normalized = _validate_https_url(value, allow_path=False)
    return normalized.rstrip("/")


def _validate_config(raw: Any, plugin_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PluginOAuthError(422, "OAuth接続の設定が正しくありません。")
    connection_id = raw.get("connection_id")
    if not _valid_connection_id(connection_id):
        raise PluginOAuthError(422, "connection_idは小文字英数字とハイフンで指定してください。")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise PluginOAuthError(422, "OAuth接続名が正しくありません。")
    agent_name_hint = raw.get("agent_name_hint", "Sparkle")
    if (
        not isinstance(agent_name_hint, str)
        or not agent_name_hint.strip()
        or len(agent_name_hint.strip()) > 100
        or any(ord(char) < 32 for char in agent_name_hint)
    ):
        raise PluginOAuthError(422, "agent_name_hintが正しくありません。")
    client_id = raw.get("client_id")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or len(client_id) > 256
        or any(ord(char) < 33 or ord(char) > 126 for char in client_id)
    ):
        raise PluginOAuthError(422, "OAuthのclient_idが正しくありません。")
    dynamic_registration = raw.get("dynamic_registration", False)
    if not isinstance(dynamic_registration, bool):
        raise PluginOAuthError(422, "dynamic_registrationはtrueまたはfalseで指定してください。")
    if dynamic_registration and client_id != "dynamic_agent_client":
        raise PluginOAuthError(422, "動的登録ではclient_idにdynamic_agent_clientを指定してください。")
    scopes = raw.get("scopes")
    if (
        not isinstance(scopes, list)
        or not scopes
        or len(scopes) > 32
        or any(not isinstance(scope, str) or not scope or len(scope) > 128 or any(ch.isspace() for ch in scope) for scope in scopes)
    ):
        raise PluginOAuthError(422, "OAuth scopesは1〜32個の空白を含まない文字列で指定してください。")
    if len(set(scopes)) != len(scopes):
        raise PluginOAuthError(422, "OAuth scopesに重複があります。")
    params = raw.get("authorization_params", {})
    if not isinstance(params, dict) or len(params) > 16:
        raise PluginOAuthError(422, "authorization_paramsが正しくありません。")
    clean_params: dict[str, str] = {}
    for key, value in params.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.replace("_", "").isalnum()
            or key.lower() in RESERVED_AUTH_PARAMS
            or not isinstance(value, str)
            or len(value) > 256
            or any(ord(char) < 32 for char in value)
        ):
            raise PluginOAuthError(422, "authorization_paramsに使用できない項目があります。")
        clean_params[key] = value
    token_params = raw.get("token_params", {})
    if not isinstance(token_params, dict) or len(token_params) > 16:
        raise PluginOAuthError(422, "token_paramsが正しくありません。")
    clean_token_params: dict[str, str] = {}
    for key, value in token_params.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.replace("_", "").isalnum()
            or key.lower() in {"grant_type", "client_id", "code", "code_verifier", "redirect_uri", "refresh_token", "access_token"}
            or not isinstance(value, str)
            or len(value) > 256
            or any(ord(char) < 32 for char in value)
        ):
            raise PluginOAuthError(422, "token_paramsに使用できない項目があります。")
        clean_token_params[key] = value
    issuer = raw.get("issuer")
    jwks_url = raw.get("jwks_url")
    if "openid" in scopes and (not issuer or not jwks_url):
        raise PluginOAuthError(422, "openidを使う場合はissuerとjwks_urlが必要です。")
    normalized_issuer = _validate_https_url(issuer, allow_path=True) if issuer else ""
    normalized_jwks = _validate_https_url(jwks_url, allow_path=True) if jwks_url else ""
    resource = raw.get("resource")
    normalized_resource = _validate_https_url(resource, allow_path=True) if resource else ""
    return {
        "connection_id": connection_id,
        "name": name.strip(),
        "agent_name_hint": agent_name_hint.strip(),
        "authorization_url": _validate_https_url(raw.get("authorization_url"), allow_path=True),
        "token_url": _validate_https_url(raw.get("token_url"), allow_path=True),
        "client_id": client_id,
        "dynamic_registration": dynamic_registration,
        "scopes": scopes,
        "resource": normalized_resource,
        "api_origin": _normalize_origin(raw.get("api_origin")),
        "issuer": normalized_issuer,
        "jwks_url": normalized_jwks,
        "authorization_params": clean_params,
        "token_params": clean_token_params,
        "plugin_id": plugin_id,
    }


def _same_auth_config(existing: dict[str, Any], requested: dict[str, Any]) -> bool:
    fields = (
        "name", "authorization_url", "token_url", "dynamic_registration", "resource",
        "api_origin", "issuer", "jwks_url", "authorization_params", "token_params",
    )
    if any(existing.get(field) != requested.get(field) for field in fields):
        return False
    if existing.get("scopes") != requested.get("scopes"):
        return False
    if existing.get("agent_name_hint", "Sparkle") != requested["agent_name_hint"]:
        return False
    if requested["dynamic_registration"]:
        return requested["client_id"] == "dynamic_agent_client" and (
            not existing.get("registered_client_id") or isinstance(existing.get("registered_client_id"), str)
        )
    return existing.get("registered_client_id", requested["client_id"]) == requested["client_id"]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _chatgpt_account_id_from_access_token(access_token: str) -> str | None:
    """Read the optional ChatGPT account claim without returning token data to plugins."""
    if not isinstance(access_token, str) or len(access_token) > 16_384:
        return None
    parts = access_token.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    try:
        payload = base64.b64decode(
            parts[1] + "=" * (-len(parts[1]) % 4),
            altchars=b"-_",
            validate=True,
        )
        claims = json.loads(payload.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(claims, dict):
        return None
    auth_claim = claims.get("https://api.openai.com/auth")
    account_id = auth_claim.get("chatgpt_account_id") if isinstance(auth_claim, dict) else None
    if not isinstance(account_id, str):
        account_id = claims.get("chatgpt_account_id")
    if (
        not isinstance(account_id, str)
        or not account_id
        or len(account_id) > 256
        or not account_id.isascii()
        or any(ord(char) < 33 or ord(char) > 126 for char in account_id)
    ):
        return None
    return account_id


def _apply_access_token_headers(headers: dict[str, Any], access_token: str, origin: str) -> None:
    for header in list(headers):
        if isinstance(header, str) and header.lower() in {"authorization", "chatgpt-account-id"}:
            del headers[header]
    headers["Authorization"] = f"Bearer {access_token}"
    if origin == "https://chatgpt.com":
        account_id = _chatgpt_account_id_from_access_token(access_token)
        if account_id:
            headers["ChatGPT-Account-ID"] = account_id


def _status_value(plugin_id: str, connection_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    key = (plugin_id, connection_id)
    with _lock:
        flow = dict(_flow_status.get(key, {}))
        pending = key in _pending
    try:
        connected = bool(_get_secret(plugin_id, connection_id, "access"))
    except Exception:
        connected = False
    return {
        "connection_id": connection_id,
        "name": profile.get("name", connection_id),
        "connected": connected,
        "pending": pending,
        "api_origin": profile.get("api_origin", ""),
        "scopes": list(profile.get("granted_scopes", [])),
        "message": flow.get("message", "接続済みです。" if connected else "未接続です。"),
    }


def get_connection_status(plugin_id: str, connection_id: str, directory: Path | None = None) -> dict[str, Any]:
    if not _valid_connection_id(connection_id):
        raise PluginOAuthError(422, "connection_idが正しくありません。")
    profile = _read_profiles(plugin_id, directory).get(connection_id)
    if not profile:
        return {"connection_id": connection_id, "name": connection_id, "connected": False, "pending": False, "api_origin": "", "scopes": [], "message": "未接続です。"}
    return _status_value(plugin_id, connection_id, profile)


def _authorization_url(profile: dict[str, Any], client_id: str, pending: _PendingAuthorization) -> str:
    params = dict(profile.get("authorization_params", {}))
    params.update({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": pending.redirect_uri,
        "scope": " ".join(profile["scopes"]),
        "state": pending.state,
        "code_challenge_method": "S256",
        "code_challenge": _b64url(hashlib.sha256(pending.verifier.encode("ascii")).digest()),
    })
    if "openid" in profile["scopes"]:
        params["nonce"] = pending.nonce
    if profile.get("resource"):
        params["resource"] = profile["resource"]
    if profile.get("dynamic_registration") and client_id == "dynamic_agent_client":
        params["ext_agent_host_id"] = profile["host_id"]
        params["agent_name_hint"] = profile.get("agent_name_hint", "Sparkle")
    query = urllib.parse.urlencode(params)
    return profile["authorization_url"] + "?" + query


def start_connection(plugin_id: str, raw_config: Any, directory: Path | None = None) -> dict[str, Any]:
    reauthorize = raw_config.get("reauthorize", False) if isinstance(raw_config, dict) else False
    if not isinstance(reauthorize, bool):
        raise PluginOAuthError(422, "reauthorizeはtrueまたはfalseで指定してください。")
    profile_request = _validate_config(raw_config, plugin_id)
    connection_id = profile_request["connection_id"]
    key = (plugin_id, connection_id)
    profiles = _read_profiles(plugin_id, directory)
    existing = profiles.get(connection_id)
    if existing and not _same_auth_config(existing, profile_request):
        raise PluginOAuthError(409, "この接続IDは別のOAuth設定です。プラグイン内で接続を解除してから再設定してください。")
    if existing and not reauthorize and _get_secret(plugin_id, connection_id, "access"):
        return _status_value(plugin_id, connection_id, existing)
    with _lock:
        if key in _pending:
            raise PluginOAuthError(409, "このプラグインのOAuth接続はすでに進行中です。")

    profile = dict(existing or profile_request)
    profile.update({field: profile_request[field] for field in profile_request})
    profile["host_id"] = _persistent_host_id(plugin_id, profiles, directory)
    if not profile.get("dynamic_registration"):
        profile["registered_client_id"] = profile_request["client_id"]
    profiles[connection_id] = profile
    _write_profiles(plugin_id, profiles, directory)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    manager: dict[str, _PendingAuthorization] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _respond(self, status: int, message: str) -> None:
            body = f"<!doctype html><meta charset='utf-8'><title>Sparkle OAuth</title><p>{message}</p>".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.client_address[0] not in {"127.0.0.1", "::1"} or len(self.path) > 8_192:
                self._respond(400, "ローカルの認証コールバックを確認できませんでした。")
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/auth/callback":
                self._respond(404, "コールバック先が正しくありません。")
                return
            try:
                query = urllib.parse.parse_qs(parsed.query, max_num_fields=16)
            except ValueError:
                self._respond(400, "OAuthコールバックを読み取れませんでした。")
                return
            values = {name: items[0] for name, items in query.items() if items}
            if not secrets.compare_digest(values.get("state", ""), state):
                _set_flow_status(key, pending=False, message="OAuthのstate検証に失敗しました。")
                self._respond(400, "認証結果を確認できません。Sparkleのプラグイン画面から再試行してください。")
                return
            if values.get("error"):
                _set_flow_status(key, pending=False, message="OAuth接続がキャンセルされました。")
                self._respond(200, "認証はキャンセルされました。Sparkleへ戻ってください。")
                return
            code = values.get("code", "").strip()
            callback_client_id = values.get("client_id", "").strip()
            if not code or len(code) > 8_192:
                _set_flow_status(key, pending=False, message="OAuth認証コードを確認できませんでした。")
                self._respond(400, "認証結果を確認できません。Sparkleへ戻って再試行してください。")
                return
            selected_client_id = _select_callback_client_id(
                profile,
                pending_client_id=manager["pending"].client_id,
                callback_client_id=callback_client_id,
            )
            if not selected_client_id or len(selected_client_id) > 256:
                _set_flow_status(key, pending=False, message="OAuth client_idを確認できませんでした。")
                self._respond(400, "認証結果を確認できません。Sparkleへ戻って再試行してください。")
                return
            _set_flow_status(key, pending=True, message="OAuth接続を検証しています…")
            self._respond(200, "接続を確認しています。Sparkleへ戻ってください。")
            pending = manager["pending"]
            threading.Thread(
                target=_complete_authorization,
                args=(pending, code, selected_client_id, directory),
                name="SparklePluginOAuthExchange",
                daemon=True,
            ).start()

    try:
        server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    except OSError as exc:
        raise PluginOAuthError(503, "OAuthのローカルコールバック用ポートを開けません。") from exc
    server.timeout = 0.5
    redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
    pending = _PendingAuthorization(
        plugin_id=plugin_id,
        connection_id=connection_id,
        profile=profile,
        state=state,
        nonce=nonce,
        verifier=verifier,
        redirect_uri=redirect_uri,
        client_id=profile.get("registered_client_id") or profile["client_id"],
        server=server,
    )
    manager["pending"] = pending
    with _lock:
        _pending[key] = pending
        _flow_status[key] = {"message": "ブラウザーでアカウントへの接続を許可してください。"}
    threading.Thread(target=_serve_callback, args=(pending,), name="SparklePluginOAuthCallback", daemon=True).start()
    try:
        opened = webbrowser.open(_authorization_url(profile, pending.client_id, pending), new=2, autoraise=True)
    except Exception as exc:
        opened = False
        LOGGER.warning("Plugin OAuth browser launch failed: %s", type(exc).__name__)
    if not opened:
        with _lock:
            _pending.pop(key, None)
        try:
            server.server_close()
        except OSError:
            pass
        _set_flow_status(key, pending=False, message="既定のブラウザーを開けませんでした。")
        raise PluginOAuthError(503, "既定のブラウザーを開けませんでした。")
    return _status_value(plugin_id, connection_id, profile)


def _set_flow_status(key: tuple[str, str], *, pending: bool, message: str) -> None:
    with _lock:
        _flow_status[key] = {"message": message}
        if not pending:
            _pending.pop(key, None)


def _select_callback_client_id(
    profile: dict[str, Any],
    *,
    pending_client_id: str,
    callback_client_id: str,
) -> str:
    """Accept an issued ID on first dynamic registration and retain it later."""
    if profile.get("dynamic_registration") and pending_client_id == "dynamic_agent_client":
        if (
            callback_client_id
            and callback_client_id != "dynamic_agent_client"
            and len(callback_client_id) <= 256
            and all(33 <= ord(char) <= 126 for char in callback_client_id)
        ):
            return callback_client_id
        return ""
    if callback_client_id and callback_client_id != pending_client_id:
        return ""
    return pending_client_id


def _serve_callback(pending: _PendingAuthorization) -> None:
    key = (pending.plugin_id, pending.connection_id)
    deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            with _lock:
                if _pending.get(key) is not pending:
                    break
            pending.server.timeout = min(0.5, max(0.05, deadline - time.monotonic()))
            pending.server.handle_request()
        else:
            _set_flow_status(key, pending=False, message="OAuth認証がタイムアウトしました。")
    except Exception as exc:  # pragma: no cover - socket/runtime failure
        LOGGER.warning("Plugin OAuth callback listener failed: %s", type(exc).__name__)
        _set_flow_status(key, pending=False, message="OAuthコールバックを受け付けられませんでした。")
    finally:
        try:
            pending.server.server_close()
        except OSError:
            pass
        with _lock:
            if _pending.get(key) is pending:
                _pending.pop(key, None)


def _request_json(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        response = perform_plugin_network_request(url=url, method=method, headers=headers or {}, body=body)
    except PluginNetworkError as exc:
        raise PluginOAuthError(502, "OAuthサーバーへ安全に接続できませんでした。") from exc
    if len(response.get("body", "").encode("utf-8")) > MAX_OAUTH_RESPONSE_BYTES:
        raise PluginOAuthError(502, "OAuthサーバーの応答が大きすぎます。")
    try:
        parsed = json.loads(response.get("body", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise PluginOAuthError(502, "OAuthサーバーのJSON応答を読み取れません。") from exc
    if not isinstance(parsed, dict):
        raise PluginOAuthError(502, "OAuthサーバーの応答形式が正しくありません。")
    return int(response.get("status", 0)), parsed


def _validate_id_token(id_token: str, *, profile: dict[str, Any], client_id: str, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
        response_status, jwks = _request_json(profile["jwks_url"])
        if response_status != 200 or not isinstance(jwks.get("keys"), list):
            raise ValueError("JWKS unavailable")
        match = next((item for item in jwks["keys"] if isinstance(item, dict) and item.get("kid") == header.get("kid")), None)
        if not match:
            raise ValueError("signing key unavailable")
        signing_key = jwt.PyJWK.from_dict(match, algorithm=header.get("alg")).key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=[header.get("alg")],
            audience=client_id,
            issuer=profile["issuer"],
            options={"require": ["exp", "iss", "aud", "sub", "nonce"]},
            leeway=30,
        )
    except Exception as exc:
        raise PluginOAuthError(401, "OAuthのIDトークンを検証できませんでした。") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise PluginOAuthError(401, "OAuthのnonce検証に失敗しました。")
    return claims


def _post_token_form(profile: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    values = dict(profile.get("token_params", {}))
    values.update(fields)
    status, result = _request_json(
        profile["token_url"],
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "Sparkle/1 PluginOAuth"},
        body=urllib.parse.urlencode(values),
    )
    if status != 200:
        error = str(result.get("error", ""))
        message = "OAuth認証コードまたは更新トークンの期限が切れました。" if error == "invalid_grant" else "OAuthトークンの取得を拒否されました。"
        raise PluginOAuthError(401 if error == "invalid_grant" else 502, message)
    if not isinstance(result.get("access_token"), str) or not result["access_token"]:
        raise PluginOAuthError(502, "OAuth応答にaccess_tokenがありません。")
    return result


def _save_tokens(
    plugin_id: str,
    connection_id: str,
    token_data: dict[str, Any],
    profile: dict[str, Any],
    client_id: str,
    nonce: str,
    *,
    validate_id_token: bool = True,
) -> None:
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    if not isinstance(access_token, str) or len(access_token) > 16_384:
        raise PluginOAuthError(502, "OAuth access_tokenの形式が正しくありません。")
    if refresh_token is not None and (not isinstance(refresh_token, str) or len(refresh_token) > 16_384):
        raise PluginOAuthError(502, "OAuth refresh_tokenの形式が正しくありません。")
    token_type = str(token_data.get("token_type", "Bearer"))
    if token_type.lower() != "bearer":
        raise PluginOAuthError(502, "SparkleはBearerトークン形式のOAuth接続に対応しています。")
    id_token = token_data.get("id_token")
    if validate_id_token and "openid" in profile.get("scopes", []) and id_token is None:
        raise PluginOAuthError(401, "OAuth応答に必要なIDトークンがありません。")
    if id_token is not None and validate_id_token:
        if not isinstance(id_token, str) or not profile.get("issuer") or not profile.get("jwks_url"):
            raise PluginOAuthError(401, "IDトークンを検証するOAuth設定がありません。")
        _validate_id_token(id_token, profile=profile, client_id=client_id, nonce=nonce)
    granted_scopes = token_data.get("scope")
    if isinstance(granted_scopes, str):
        scopes = sorted(set(granted_scopes.split()))
    else:
        scopes = profile.get("scopes", [])
    try:
        expires_in = max(0, min(int(token_data.get("expires_in", 0)), 31_536_000))
    except (TypeError, ValueError):
        expires_in = 0
    store = _secret_store()
    parts = ("access", "refresh", "expires", "scopes")
    previous = {part: _get_secret(plugin_id, connection_id, part, store) for part in parts}
    replacements = {
        "access": access_token,
        "refresh": refresh_token,
        "expires": str(int(time.time()) + expires_in),
        "scopes": " ".join(scopes),
    }
    try:
        for part, value in replacements.items():
            if value:
                _set_secret(plugin_id, connection_id, part, value, store)
            else:
                _delete_secret(_key(plugin_id, connection_id, part), store)
    except Exception:
        for part, value in previous.items():
            try:
                if value:
                    _set_secret(plugin_id, connection_id, part, value, store)
                else:
                    _delete_secret(_key(plugin_id, connection_id, part), store)
            except Exception:
                LOGGER.error("Plugin OAuth token rollback failed")
        raise
    profile["registered_client_id"] = client_id
    profile["granted_scopes"] = scopes


def _complete_authorization(pending: _PendingAuthorization, code: str, client_id: str, directory: Path | None) -> None:
    plugin_id = pending.plugin_id
    connection_id = pending.connection_id
    key = (plugin_id, connection_id)
    profile = pending.profile
    fields = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": pending.verifier,
        "redirect_uri": pending.redirect_uri,
    }
    if profile.get("resource"):
        fields["resource"] = profile["resource"]
    stage = "トークン交換"
    try:
        with _lock:
            if _pending.get(key) is not pending:
                return
        token_data = _post_token_form(profile, fields)
        with _lock:
            if _pending.get(key) is not pending:
                return
            stage = "安全な資格情報保存"
            _save_tokens(plugin_id, connection_id, token_data, profile, client_id, pending.nonce)
            stage = "接続プロフィール保存"
            profiles = _read_profiles(plugin_id, directory)
            profiles[connection_id] = profile
            _write_profiles(plugin_id, profiles, directory)
            _set_flow_status(key, pending=False, message="外部アカウントに接続しました。")
    except PluginOAuthError as exc:
        LOGGER.info("Plugin OAuth exchange rejected: %s", exc.status_code)
        with _lock:
            if _pending.get(key) is pending:
                _set_flow_status(key, pending=False, message=exc.message)
        return
    except Exception as exc:
        LOGGER.warning("Plugin OAuth authorization failed during %s: %s", stage, type(exc).__name__)
        message = "OAuth接続を保存できませんでした。"
        try:
            from project_assistant import ProjectAssistantError

            if isinstance(exc, ProjectAssistantError):
                message = exc.message
        except ImportError:
            pass
        with _lock:
            if _pending.get(key) is pending:
                _set_flow_status(key, pending=False, message=message)
        return


def _refresh(
    plugin_id: str,
    connection_id: str,
    profile: dict[str, Any],
    *,
    force: bool = False,
    directory: Path | None = None,
) -> str:
    with _refresh_lock:
        store = _secret_store()
        access = _get_secret(plugin_id, connection_id, "access", store)
        refresh_token = _get_secret(plugin_id, connection_id, "refresh", store)
        expires = _get_secret(plugin_id, connection_id, "expires", store)
        try:
            expires_at = int(expires or "0")
        except ValueError:
            expires_at = 0
        if access and (not force and (not expires_at or expires_at - TOKEN_REFRESH_MARGIN_SECONDS > time.time())):
            return access
        if not refresh_token:
            raise PluginOAuthError(401, "OAuth接続の期限が切れています。プラグインから再接続してください。")
        client_id = profile.get("registered_client_id") or profile.get("client_id")
        fields = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
        if profile.get("resource"):
            fields["resource"] = profile["resource"]
        token_data = _post_token_form(profile, fields)
        _save_tokens(plugin_id, connection_id, token_data, profile, client_id, "", validate_id_token=False)
        profiles = _read_profiles(plugin_id, directory)
        profiles[connection_id] = profile
        _write_profiles(plugin_id, profiles, directory)
        return str(token_data["access_token"])


def authenticated_request(
    plugin_id: str,
    connection_id: str,
    *,
    url: str,
    method: str = "GET",
    headers: Any = None,
    body: str | None = None,
    directory: Path | None = None,
) -> dict[str, Any]:
    profiles = _read_profiles(plugin_id, directory)
    profile = profiles.get(connection_id)
    if not profile:
        raise PluginOAuthError(404, "OAuth接続が見つかりません。")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or 443
        origin = _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
    except (ValueError, PluginOAuthError) as exc:
        raise PluginOAuthError(422, "OAuthリクエストURLが正しくありません。") from exc
    if origin != profile.get("api_origin") or parsed.scheme.lower() != "https" or port != 443:
        raise PluginOAuthError(403, "OAuth接続は登録済みのAPIホストにだけ使用できます。")
    token = _refresh(plugin_id, connection_id, profile, directory=directory)
    safe_headers = dict(headers) if isinstance(headers, dict) else {}
    _apply_access_token_headers(safe_headers, token, origin)
    try:
        response = perform_plugin_network_request(
            url=url,
            method=method,
            headers=safe_headers,
            body=body,
            timeout_seconds=OAUTH_REQUEST_TIMEOUT_SECONDS,
        )
        if int(response.get("status", 0)) == 401 and _get_secret(plugin_id, connection_id, "refresh"):
            token = _refresh(plugin_id, connection_id, profile, force=True, directory=directory)
            _apply_access_token_headers(safe_headers, token, origin)
            response = perform_plugin_network_request(
                url=url,
                method=method,
                headers=safe_headers,
                body=body,
                timeout_seconds=OAUTH_REQUEST_TIMEOUT_SECONDS,
            )
        return response
    except PluginNetworkError as exc:
        raise PluginOAuthError(400, str(exc)) from exc


def disconnect_connection(plugin_id: str, connection_id: str, directory: Path | None = None) -> dict[str, Any]:
    if not _valid_connection_id(connection_id):
        raise PluginOAuthError(422, "connection_idが正しくありません。")
    key = (plugin_id, connection_id)
    with _lock:
        _delete_secrets(plugin_id, connection_id)
        profiles = _read_profiles(plugin_id, directory)
        profiles.pop(connection_id, None)
        _write_profiles(plugin_id, profiles, directory)
        pending = _pending.pop(key, None)
        _flow_status.pop(key, None)
    if pending:
        try:
            pending.server.server_close()
        except OSError:
            pass
    return {"connection_id": connection_id, "connected": False, "message": "Sparkleに保存したOAuth資格情報を削除しました。"}


def clear_plugin_connections(plugin_id: str, directory: Path | None = None) -> None:
    with _lock:
        profiles = _read_profiles(plugin_id, directory)
        for connection_id in list(profiles):
            _delete_secrets(plugin_id, connection_id)
        path = _profile_path(plugin_id, directory)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise PluginOAuthError(500, "プラグインのOAuth資格情報を削除できません。") from exc
        for key, pending in list(_pending.items()):
            if key[0] == plugin_id:
                _pending.pop(key, None)
                try:
                    pending.server.server_close()
                except OSError:
                    pass
        for key in [key for key in _flow_status if key[0] == plugin_id]:
            _flow_status.pop(key, None)
