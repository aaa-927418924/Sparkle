"""Authentication state for Sparkle's optional remote Web gateway.

The desktop application itself remains local and unauthenticated.  This module
stores only hashes of the access key and browser session tokens, so the
one-time access key shown by the desktop settings page is never recoverable
from the JSON file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from paths import get_app_data_dir


PERSISTENT_SESSION_DAYS = 365
SESSION_HOURS = 12
STATE_VERSION = 1
DEFAULT_REMOTE_MODE = "funnel"
REMOTE_MODES = frozenset({"funnel", "serve"})
MCP_AUTH_FILE = "mcp-auth.json"


class InvalidAccessKey(ValueError):
    """Raised when a login attempt does not match the configured key."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "remote_mode": DEFAULT_REMOTE_MODE,
        "enabled": False,
        "access_key_hash": None,
        "access_key_created_at": None,
        "sessions": {},
    }


class AuthStore:
    """Small file-backed store for remote Web credentials and sessions."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self.path = Path(path) if path is not None else get_app_data_dir() / "remote-auth.json"
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
            return _empty_state()
        if not isinstance(raw, dict):
            return _empty_state()

        state = _empty_state()
        state["version"] = raw.get("version", STATE_VERSION)
        remote_mode = raw.get("remote_mode")
        state["remote_mode"] = (
            remote_mode
            if isinstance(remote_mode, str) and remote_mode in REMOTE_MODES
            else DEFAULT_REMOTE_MODE
        )
        state["enabled"] = bool(raw.get("enabled", False))
        state["access_key_hash"] = raw.get("access_key_hash") if isinstance(raw.get("access_key_hash"), str) else None
        state["access_key_created_at"] = (
            raw.get("access_key_created_at")
            if isinstance(raw.get("access_key_created_at"), str)
            else None
        )
        sessions = raw.get("sessions")
        if isinstance(sessions, dict):
            state["sessions"] = {
                str(token_hash): record
                for token_hash, record in sessions.items()
                if isinstance(token_hash, str) and isinstance(record, dict)
            }
        return state

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(6)}.tmp")
        payload = json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        try:
            temporary.replace(self.path)
        except OSError:
            # Keep the old file intact if replacement is temporarily blocked
            # (for example by backup software).  The next state-changing
            # operation can retry the write.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _new_access_key() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def _new_session_token() -> str:
        return secrets.token_urlsafe(32)

    def _clear_sessions_locked(self) -> None:
        self._state["sessions"] = {}

    def _purge_expired_locked(self, now: Optional[datetime] = None) -> bool:
        current = now or _utc_now()
        sessions = self._state.get("sessions", {})
        expired = []
        for token_hash, record in sessions.items():
            if not isinstance(record, dict):
                expired.append(token_hash)
                continue
            expires_at = _parse_iso(record.get("expires_at"))
            if expires_at is None or expires_at <= current:
                expired.append(token_hash)
        for token_hash in expired:
            sessions.pop(token_hash, None)
        return bool(expired)

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._state.get("enabled") and self._state.get("access_key_hash"))

    def get_remote_mode(self) -> str:
        with self._lock:
            mode = self._state.get("remote_mode")
            return mode if mode in REMOTE_MODES else DEFAULT_REMOTE_MODE

    def set_remote_mode(self, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized not in REMOTE_MODES:
            raise ValueError("リモートWebの公開方式は funnel または serve を指定してください。")
        with self._lock:
            if self._state.get("remote_mode") != normalized:
                self._state["remote_mode"] = normalized
                self._save_locked()
            return normalized

    def enable(self) -> str:
        """Enable access and return a newly generated key exactly once."""
        with self._lock:
            key = self._new_access_key()
            now = _utc_now()
            self._state["enabled"] = True
            self._state["access_key_hash"] = _hash(key)
            self._state["access_key_created_at"] = _iso(now)
            self._clear_sessions_locked()
            self._save_locked()
            return key

    def rotate_access_key(self) -> str:
        """Replace the key and invalidate every existing browser session."""
        return self.enable()

    def validate_access_key(self, access_key: str) -> bool:
        """Validate the access key without creating a browser session."""

        supplied_hash = _hash(access_key.strip()) if isinstance(access_key, str) else ""
        with self._lock:
            stored_hash = self._state.get("access_key_hash")
            return bool(
                self._state.get("enabled")
                and isinstance(stored_hash, str)
                and hmac.compare_digest(stored_hash, supplied_hash)
            )

    def disable(self) -> None:
        with self._lock:
            self._state["enabled"] = False
            self._state["access_key_hash"] = None
            self._state["access_key_created_at"] = None
            self._clear_sessions_locked()
            self._save_locked()

    def login(
        self,
        access_key: str,
        trust_device: bool = False,
        device_label: str = "ブラウザ",
    ) -> dict[str, Any]:
        with self._lock:
            stored_hash = self._state.get("access_key_hash")
            supplied_hash = _hash(access_key.strip()) if isinstance(access_key, str) else ""
            if (
                not self._state.get("enabled")
                or not isinstance(stored_hash, str)
                or not hmac.compare_digest(stored_hash, supplied_hash)
            ):
                raise InvalidAccessKey("アクセスキーが正しくありません。")

            now = _utc_now()
            self._purge_expired_locked(now)
            token = self._new_session_token()
            expires = now + (
                timedelta(days=PERSISTENT_SESSION_DAYS)
                if trust_device
                else timedelta(hours=SESSION_HOURS)
            )
            label = str(device_label or "ブラウザ").strip()[:80] or "ブラウザ"
            record = {
                "id": uuid.uuid4().hex,
                "persistent": bool(trust_device),
                "label": label,
                "created_at": _iso(now),
                "expires_at": _iso(expires),
                "last_seen_at": _iso(now),
            }
            self._state["sessions"][_hash(token)] = record
            self._save_locked()
            return {
                "token": token,
                "session_id": record["id"],
                "persistent": record["persistent"],
                "expires_at": record["expires_at"],
            }

    def authenticate(self, token: Optional[str]) -> Optional[dict[str, Any]]:
        if not token:
            return None
        token_hash = _hash(token)
        with self._lock:
            if not self._state.get("enabled"):
                return None
            changed = self._purge_expired_locked()
            record = self._state.get("sessions", {}).get(token_hash)
            if record is None:
                if changed:
                    self._save_locked()
                return None
            if changed:
                self._save_locked()
            return dict(record)

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._lock:
            changed = self._state.get("sessions", {}).pop(_hash(token), None) is not None
            changed = self._purge_expired_locked() or changed
            if changed:
                self._save_locked()

    def revoke_session(self, session_id: str) -> bool:
        with self._lock:
            sessions = self._state.get("sessions", {})
            for token_hash, record in list(sessions.items()):
                if isinstance(record, dict) and record.get("id") == session_id:
                    del sessions[token_hash]
                    self._save_locked()
                    return True
            return False

    def revoke_all(self) -> None:
        with self._lock:
            self._clear_sessions_locked()
            self._save_locked()

    def list_trusted(self) -> list[dict[str, Any]]:
        with self._lock:
            changed = self._purge_expired_locked()
            if changed:
                self._save_locked()
            return [
                {
                    "id": record.get("id"),
                    "label": record.get("label") or "ブラウザ",
                    "persistent": bool(record.get("persistent")),
                    "created_at": record.get("created_at"),
                    "last_seen_at": record.get("last_seen_at"),
                    "expires_at": record.get("expires_at"),
                }
                for record in self._state.get("sessions", {}).values()
                if isinstance(record, dict)
            ]

    def status(self) -> dict[str, Any]:
        with self._lock:
            changed = self._purge_expired_locked()
            if changed:
                self._save_locked()
            sessions = self.list_trusted()
            return {
                "remote_mode": self.get_remote_mode(),
                "enabled": bool(self._state.get("enabled") and self._state.get("access_key_hash")),
                "access_key_created_at": self._state.get("access_key_created_at"),
                "session_count": len(sessions),
                "trusted_devices": [item for item in sessions if item["persistent"]],
                "session_hours": SESSION_HOURS,
                "persistent_days": PERSISTENT_SESSION_DAYS,
            }


_default_store: Optional[AuthStore] = None
_default_mcp_store: Optional[AuthStore] = None
_default_store_lock = threading.Lock()


def get_auth_store() -> AuthStore:
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = AuthStore()
        return _default_store


def get_mcp_auth_store() -> AuthStore:
    """Return the persistent credential store used only by Remote MCP."""

    global _default_mcp_store
    with _default_store_lock:
        if _default_mcp_store is None:
            _default_mcp_store = AuthStore(get_app_data_dir() / MCP_AUTH_FILE)
        return _default_mcp_store
