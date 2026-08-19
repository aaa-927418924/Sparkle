"""Runtime manager for Sparkle's optional Tailscale Web endpoints."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen

from remote_auth import AuthStore


REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 8001
MAIN_PORT = 8000
REMOTE_TARGET = f"http://{REMOTE_HOST}:{REMOTE_PORT}"
MAIN_TARGET = f"http://{REMOTE_HOST}:{MAIN_PORT}"
SERVE_WEB_HTTPS_PORT = 8443
WEB_MODE_FUNNEL = "funnel"
WEB_MODE_SERVE = "serve"
WEB_MODES = frozenset({WEB_MODE_FUNNEL, WEB_MODE_SERVE})


def _target_matches(value: Any, target: str) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.lower().rstrip("/")
    expected = target.lower().rstrip("/")
    return normalized == expected or expected in normalized


def _find_target(value: Any, targets: tuple[str, ...]) -> Optional[str]:
    if isinstance(value, str):
        for target in targets:
            if _target_matches(value, target):
                return target
        return None
    if isinstance(value, dict):
        for child in value.values():
            found = _find_target(child, targets)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_target(child, targets)
            if found:
                return found
    return None


def _find_public_url(value: Any) -> Optional[str]:
    if isinstance(value, str):
        match = re.search(r"https://[^\s\"']+", value)
        if match:
            return match.group(0).rstrip(".,)")
        return None
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.startswith("https://"):
                return key.rstrip(".,)")
            if key == "Web" and isinstance(child, dict):
                for host_port in child:
                    if isinstance(host_port, str):
                        return _web_host_to_url(host_port)
            found = _find_public_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_public_url(child)
            if found:
                return found
    return None


def _web_host_to_url(host_port: str) -> Optional[str]:
    """Convert a Tailscale Web JSON key (host:port) to a clickable HTTPS URL."""
    value = host_port.strip().rstrip(".,)")
    if not value:
        return None
    if value.startswith("https://"):
        return value
    if value.startswith("http://"):
        return "https://" + value[7:]
    if value.endswith(":443"):
        value = value[:-4]
    return "https://" + value


def _host_port_matches(host_port: str, preferred_port: Optional[int]) -> bool:
    if preferred_port is None:
        return True
    value = host_port.strip().rstrip(".,)")
    if value.startswith(("https://", "http://")):
        value = value.split("://", 1)[1]
    match = re.search(r":(\d+)$", value)
    return int(match.group(1)) == preferred_port if match else preferred_port == 443


def _find_web_routes(
    value: Any,
    preferred_port: Optional[int],
    targets: tuple[str, ...],
) -> list[tuple[str, Optional[str]]]:
    """Return Web routes as (host:port, known target) pairs.

    Tailscale Serve can expose Sparkle's desktop route and the remote gateway
    at the same time. Looking at the port as well as the proxy target keeps
    the remote URL separate from the existing desktop Serve URL.
    """
    routes: list[tuple[str, Optional[str]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "Web" and isinstance(child, dict):
                for host_port, route in child.items():
                    if isinstance(host_port, str) and _host_port_matches(host_port, preferred_port):
                        routes.append((host_port, _find_target(route, targets)))
                continue
            routes.extend(_find_web_routes(child, preferred_port, targets))
    elif isinstance(value, list):
        for child in value:
            routes.extend(_find_web_routes(child, preferred_port, targets))
    return routes


def _find_public_url_for_target(
    value: Any,
    target: str,
    preferred_port: Optional[int],
) -> Optional[str]:
    for host_port, route_target in _find_web_routes(value, preferred_port, (target,)):
        if route_target == target:
            return _web_host_to_url(host_port)
    return None


def _has_any_route_config(value: Any) -> bool:
    """Detect an active Serve/Funnel route even when its target is unknown."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and (
                key.startswith("https://")
                or key.startswith("tcp://")
                or key in {"Web", "TCP", "TLS-terminated-TCP", "Services"}
            ):
                if child:
                    return True
            if _has_any_route_config(child):
                return True
    elif isinstance(value, list):
        return any(_has_any_route_config(child) for child in value)
    return False


