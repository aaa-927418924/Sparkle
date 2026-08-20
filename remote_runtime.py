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
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from remote_auth import AuthStore, get_mcp_auth_store


REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 8001
MAIN_PORT = 8000
REMOTE_TARGET = f"http://{REMOTE_HOST}:{REMOTE_PORT}"
MAIN_TARGET = f"http://{REMOTE_HOST}:{MAIN_PORT}"
ANDROID_WEB_HTTPS_PORT = 443
MCP_FUNNEL_HTTPS_PORT = 8443
# Kept as a compatibility alias for callers that used the pre-split route
# name. Remote MCP now uses Funnel on this port, while Android Web uses 443.
SERVE_WEB_HTTPS_PORT = MCP_FUNNEL_HTTPS_PORT
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


def _normalize_mcp_public_url(value: Optional[str]) -> Optional[str]:
    """Normalize the configured MCP URL without inventing a route port.

    Funnel Web uses the default HTTPS port 443. Serve Web mode uses the
    explicit 8443 URL, so a configured non-default port must be preserved.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return raw
        netloc = parsed.netloc
        return urlunsplit((parsed.scheme, netloc, "/mcp", "", ""))
    except ValueError:
        return raw


class RemoteAccessManager:
    """Own the local authenticated gateway and its Funnel/Serve route."""

    def __init__(
        self,
        auth_store: Optional[AuthStore] = None,
        main_port: int = MAIN_PORT,
        mcp_auth_store: Optional[AuthStore] = None,
    ) -> None:
        self.auth_store = auth_store or AuthStore()
        self.mcp_auth_store = mcp_auth_store or get_mcp_auth_store()
        self.main_target = f"http://{REMOTE_HOST}:{int(main_port)}"
        self._lock = threading.RLock()
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._mcp_runtime = None
        self._last_error: Optional[str] = None
        self._funnel_cache: Optional[dict[str, Any]] = None
        self._funnel_cache_at = 0.0

    def _any_enabled(self) -> bool:
        return self.auth_store.is_enabled() or self.mcp_auth_store.is_enabled()

    def _reset_mcp_oauth(self) -> None:
        with self._lock:
            runtime = self._mcp_runtime
        revoke_all = getattr(runtime, "revoke_all", None) if runtime is not None else None
        if callable(revoke_all):
            revoke_all()

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
        # Compatibility name: Serve Web is now the Android/tailnet route on
        # HTTPS 443 and proxies the main application directly.
        return self._status_for_target("serve", self.main_target, ANDROID_WEB_HTTPS_PORT)

    def _mcp_route_port(self, mode: Optional[str] = None) -> int:
        """Return the active MCP HTTPS port for the selected Web mode.

        Funnel Web already proxies the authenticated remote gateway on 443,
        so the initial Remote MCP flow shares that public route. When Web is
        switched to Serve, 443 must point at the desktop app and MCP moves to
        the separate public Funnel on 8443.
        """
        selected = mode or self._configured_web_mode()
        return ANDROID_WEB_HTTPS_PORT if selected == WEB_MODE_FUNNEL else MCP_FUNNEL_HTTPS_PORT

    def _mcp_route_is_shared(self, mode: Optional[str] = None) -> bool:
        return (
            self.mcp_auth_store.is_enabled()
            and self.auth_store.is_enabled()
            and (mode or self._configured_web_mode()) == WEB_MODE_FUNNEL
        )

    def _mcp_route_status(self) -> dict[str, Any]:
        """Return the MCP route on Funnel HTTPS 443 or 8443 as appropriate."""
        return self._status_for_target("funnel", REMOTE_TARGET, self._mcp_route_port())

    def _web_route_status(self, mode: Optional[str] = None) -> dict[str, Any]:
        """Return the Android/Web route without inspecting the MCP port."""
        selected = mode or self._configured_web_mode()
        if selected == WEB_MODE_SERVE:
            return self._status_for_target("serve", self.main_target, ANDROID_WEB_HTTPS_PORT)
        return self._status_for_target("funnel", REMOTE_TARGET, ANDROID_WEB_HTTPS_PORT)

    def _configured_web_mode(self) -> str:
        mode = self.auth_store.get_remote_mode()
        return mode if mode in WEB_MODES else WEB_MODE_FUNNEL

    def _web_status(self, mode: Optional[str] = None) -> dict[str, Any]:
        # Keep the old method as the API-facing compatibility point. New code
        # uses the explicit web_route/mcp_route fields in status().
        return self._web_route_status(mode)

    def _port_status(self, port: int) -> dict[str, Any]:
        """Inspect one HTTPS port without confusing Serve with Funnel.

        Tailscale versions differ in whether Serve/Funnel JSON includes the
        other command's configuration. Query both and use the first route
        found. The route target is what matters for conflict protection; the
        command used to configure it is selected explicitly when starting or
        stopping the route.
        """
        available_empty: Optional[dict[str, Any]] = None
        unavailable: Optional[dict[str, Any]] = None
        for command in ("serve", "funnel"):
            status = self._status_for_target(command, REMOTE_TARGET, port)
            if not status.get("available"):
                unavailable = status
                continue
            if status.get("active"):
                return status
            if available_empty is None:
                available_empty = status
        return available_empty or unavailable or {
            "available": False,
            "active": False,
            "target": None,
            "public_url": None,
            "error": "Tailscaleの状態を確認できません。",
        }

    def _start_route(
        self,
        command: str,
        target: str,
        port: int,
        label: str,
    ) -> dict[str, Any]:
        """Configure one Sparkle route while leaving every other port intact."""
        current = self._port_status(port)
        if not current.get("available"):
            return {"ok": False, "status": current, "error": current.get("error")}
        if current.get("active") and current.get("target") == "other":
            return {
                "ok": False,
                "status": current,
                "error": f"TailscaleのHTTPS {port}番ポートに別の設定があります。先にその設定を解除してください。",
            }

        ok, stdout, stderr = self._run_cli(
            [command, "--bg", f"--https={port}", "--yes", target]
        )
        if not ok:
            return {
                "ok": False,
                "status": current,
                "error": self._cli_error(stderr or stdout),
            }

        self._funnel_cache = None
        verified = self._status_for_target(command, target, port)
        if verified.get("available") and verified.get("active"):
            if verified.get("target") != ("remote" if target == REMOTE_TARGET else "main"):
                return {
                    "ok": False,
                    "status": verified,
                    "error": f"{label}の転送先がSparkleの想定するサービスではありません。",
                }
        elif not verified.get("available"):
            verified = {
                **verified,
                "configured": True,
                "warning": f"{label}の設定は完了しましたが、現在の状態を確認できません。",
            }
        else:
            return {
                "ok": False,
                "status": verified,
                "error": f"{label}の設定後に転送先を確認できませんでした。",
            }
        return {"ok": True, "status": verified}

    def _stop_route(
        self,
        preferred_command: str,
        target: str,
        port: int,
        current: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """Stop only the specified Sparkle route on one HTTPS port."""
        if not current.get("available"):
            return False, current.get("error") or "Tailscaleの状態を確認できません。"
        if not current.get("active"):
            return True, None
        expected_target = "remote" if target == REMOTE_TARGET else "main"
        if current.get("target") != expected_target:
            return False, f"TailscaleのHTTPS {port}番ポートに別の設定があります。先にその設定を解除してください。"

        commands = [preferred_command, "funnel" if preferred_command == "serve" else "serve"]
        last_error: Optional[str] = None
        for command in commands:
            ok, stdout, stderr = self._run_cli(
                [command, f"--https={port}", "--yes", target, "off"]
            )
            if ok:
                self._funnel_cache = None
                remaining = self._port_status(port)
                if not remaining.get("available") or not remaining.get("active"):
                    return True, None
                # Some Tailscale versions require the matching command when
                # an existing route was configured by the other command.
                if remaining.get("target") != expected_target:
                    return True, None
            else:
                last_error = self._cli_error(stderr or stdout)
        return False, last_error or "Tailscaleの公開ルートを停止できませんでした。"

    def _configured_mcp_url(self) -> Optional[str]:
        configured = _normalize_mcp_public_url(os.environ.get("SPARKLE_MCP_PUBLIC_URL"))
        if not configured:
            return None
        try:
            parsed = urlsplit(configured)
            route_port = self._mcp_route_port()
            configured_port = parsed.port
            route_switch_ports = {ANDROID_WEB_HTTPS_PORT, MCP_FUNNEL_HTTPS_PORT}
            if configured_port is None or configured_port in route_switch_ports:
                hostname = parsed.hostname or ""
                if ":" in hostname and not hostname.startswith("["):
                    hostname = f"[{hostname}]"
                netloc = hostname
                if route_port != ANDROID_WEB_HTTPS_PORT:
                    netloc = f"{hostname}:{route_port}"
                configured = urlunsplit(
                    (parsed.scheme, netloc, "/mcp", "", "")
                )
        except ValueError:
            pass
        return configured

    def _tailscale_dns_name(self) -> Optional[str]:
        """Read this node's MagicDNS name without changing Tailscale state."""
        ok, stdout, _ = self._run_cli(["status", "--json"])
        if not ok:
            return None
        try:
            parsed = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            return None
        self_info = parsed.get("Self") if isinstance(parsed, dict) else None
        dns_name = self_info.get("DNSName") if isinstance(self_info, dict) else None
        if not isinstance(dns_name, str):
            return None
        value = dns_name.strip().rstrip(".")
        return value or None

    def _mcp_public_url(self, route: Optional[dict[str, Any]] = None) -> Optional[str]:
        configured = self._configured_mcp_url()
        if configured:
            return configured
        candidate = route or self._mcp_route_status()
        public_url = candidate.get("public_url") if isinstance(candidate, dict) else None
        if isinstance(public_url, str) and public_url:
            return f"{public_url.rstrip('/')}/mcp"
        dns_name = self._tailscale_dns_name()
        if dns_name:
            port = self._mcp_route_port()
            suffix = "" if port == 443 else f":{port}"
            return f"https://{dns_name}{suffix}/mcp"
        return None

    def _start_remote_server(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            try:
                import uvicorn
                from main import app
                from remote_gateway import RemoteGateway

                gateway = RemoteGateway(
                    app,
                    self.auth_store,
                    mcp_auth_store=self.mcp_auth_store,
                    mcp_public_url=self._mcp_public_url(),
                )
                config = uvicorn.Config(
                    gateway,
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
            self._mcp_runtime = gateway.mcp_runtime
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
        with self._lock:
            self._mcp_runtime = None

    def _prepare_serve_switch(self) -> tuple[bool, Optional[str]]:
        # Compatibility helper retained for callers from the previous route
        # implementation. Route changes are now port-scoped and never reset
        # the whole Serve configuration.
        status = self._port_status(ANDROID_WEB_HTTPS_PORT)
        if not status.get("available"):
            return False, status.get("error") or "Tailscaleの状態を確認できません。"
        if status.get("active") and status.get("target") == "other":
            return False, "TailscaleのHTTPS 443番ポートに別の設定があります。先にその設定を解除してください。"
        return True, None

    def _stop_serve_web_route(self) -> tuple[bool, Optional[str]]:
        current = self._port_status(ANDROID_WEB_HTTPS_PORT)
        if not current.get("active"):
            return (True, None) if current.get("available") else (
                False,
                current.get("error") or "Tailscaleの状態を確認できません。",
            )
        target = REMOTE_TARGET if current.get("target") == "remote" else self.main_target
        return self._stop_route(
            "serve",
            target,
            ANDROID_WEB_HTTPS_PORT,
            current,
        )

    def _restore_default_serve_route(self) -> None:
        # Kept as a no-op compatibility hook. The Android Serve route is
        # started explicitly by _start_web_route and is never restored by a
        # global Serve/Funnel reset.
        return None

    def _start_serve_web_route(self) -> dict[str, Any]:
        return self._start_route(
            "serve",
            self.main_target,
            ANDROID_WEB_HTTPS_PORT,
            "Android向けTailscale Serve",
        )

    def _start_funnel_route(self) -> dict[str, Any]:
        return self._start_route(
            "funnel",
            REMOTE_TARGET,
            ANDROID_WEB_HTTPS_PORT,
            "外部Web向けTailscale Funnel",
        )

    def _start_mcp_route(self) -> dict[str, Any]:
        port = self._mcp_route_port()
        label = "Remote MCP向けTailscale Funnel"
        if port == ANDROID_WEB_HTTPS_PORT and self.auth_store.is_enabled():
            label = "Remote MCP共有Funnel"
        return self._start_route(
            "funnel",
            REMOTE_TARGET,
            port,
            label,
        )

    def _start_web_route(self) -> dict[str, Any]:
        if self._configured_web_mode() == WEB_MODE_SERVE:
            return self._start_serve_web_route()
        return self._start_funnel_route()

    def _start_enabled_routes(self) -> dict[str, Any]:
        """Start each enabled feature on its own Tailscale HTTPS port."""
        if self.auth_store.is_enabled():
            web_result = self._start_web_route()
            if not web_result.get("ok"):
                return web_result
        if self.mcp_auth_store.is_enabled():
            mcp_result = self._start_mcp_route()
            if not mcp_result.get("ok"):
                return mcp_result
            legacy_ok, legacy_error = self._stop_legacy_mcp_route()
            if not legacy_ok:
                return {"ok": False, "status": self.status(), "error": legacy_error}
        return {"ok": True, "status": self.status()}

    def enable(self) -> dict[str, Any]:
        key = self.auth_store.enable()
        if not self._start_remote_server():
            return {
                "ok": False,
                "access_key": key,
                "status": self.status(),
                "error": self._last_error,
            }
        result = self._start_enabled_routes()
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

    def enable_mcp(self) -> dict[str, Any]:
        """Enable Remote MCP with a credential independent from Remote Web."""

        key = self.mcp_auth_store.enable()
        self._reset_mcp_oauth()
        if not self._start_remote_server():
            return {
                "ok": False,
                "access_key": key,
                "status": self.status(),
                "error": self._last_error,
            }
        result = self._start_enabled_routes()
        self._last_error = result.get("error") if not result.get("ok") else None
        return {
            "ok": bool(result.get("ok")),
            "access_key": key,
            "status": self.status(),
            "error": result.get("error"),
        }

    def retry(self) -> dict[str, Any]:
        if not self._any_enabled():
            return {
                "ok": False,
                "status": self.status(),
                "error": "先に外部WebアクセスまたはRemote MCPを有効にしてください。",
            }
        if not self._start_remote_server():
            return {"ok": False, "status": self.status(), "error": self._last_error}
        result = self._start_enabled_routes()
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

        mcp_enabled = self.mcp_auth_store.is_enabled()
        previous_mcp_port = self._mcp_route_port(previous)
        next_mcp_port = self._mcp_route_port(normalized)
        if mcp_enabled and previous_mcp_port != next_mcp_port:
            # A Funnel Web route on 443 is shared by Web and MCP. Moving to
            # Serve must leave that route for the Web app and start MCP on
            # 8443; moving back removes the old 8443 route first.
            if not self._mcp_route_is_shared(previous):
                current = self._port_status(previous_mcp_port)
                if current.get("active"):
                    stopped, error = self._stop_route(
                        "funnel",
                        REMOTE_TARGET,
                        previous_mcp_port,
                        current,
                    )
                    if not stopped:
                        self._last_error = error
                        return {"ok": False, "status": self.status(), "error": error}

            # The MCP OAuth metadata contains the public resource URL. Restart
            # the gateway when its public port changes so discovery cannot keep
            # advertising the previous route.
            self._stop_remote_server()

        self.auth_store.set_remote_mode(normalized)
        if self.auth_store.is_enabled() or mcp_enabled:
            if not self._start_remote_server():
                return {"ok": False, "status": self.status(), "error": self._last_error}

        result = {"ok": True}
        if self.auth_store.is_enabled():
            result = self._start_web_route()
        if result.get("ok") and mcp_enabled:
            result = self._start_mcp_route()
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

    def rotate_mcp(self) -> dict[str, Any]:
        if not self.mcp_auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "先にRemote MCPを有効にしてください。"}
        key = self.mcp_auth_store.rotate_access_key()
        self._reset_mcp_oauth()
        return {"ok": True, "access_key": key, "status": self.status()}

    def revoke_mcp_all(self) -> dict[str, Any]:
        if not self.mcp_auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "Remote MCPは有効になっていません。"}
        self.mcp_auth_store.revoke_all()
        self._reset_mcp_oauth()
        return {"ok": True, "status": self.status()}

    def _stop_public_route(self) -> tuple[bool, Optional[str]]:
        if self._mcp_route_is_shared():
            return True, None
        current = self._port_status(ANDROID_WEB_HTTPS_PORT)
        if not current.get("available"):
            return False, current.get("error") or "Tailscaleの状態を確認できません。"
        if not current.get("active"):
            return True, None
        if current.get("target") == "other":
            return False, "TailscaleのHTTPS 443番ポートに別の設定があります。先にその設定を解除してください。"
        target = REMOTE_TARGET if current.get("target") == "remote" else self.main_target
        preferred = "serve" if self._configured_web_mode() == WEB_MODE_SERVE else "funnel"
        return self._stop_route(preferred, target, ANDROID_WEB_HTTPS_PORT, current)

    def _stop_mcp_route(self) -> tuple[bool, Optional[str]]:
        if self._mcp_route_is_shared():
            return True, None
        port = self._mcp_route_port()
        current = self._port_status(port)
        if not current.get("available"):
            return False, current.get("error") or "Tailscaleの状態を確認できません。"
        if not current.get("active"):
            return True, None
        if current.get("target") != "remote":
            return False, f"TailscaleのMCP用HTTPS {port}番ポートに別の設定があります。先にその設定を解除してください。"
        return self._stop_route(
            "funnel",
            REMOTE_TARGET,
            port,
            current,
        )

    def _stop_legacy_mcp_route(self) -> tuple[bool, Optional[str]]:
        """Remove the old 8443 MCP route after switching Funnel Web to 443."""
        if self._mcp_route_port() != ANDROID_WEB_HTTPS_PORT:
            return True, None
        current = self._port_status(MCP_FUNNEL_HTTPS_PORT)
        if not current.get("available"):
            # Cleanup is best-effort; the active 443 route is already valid.
            return True, None
        if not current.get("active") or current.get("target") != "remote":
            return True, None
        return self._stop_route(
            "funnel",
            REMOTE_TARGET,
            MCP_FUNNEL_HTTPS_PORT,
            current,
        )

    def disable(self) -> dict[str, Any]:
        if not self.auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "外部Webアクセスは有効になっていません。"}
        mcp_enabled = self.mcp_auth_store.is_enabled()
        stopped, error = self._stop_public_route()
        if not stopped:
            self._last_error = error
            return {"ok": False, "status": self.status(), "error": error}
        self.auth_store.disable()
        if not mcp_enabled:
            self._stop_remote_server()
        self._last_error = None
        return {"ok": True, "status": self.status()}

    def disable_mcp(self) -> dict[str, Any]:
        if not self.mcp_auth_store.is_enabled():
            return {"ok": False, "status": self.status(), "error": "Remote MCPは有効になっていません。"}
        web_enabled = self.auth_store.is_enabled()
        stopped, error = self._stop_mcp_route()
        if not stopped:
            self._last_error = error
            return {"ok": False, "status": self.status(), "error": error}
        self.mcp_auth_store.disable()
        self._reset_mcp_oauth()
        if not web_enabled:
            self._stop_remote_server()
        self._last_error = None
        return {"ok": True, "status": self.status()}

    def start_on_launch(self) -> dict[str, Any]:
        if not self._any_enabled():
            return self.status()
        if not self._start_remote_server():
            return self.status()
        result = self._start_enabled_routes()
        self._last_error = result.get("error") if not result.get("ok") else None
        return self.status()

    def shutdown(self) -> None:
        with self._lock:
            web_enabled = self.auth_store.is_enabled()
            mcp_enabled = self.mcp_auth_store.is_enabled()
        if web_enabled and mcp_enabled and self._mcp_route_is_shared():
            current = self._port_status(ANDROID_WEB_HTTPS_PORT)
            if current.get("active"):
                self._stop_route(
                    "funnel",
                    REMOTE_TARGET,
                    ANDROID_WEB_HTTPS_PORT,
                    current,
                )
        else:
            if web_enabled:
                self._stop_public_route()
            if mcp_enabled:
                self._stop_mcp_route()
        self._stop_remote_server()

    def status(self) -> dict[str, Any]:
        web_enabled = self.auth_store.is_enabled()
        mcp_enabled = self.mcp_auth_store.is_enabled()
        enabled = web_enabled or mcp_enabled
        web_mode = self._configured_web_mode()
        empty_route = {
            "available": True,
            "active": False,
            "target": None,
            "public_url": None,
        }
        web_route = self._web_status(web_mode) if web_enabled else dict(empty_route)
        mcp_route = self._mcp_route_status() if mcp_enabled else dict(empty_route)

        # Legacy fields remain available for older settings pages. New clients
        # should use web_route for Android/Web and mcp_route for Remote MCP.
        remote = mcp_route if mcp_enabled else (
            web_route if web_enabled and web_mode == WEB_MODE_FUNNEL else dict(empty_route)
        )
        configured_mcp_url = self._configured_mcp_url()
        if mcp_enabled and not configured_mcp_url:
            configured_mcp_url = self._mcp_public_url(mcp_route)
        return {
            "mode": web_mode if web_enabled else "tailscale",
            "web_mode": web_mode,
            "auth": self.auth_store.status(),
            "mcp_auth": self.mcp_auth_store.status(),
            "remote_server": bool(self._thread and self._thread.is_alive()),
            "mcp_url": configured_mcp_url,
            "web_route": web_route,
            "android": web_route,
            "mcp_route": mcp_route,
            "remote": remote,
            "funnel": web_route if web_enabled and web_mode == WEB_MODE_FUNNEL else dict(empty_route),
            "serve": web_route if web_enabled and web_mode == WEB_MODE_SERVE else dict(empty_route),
            "last_error": self._last_error,
        }
