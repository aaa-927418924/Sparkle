"""Desktop-client connection to a remote Sparkle data server.

The desktop process remains the browser/extension's same-origin API.  When
remote mode is enabled this module forwards the data requests to the
authenticated server gateway.  Only the non-secret connection profile is
stored in JSON; the bearer session token is kept in Windows Credential
Manager through ``keyring``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from paths import get_app_data_dir


LOGGER = logging.getLogger("sparkle.remote_client")
CONFIG_FILE = "remote-client.json"
KEYRING_SERVICE = "Sparkle Remote Client"
KEYRING_USERNAME = "desktop-client-session"
REMOTE_CACHE_DIR_NAME = "remote-cache"


class RemoteClientError(RuntimeError):
    """A safe connection error suitable for displaying in the UI."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class RemoteResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": False,
        "server_url": "",
        "server_label": "",
        "server_version": "",
        "expires_at": None,
    }


class _CredentialStore:
    """Use only a real Windows Credential Manager keyring backend."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RemoteClientError(
                "リモート接続情報はWindows資格情報マネージャーでのみ保存できます。"
            )
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise RemoteClientError(
                "リモート接続に必要なkeyringがインストールされていません。"
            ) from exc

        try:
            backend = keyring.get_keyring()
        except Exception as exc:  # pragma: no cover - backend-specific failure
            raise RemoteClientError(
                "Windows資格情報マネージャーを利用できません。"
            ) from exc

        backend_name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        if (
            getattr(backend, "priority", 0) <= 0
            or "fail" in backend_name
            or "plaintext" in backend_name
            or "file" in backend_name
        ):
            raise RemoteClientError(
                "安全なWindows資格情報マネージャーのバックエンドを利用できません。"
            )
        self._keyring = keyring

    def get(self) -> Optional[str]:
        try:
            value = self._keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as exc:  # pragma: no cover - backend-specific failure
            LOGGER.warning("Remote client credential read failed: %s", type(exc).__name__)
            raise RemoteClientError("リモート接続トークンを読み出せませんでした。") from exc
        return value.strip() if isinstance(value, str) and value.strip() else None

    def set(self, value: str) -> None:
        try:
            self._keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)
        except Exception as exc:  # pragma: no cover - backend-specific failure
            LOGGER.warning("Remote client credential write failed: %s", type(exc).__name__)
            raise RemoteClientError("リモート接続トークンを保存できませんでした。") from exc

    def delete(self) -> None:
        try:
            self._keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as exc:  # keyring uses an exception for an absent item
            error_name = type(exc).__name__.lower()
            if "password" in error_name or "notfound" in error_name:
                return
            LOGGER.warning("Remote client credential delete failed: %s", type(exc).__name__)
            raise RemoteClientError("リモート接続トークンを削除できませんでした。") from exc


class RemoteClient:
    """Persisted connection profile and authenticated HTTP client."""

    def __init__(self, config_path: Optional[Path | str] = None) -> None:
        self.path = Path(config_path) if config_path is not None else get_app_data_dir() / CONFIG_FILE
        self._lock = threading.RLock()
        self._state = self._load()
        self._credentials: Optional[_CredentialStore] = None

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
            return _default_state()
        if not isinstance(raw, dict):
            return _default_state()
        state = _default_state()
        state["enabled"] = bool(raw.get("enabled", False))
        for key in ("server_url", "server_label", "server_version", "expires_at"):
            value = raw.get(key)
            if isinstance(value, str):
                state[key] = value
        return state

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _credential_store(self) -> _CredentialStore:
        if self._credentials is None:
            self._credentials = _CredentialStore()
        return self._credentials

    @staticmethod
    def _normalize_url(value: str) -> str:
        raw = str(value or "").strip().rstrip("/")
        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise RemoteClientError("サーバーURLが正しくありません。", 422) from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RemoteClientError("サーバーURLはhttpまたはhttpsで入力してください。", 422)
        if parsed.username or parsed.password:
            raise RemoteClientError("サーバーURLに認証情報を含めないでください。", 422)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    @staticmethod
    def _safe_headers(headers: Optional[Mapping[str, str]]) -> dict[str, str]:
        blocked = {"host", "content-length", "origin", "cookie", "referer"}
        return {
            str(key): str(value)
            for key, value in (headers or {}).items()
            if str(key).lower() not in blocked
        }

    @staticmethod
    def _decode_error(body: bytes, fallback: str) -> str:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return fallback
        detail = data.get("detail") if isinstance(data, dict) else None
        return str(detail).strip()[:500] if detail else fallback

    def _raw_request(
        self,
        url: str,
        method: str = "GET",
        body: bytes = b"",
        headers: Optional[Mapping[str, str]] = None,
    ) -> RemoteResponse:
        request_headers = self._safe_headers(headers)
        request_headers.setdefault("Accept", "application/json")
        data = body if method.upper() not in {"GET", "HEAD"} else None
        request = Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=45) as response:
                return RemoteResponse(
                    int(response.status),
                    {str(key): str(value) for key, value in response.headers.items()},
                    response.read(),
                )
        except HTTPError as exc:
            payload = exc.read()
            return RemoteResponse(
                int(exc.code),
                {str(key): str(value) for key, value in exc.headers.items()},
                payload,
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise RemoteClientError(
                "サーバーに接続できません。URL、Tailscale接続、サーバーの起動状態を確認してください。"
            ) from exc

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": bool(self._state.get("enabled")),
                "server_url": self._state.get("server_url", ""),
                "server_label": self._state.get("server_label", ""),
                "server_version": self._state.get("server_version", ""),
                "expires_at": self._state.get("expires_at"),
                "authenticated": bool(self._state.get("enabled")),
            }

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._state.get("enabled") and self._state.get("server_url"))

    def base_url(self) -> str:
        with self._lock:
            return str(self._state.get("server_url") or "").rstrip("/")

    def configure(self, server_url: str, access_key: str) -> dict[str, Any]:
        normalized_url = self._normalize_url(server_url)
        key = str(access_key or "").strip()
        if not key:
            raise RemoteClientError("アクセスキーを入力してください。", 422)
        payload = json.dumps(
            {"access_key": key, "device_label": "Sparkleデスクトップ"},
            ensure_ascii=False,
        ).encode("utf-8")
        response = self._raw_request(
            f"{normalized_url}/remote-client/login",
            method="POST",
            body=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise RemoteClientError(
                self._decode_error(response.body, "サーバーへの接続認証に失敗しました。"),
                response.status_code,
            )
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteClientError("サーバーから不正な認証応答が返りました。") from exc
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise RemoteClientError("サーバーから接続トークンを取得できませんでした。")

        with self._lock:
            self._credential_store().set(token.strip())
            self._state.update(
                {
                    "enabled": True,
                    "server_url": normalized_url,
                    "server_label": str(data.get("server") or "Sparkle")[:120],
                    "server_version": str(data.get("version") or "")[:80],
                    "expires_at": str(data.get("expires_at") or "")[:80],
                }
            )
            self._save_locked()
            return self.status()

    def disconnect(self) -> None:
        with self._lock:
            token = self._credential_store().get()
            base = str(self._state.get("server_url") or "").rstrip("/")
            if token and base:
                try:
                    self._raw_request(
                        f"{base}/remote-client/logout",
                        method="POST",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                except RemoteClientError:
                    pass
            self._credential_store().delete()
            self._state = _default_state()
            self._save_locked()

    def test_connection(self) -> dict[str, Any]:
        response = self.request("/remote-client/status", method="GET")
        if response.status_code < 200 or response.status_code >= 300:
            raise RemoteClientError(
                self._decode_error(response.body, "サーバー認証が無効です。"),
                response.status_code,
            )
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteClientError("サーバーから不正な状態応答が返りました。") from exc
        return data if isinstance(data, dict) else {}

    def request(
        self,
        path: str,
        method: str = "GET",
        body: bytes = b"",
        headers: Optional[Mapping[str, str]] = None,
    ) -> RemoteResponse:
        with self._lock:
            base = str(self._state.get("server_url") or "").rstrip("/")
            if not self._state.get("enabled") or not base:
                raise RemoteClientError("サーバーモードが有効になっていません。", 409)
            token = self._credential_store().get()
        if not token:
            raise RemoteClientError("リモート接続トークンがありません。再接続してください。", 401)
        normalized_path = path if str(path).startswith("/") else f"/{path}"
        request_headers = self._safe_headers(headers)
        request_headers["Authorization"] = f"Bearer {token}"
        return self._raw_request(
            f"{base}{normalized_path}",
            method=method,
            body=body,
            headers=request_headers,
        )

    def cache_dir(self) -> Path:
        directory = get_app_data_dir() / REMOTE_CACHE_DIR_NAME
        directory.mkdir(parents=True, exist_ok=True)
        return directory


_default_client: Optional[RemoteClient] = None
_default_client_lock = threading.Lock()


def get_remote_client() -> RemoteClient:
    global _default_client
    with _default_client_lock:
        if _default_client is None:
            _default_client = RemoteClient()
        return _default_client