class RemoteAccessManager:
    """Own the local authenticated gateway and its Funnel/Serve route."""

    def __init__(self, auth_store: Optional[AuthStore] = None, main_port: int = MAIN_PORT) -> None:
        self.auth_store = auth_store or AuthStore()
        self.main_target = f"http://{REMOTE_HOST}:{int(main_port)}"
        self._lock = threading.RLock()
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None
        self._funnel_cache: Optional[dict[str, Any]] = None
        self._funnel_cache_at = 0.0

    @staticmethod
    def _tailscale_path() -> Optional[str]:
        found = shutil.which("tailscale")
        if found:
            return found
        windows_path = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(windows_path) if windows_path.is_file() else None

    def _run_cli(self, args: list[str], timeout: float = 30.0) -> tuple[bool, str, str]:
        executable = self._tailscale_path()
        if executable is None:
            return False, "", "Tailscale CLIが見つかりません。"
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except FileNotFoundError:
            return False, "", "Tailscale CLIが見つかりません。"
        except subprocess.TimeoutExpired:
            return False, "", "Tailscale CLIがタイムアウトしました。"
        except OSError as exc:
            return False, "", f"Tailscale CLIを実行できませんでした: {exc}"

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            return False, stdout, stderr or stdout or f"終了コード {result.returncode}"
        return True, stdout, stderr

    @staticmethod
    def _cli_error(detail: str) -> str:
        lowered = detail.lower()
        if "access is denied" in lowered or "permission" in lowered:
            return "Tailscaleの状態を読み取れませんでした。Sparkleを管理者権限で一度起動して確認してください。"
        return detail[:500] or "Tailscaleの操作に失敗しました。"

    def _status(self, command: str) -> dict[str, Any]:
        ok, stdout, stderr = self._run_cli([command, "status", "--json"])
        if not ok:
            return {
                "available": False,
                "active": False,
                "error": self._cli_error(stderr or stdout),
            }
        try:
            parsed = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            return {
                "available": False,
                "active": False,
                "error": "Tailscaleの状態(JSON)を読み取れませんでした。",
            }

        target = _find_target(parsed, (REMOTE_TARGET, self.main_target))
        target_name = None
        if target == REMOTE_TARGET:
            target_name = "remote"
        elif target == self.main_target:
            target_name = "main"
        elif _has_any_route_config(parsed):
            target_name = "other"
        public_url = _find_public_url(parsed) if target_name == "remote" else None
        return {
            "available": True,
            "active": target_name is not None,
            "target": target_name,
            "public_url": public_url,
        }

    def _status_for_target(
        self,
        command: str,
        target: str,
        preferred_port: Optional[int],
    ) -> dict[str, Any]:
        ok, stdout, stderr = self._run_cli([command, "status", "--json"])
        if not ok:
            return {
                "available": False,
                "active": False,
                "target": None,
                "public_url": None,
                "error": self._cli_error(stderr or stdout),
            }
        try:
            parsed = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            return {
                "available": False,
                "active": False,
                "target": None,
                "public_url": None,
                "error": "Tailscaleの状態(JSON)を読み込めませんでした。",
            }

        routes = _find_web_routes(
            parsed,
            preferred_port,
            (REMOTE_TARGET, self.main_target),
        )
        for host_port, route_target in routes:
            if route_target == target:
                target_name = "remote" if target == REMOTE_TARGET else "main"
                return {
                    "available": True,
                    "active": True,
                    "target": target_name,
                    "public_url": _web_host_to_url(host_port),
                }

        if routes:
            known_targets = {route_target for _, route_target in routes}
            target_name = "main" if self.main_target in known_targets else "other"
            return {
                "available": True,
                "active": True,
                "target": target_name,
                "public_url": None,
            }

        return {
            "available": True,
            "active": False,
            "target": None,
            "public_url": None,
        }

    def funnel_status(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if not force and self._funnel_cache is not None and now - self._funnel_cache_at < 2.0:
                return dict(self._funnel_cache)
            status = self._status("funnel")
            self._funnel_cache = status
            self._funnel_cache_at = now
            return dict(status)

    def _serve_status(self) -> dict[str, Any]:
        return self._status("serve")

    def _serve_web_status(self) -> dict[str, Any]:
        return self._status_for_target("serve", REMOTE_TARGET, SERVE_WEB_HTTPS_PORT)

    def _configured_web_mode(self) -> str:
        mode = self.auth_store.get_remote_mode()
        return mode if mode in WEB_MODES else WEB_MODE_FUNNEL

    def _web_status(self, mode: Optional[str] = None) -> dict[str, Any]:
        selected = mode or self._configured_web_mode()
        if selected == WEB_MODE_SERVE:
            return self._serve_web_status()
        return self.funnel_status()

    def _start_remote_server(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            try:
                import uvicorn
                from main import app
                from remote_gateway import RemoteGateway

                config = uvicorn.Config(
                    RemoteGateway(app, self.auth_store),
                    host=REMOTE_HOST,
                    port=REMOTE_PORT,
                    log_config=None,
                    access_log=False,
                )
                server = uvicorn.Server(config)
            except Exception as exc:
                self._last_error = f"リモートWebサーバーを準備できませんでした: {exc}"
                return False

            def run() -> None:
                try:
                    server.run()
                except Exception as exc:
                    self._last_error = f"リモートWebサーバーが停止しました: {exc}"

            self._server = server
            self._thread = threading.Thread(target=run, name="sparkle-remote-web", daemon=True)
            self._thread.start()

        for _ in range(60):
            try:
                with urlopen(f"http://{REMOTE_HOST}:{REMOTE_PORT}/health", timeout=0.5) as response:
                    if response.status == 200 and b"Sparkle Remote" in response.read(256):
                        return True
            except Exception:
                time.sleep(0.1)
        self._last_error = "リモートWebサーバーが起動しませんでした。"
        return False

    def _stop_remote_server(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.should_exit = True
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def _prepare_serve_switch(self) -> tuple[bool, Optional[str]]:
        serve = self._serve_status()
        if not serve.get("available"):
            return False, serve.get("error") or "Tailscale Serveの状態を確認できません。"
        if not serve.get("active"):
            return True, None
        if serve.get("target") != "main":
            return False, "別のTailscale Serve設定が使われています。先にその設定を解除してください。"
        ok, stdout, stderr = self._run_cli(["serve", "reset"])
        if not ok:
            return False, self._cli_error(stderr or stdout)
        return True, None

    def _stop_serve_web_route(self) -> tuple[bool, Optional[str]]:
        current = self._serve_web_status()
        if not current.get("available"):
            return False, current.get("error") or "Tailscale Serveの状態を確認できません。"
        if not current.get("active"):
            return True, None
        if current.get("target") != "remote":
            return False, "Tailscale Serveのポート8443に別の設定があります。先にその設定を解除してください。"
        ok, stdout, stderr = self._run_cli(
            [
                "serve",
                f"--https={SERVE_WEB_HTTPS_PORT}",
                "--yes",
                REMOTE_TARGET,
                "off",
            ]
        )
        if not ok:
            return False, self._cli_error(stderr or stdout)
        return True, None

    def _restore_default_serve_route(self) -> None:
        # Funnel uses HTTPS 443, so restore Sparkle's normal tailnet-only
        # desktop route after Funnel has released that port.
        serve = self._serve_status()
        if serve.get("available") and not serve.get("active"):
            self._run_cli(["serve", "--bg", "--https=443", "--yes", self.main_target])

    def _start_serve_web_route(self) -> dict[str, Any]:
        current = self._serve_web_status()
        if not current.get("available"):
            return {"ok": False, "status": current, "error": current.get("error")}
        if current.get("active"):
            if current.get("target") == "remote":
                return {"ok": True, "status": current}
            return {
                "ok": False,
                "status": current,
                "error": "Tailscale Serveのポート8443に別の設定があります。先にその設定を解除してください。",
            }

        funnel = self.funnel_status(force=True)
        if not funnel.get("available"):
            return {"ok": False, "status": current, "error": funnel.get("error")}
        if funnel.get("active"):
            if funnel.get("target") not in {"remote", "main"}:
                return {
                    "ok": False,
                    "status": current,
                    "error": "別のTailscale Funnel設定が使われています。先にその設定を解除してください。",
                }
            ok, stdout, stderr = self._run_cli(["funnel", "reset"])
            if not ok:
                return {
                    "ok": False,
                    "status": current,
                    "error": self._cli_error(stderr or stdout),
                }
            self._funnel_cache = None
            self._restore_default_serve_route()

        ok, stdout, stderr = self._run_cli(
            [
                "serve",
                "--bg",
                f"--https={SERVE_WEB_HTTPS_PORT}",
                "--yes",
                REMOTE_TARGET,
            ]
        )
        if not ok:
            return {
                "ok": False,
                "status": current,
                "error": self._cli_error(stderr or stdout),
            }

        verified = self._serve_web_status()
        if verified.get("available") and verified.get("active") and verified.get("target") != "remote":
            return {
                "ok": False,
                "status": verified,
                "error": "Tailscale Serveの転送先がSparkleのリモートWebではありません。",
            }
        if not verified.get("available"):
            verified = {
                **verified,
                "configured": True,
                "warning": "Tailscale Serveの設定は完了しましたが、現在の状態を確認できません。",
            }
        return {"ok": True, "status": verified}

    def _start_funnel_route(self) -> dict[str, Any]:
        current = self.funnel_status(force=True)
        if current.get("available") and current.get("active"):
            if current.get("target") == "remote":
                return {"ok": True, "status": current}
            if current.get("target") == "main":
                ok, stdout, stderr = self._run_cli(["funnel", "reset"])
                if not ok:
                    return {
                        "ok": False,
                        "status": current,
                        "error": self._cli_error(stderr or stdout),
                    }
                self._funnel_cache = None
            else:
                return {
                    "ok": False,
                    "status": current,
                    "error": "別のTailscale Funnel設定がすでに有効です。先にその設定を解除してください。",
                }
        if not current.get("available"):
            return {"ok": False, "status": current, "error": current.get("error")}

        ready, error = self._prepare_serve_switch()
        if not ready:
            return {"ok": False, "status": current, "error": error}

        ok, stdout, stderr = self._run_cli(
            ["funnel", "--bg", "--https=443", "--yes", REMOTE_TARGET]
        )
        if not ok:
            return {
                "ok": False,
                "status": current,
                "error": self._cli_error(stderr or stdout),
            }
        verified = self.funnel_status(force=True)
        if verified.get("available") and verified.get("active") and verified.get("target") != "remote":
            return {
                "ok": False,
                "status": verified,
                "error": "Funnelの転送先がSparkleのリモートWebではありません。",
            }
        if not verified.get("available"):
            verified = {
                **verified,
                "configured": True,
                "warning": "Funnelの有効化コマンドは成功しましたが、現在の状態を確認できません。",
            }
        return {"ok": True, "status": verified}

    def _start_web_route(self) -> dict[str, Any]:
        if self._configured_web_mode() == WEB_MODE_SERVE:
            return self._start_serve_web_route()
        return self._start_funnel_route()

    def enable(self) -> dict[str, Any]:
        key = self.auth_store.enable()
        if not self._start_remote_server():
            return {
                "ok": False,
                "access_key": key,
                "status": self.status(),
                "error": self._last_error,
            }
        result = self._start_web_route()
        if not result.get("ok"):
            self._last_error = result.get("error")
        else:
            self._last_error = None
        return {
            "ok": bool(result.get("ok")),
            "access_key": key,
            "status": self.status(),
            "error": result.get("error"),
        }

    def retry(self) -> dict[str, Any]:
        if not self.auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "先に外部Webアクセスを有効にしてください。"}
        if not self._start_remote_server():
            return {"ok": False, "status": self.status(), "error": self._last_error}
        result = self._start_web_route()
        self._last_error = result.get("error") if not result.get("ok") else None
        return {
            "ok": bool(result.get("ok")),
            "status": self.status(),
            "error": result.get("error"),
        }

    def set_mode(self, mode: str) -> dict[str, Any]:
        normalized = str(mode or "").strip().lower()
        if normalized not in WEB_MODES:
            return {
                "ok": False,
                "status": self.status(),
                "error": "公開方式は Funnel または Tailscale Serve Web から選択してください。",
            }

        previous = self._configured_web_mode()
        if previous == normalized:
            return {"ok": True, "status": self.status()}

        if self.auth_store.is_enabled():
            if previous == WEB_MODE_FUNNEL:
                current = self.funnel_status(force=True)
                if not current.get("available"):
                    error = current.get("error") or "Tailscale Funnelの状態を確認できません。"
                    self._last_error = error
                    return {"ok": False, "status": self.status(), "error": error}
                if current.get("active"):
                    if current.get("target") != "remote":
                        error = "別のTailscale Funnel設定が使われています。先にその設定を解除してください。"
                        self._last_error = error
                        return {"ok": False, "status": self.status(), "error": error}
                    ok, stdout, stderr = self._run_cli(["funnel", "reset"])
                    if not ok:
                        error = self._cli_error(stderr or stdout)
                        self._last_error = error
                        return {"ok": False, "status": self.status(), "error": error}
                    self._funnel_cache = None
                    self._restore_default_serve_route()
            else:
                stopped, error = self._stop_serve_web_route()
                if not stopped:
                    self._last_error = error
                    return {"ok": False, "status": self.status(), "error": error}

        self.auth_store.set_remote_mode(normalized)
        if not self.auth_store.is_enabled():
            self._last_error = None
            return {"ok": True, "status": self.status()}
        result = self._start_web_route()
        self._last_error = result.get("error") if not result.get("ok") else None
        return {
            "ok": bool(result.get("ok")),
            "status": self.status(),
            "error": result.get("error"),
        }

    def rotate(self) -> dict[str, Any]:
        if not self.auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "先に外部Webアクセスを有効にしてください。"}
        key = self.auth_store.rotate_access_key()
        return {"ok": True, "access_key": key, "status": self.status()}

    def revoke_all(self) -> dict[str, Any]:
        self.auth_store.revoke_all()
        return {"ok": True, "status": self.status()}

    def disable(self) -> dict[str, Any]:
        mode = self._configured_web_mode()
        if mode == WEB_MODE_SERVE:
            current = self._serve_web_status()
            if not current.get("available"):
                self._last_error = current.get("error") or "Tailscale Serveの状態を確認できません。"
                return {"ok": False, "status": self.status(), "error": self._last_error}
            if current.get("active"):
                stopped, error = self._stop_serve_web_route()
                if not stopped:
                    self._last_error = error
                    return {"ok": False, "status": self.status(), "error": error}
        else:
            current = self.funnel_status(force=True)
            if not current.get("available"):
                self._last_error = current.get("error") or "Tailscale Funnelの状態を確認できません。"
                return {"ok": False, "status": self.status(), "error": self._last_error}
            if current.get("active") and current.get("target") == "remote":
                ok, stdout, stderr = self._run_cli(["funnel", "reset"])
                if not ok:
                    self._last_error = self._cli_error(stderr or stdout)
                    return {"ok": False, "status": self.status(), "error": self._last_error}
                self._funnel_cache = None
                self._restore_default_serve_route()

        self.auth_store.disable()
        self._stop_remote_server()
        self._last_error = None
        return {"ok": True, "status": self.status()}

    def start_on_launch(self) -> dict[str, Any]:
        if not self.auth_store.is_enabled():
            return self.status()
        if not self._start_remote_server():
            return self.status()
        result = self._start_web_route()
        self._last_error = result.get("error") if not result.get("ok") else None
        return self.status()

    def shutdown(self) -> None:
        with self._lock:
            enabled = self.auth_store.is_enabled()
            mode = self._configured_web_mode()
        if enabled:
            if mode == WEB_MODE_SERVE:
                self._stop_serve_web_route()
            else:
                current = self.funnel_status(force=True)
                if current.get("active") and current.get("target") == "remote":
                    self._run_cli(["funnel", "reset"])
                    self._funnel_cache = None
        self._stop_remote_server()

    def status(self) -> dict[str, Any]:
        enabled = self.auth_store.is_enabled()
        web_mode = self._configured_web_mode()
        if enabled:
            remote = self._web_status(web_mode)
        else:
            remote = {
                "available": True,
                "active": False,
                "target": None,
                "public_url": None,
            }
        empty_route = {
            "available": remote.get("available", True),
            "active": False,
            "target": None,
            "public_url": None,
        }
        configured_mcp_url = os.environ.get("SPARKLE_MCP_PUBLIC_URL")
        if not configured_mcp_url and remote.get("public_url"):
            configured_mcp_url = f"{str(remote['public_url']).rstrip('/')}/mcp"
        return {
            "mode": web_mode if enabled else "tailscale",
            "web_mode": web_mode,
            "auth": self.auth_store.status(),
            "remote_server": bool(self._thread and self._thread.is_alive()),
            "mcp_url": configured_mcp_url,
            "remote": remote,
            "funnel": remote if web_mode == WEB_MODE_FUNNEL else empty_route,
            "serve": remote if web_mode == WEB_MODE_SERVE else empty_route,
            "last_error": self._last_error,
        }
