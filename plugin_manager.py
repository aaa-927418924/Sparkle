"""Safe local storage and lifecycle helpers for Sparkle plugins."""

from __future__ import annotations

import json
import io
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib
from contextlib import contextmanager
from functools import wraps
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Iterator

from paths import get_plugin_data_dir, get_plugins_dir, get_resource_dir


PLUGIN_API_VERSION = 4
SUPPORTED_PLUGIN_API_VERSIONS = {1, 2, 3, 4}
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 40 * 1024 * 1024
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_FILE_COUNT = 256
MAX_MANIFEST_BYTES = 128 * 1024
MAX_PANEL_BYTES = 2 * 1024 * 1024
MAX_STORAGE_BYTES = 2 * 1024 * 1024
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
COLOR_PATTERN = re.compile(
    r"^(?:#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?|"
    r"rgba?\(\s*(?:\d{1,3}%?\s*,\s*){2}\d{1,3}%?"
    r"(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\))$"
)

THEME_COLOR_PROPERTIES = {
    "background": "--bg",
    "surface": "--surface",
    "surfaceRaised": "--surface-raised",
    "surfaceHover": "--surface-hover",
    "surfaceActive": "--surface-active",
    "sidebar": "--sidebar-bg",
    "border": "--border",
    "borderStrong": "--border-strong",
    "text": "--text",
    "muted": "--muted",
    "accent": "--accent",
    "accentSoft": "--accent-soft",
}
ALLOWED_PLUGIN_TYPES = {"theme", "feature"}
CLIP_PROJECT_DATA_PERMISSIONS = {
    "clips.read",
    "clips.write",
    "clips.delete",
    "projects.read",
    "projects.write",
    "projects.delete",
}
NOTES_TASK_DATA_PERMISSIONS = {
    "notes.read",
    "notes.write",
    "notes.delete",
    "tasks.read",
    "tasks.write",
    "tasks.delete",
}
API_V4_PERMISSIONS = {
    *NOTES_TASK_DATA_PERMISSIONS,
    "ai.request",
    "network.request",
}
DATA_PERMISSIONS = CLIP_PROJECT_DATA_PERMISSIONS | NOTES_TASK_DATA_PERMISSIONS
ALLOWED_PERMISSIONS = {
    "storage",
    "notifications",
    "ui.customize",
    "ai.request",
    "network.request",
    *DATA_PERMISSIONS,
}
ALLOWED_SIDEBAR_ICONS = {
    "home",
    "tasks",
    "projects",
    "puzzle",
    "game",
    "star",
    "sparkles",
    "book",
    "calendar",
    "calculator",
    "settings",
}
UI_HIDE_TARGETS = {
    "sidebar.home",
    "sidebar.memo",
    "sidebar.projects",
    "sidebar.profile",
    "home.search",
    "home.sort",
    "home.categories",
    "home.clips",
    "notes.status-tabs",
    "notes.task-list",
    "notes.memo-list",
    "notes.new-note",
    "projects.list",
    "projects.create",
    "profile.details",
    "profile.picks",
    "settings.category.general",
    "settings.category.theme",
    "settings.category.connections",
    "settings.category.ai",
    "settings.category.advanced",
}
UI_ORDER_TARGETS = {
    "sidebar.primary": {"home", "memo", "projects"},
    "settings.categories": {"general", "theme", "connections", "ai", "advanced", "plugins"},
}
UI_STYLE_VALUE_TYPES = {
    "accent": "color",
    "background": "color",
    "color": "color",
    "border": "color",
    "margin": "length",
    "padding": "length",
    "width": "length",
    "height": "length",
    "radius": "length",
    "fontSize": "length",
    "opacity": "number",
}
UI_LENGTH_PATTERN = re.compile(r"^(?:0|\d+(?:\.\d+)?(?:px|rem|em|%|vw|vh))$")
UI_NUMBER_PATTERN = re.compile(r"^(?:0|1|0?\.\d+)$")
RESERVED_PLUGIN_IDS = {"manager-state", "manager-state-json"}
STATE_FILENAME = "manager-state.json"
SKILL_ID = "sparkle-plugin-author"
SKILL_VERSION = "2.1.0"
SKILL_MARKER = ".sparkle-managed.json"
PLUGIN_LOCK = RLock()
ENVIRONMENT_PATH_PATTERN = re.compile(r"%([^%]+)%|\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


class PluginError(ValueError):
    """A plugin package or lifecycle request is invalid."""


class PluginPermissionRequired(PluginError):
    """A plugin requested an operation whose permission has not been granted."""

    def __init__(self, permission: str):
        self.permission = permission
        super().__init__(f"この操作には「{permission}」権限が必要です。")


def _serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with PLUGIN_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _resolve_plugins_dir(directory: Path | None = None) -> Path:
    root = Path(directory) if directory is not None else get_plugins_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _state_path(directory: Path | None = None) -> Path:
    return _resolve_plugins_dir(directory) / STATE_FILENAME


def _read_state(directory: Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"plugins": {}, "active_theme": None}
    if not isinstance(value, dict):
        return {"plugins": {}, "active_theme": None}
    plugins = value.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
    return {
        "plugins": plugins,
        "active_theme": value.get("active_theme")
        if isinstance(value.get("active_theme"), str)
        else None,
    }


def _write_state(state: dict[str, Any], directory: Path | None = None) -> None:
    path = _state_path(directory)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _valid_plugin_id(plugin_id: str) -> bool:
    return (
        isinstance(plugin_id, str)
        and len(plugin_id) <= 64
        and PLUGIN_ID_PATTERN.fullmatch(plugin_id) is not None
        and plugin_id not in RESERVED_PLUGIN_IDS
    )


def _plugin_dir(plugin_id: str, directory: Path | None = None) -> Path:
    if not _valid_plugin_id(plugin_id):
        raise PluginError("プラグインIDが不正です。")
    root = _resolve_plugins_dir(directory)
    target = root / plugin_id
    if target.is_symlink():
        raise PluginError("プラグインの保存先が安全ではありません。")
    resolved = target.resolve()
    if resolved.parent != root:
        raise PluginError("プラグインの保存先が不正です。")
    return resolved


def _read_json(path: Path, max_bytes: int) -> Any:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise PluginError("プラグインファイルの形式またはサイズが不正です。")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError("プラグインのJSONファイルを読み込めません。") from exc


def _validate_theme_file(package_dir: Path) -> dict[str, Any]:
    theme = _read_json(package_dir / "theme.json", MAX_MANIFEST_BYTES)
    if not isinstance(theme, dict) or not isinstance(theme.get("colors"), dict):
        raise PluginError("theme.jsonにはcolorsオブジェクトが必要です。")
    colors = theme["colors"]
    if not colors or len(colors) > len(THEME_COLOR_PROPERTIES):
        raise PluginError("テーマ色は1色以上、許可された数以内で指定してください。")
    normalized: dict[str, str] = {}
    for key, value in colors.items():
        if key not in THEME_COLOR_PROPERTIES or not isinstance(value, str):
            raise PluginError("テーマに未対応の色プロパティがあります。")
        if len(value) > 40 or COLOR_PATTERN.fullmatch(value.strip()) is None:
            raise PluginError(f"テーマ色 {key} の値が不正です。HEXまたはRGB形式を使ってください。")
        normalized[key] = value.strip()
    return {"colors": normalized}


def _validate_ui_contributions(manifest: dict[str, Any], plugin_type: str) -> dict[str, Any]:
    contributions = manifest.get("contributes")
    if contributions is None:
        if "ui.customize" in manifest.get("permissions", []):
            raise PluginError("ui.customize権限にはcontributesの指定が必要です。")
        return {}
    if not isinstance(contributions, dict) or not contributions:
        raise PluginError("contributesは1つ以上のUI寄与を含むオブジェクトにしてください。")
    if plugin_type != "feature":
        raise PluginError("UI寄与は機能プラグインでのみ使用できます。")
    if "ui.customize" not in manifest.get("permissions", []):
        raise PluginError("UI寄与にはui.customize権限が必要です。")
    if set(contributions) - {"sidebar", "project_action", "ui"}:
        raise PluginError("未対応のプラグイン寄与が指定されています。")

    normalized: dict[str, Any] = {}
    sidebar = contributions.get("sidebar")
    if sidebar is not None:
        if not isinstance(sidebar, dict) or set(sidebar) != {"label", "icon"}:
            raise PluginError("contributes.sidebarにはlabelとiconを指定してください。")
        label = sidebar.get("label")
        icon = sidebar.get("icon")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40:
            raise PluginError("サイドバー項目のlabelは1〜40文字で指定してください。")
        if not isinstance(icon, str) or icon not in ALLOWED_SIDEBAR_ICONS:
            raise PluginError("サイドバー項目のiconが未対応です。")
        normalized["sidebar"] = {"label": label.strip(), "icon": icon}

    project_action = contributions.get("project_action")
    if project_action is not None:
        if not isinstance(project_action, dict) or set(project_action) != {"label", "icon"}:
            raise PluginError("contributes.project_actionにはlabelとiconを指定してください。")
        label = project_action.get("label")
        icon = project_action.get("icon")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40:
            raise PluginError("プロジェクトボタンのlabelは1〜40文字で指定してください。")
        if not isinstance(icon, str) or icon not in ALLOWED_SIDEBAR_ICONS:
            raise PluginError("プロジェクトボタンのiconが未対応です。")
        normalized["project_action"] = {"label": label.strip(), "icon": icon}

    ui = contributions.get("ui")
    if ui is not None:
        if not isinstance(ui, dict) or not ui or set(ui) - {"hide", "order", "styles"}:
            raise PluginError("contributes.uiに未対応の項目があります。")
        normalized_ui: dict[str, Any] = {}

        hide = ui.get("hide", [])
        if not isinstance(hide, list) or len(hide) > len(UI_HIDE_TARGETS):
            raise PluginError("contributes.ui.hideの形式が不正です。")
        if any(not isinstance(target, str) or target not in UI_HIDE_TARGETS for target in hide):
            raise PluginError("非表示にできないUI IDが指定されています。")
        if len(set(hide)) != len(hide):
            raise PluginError("contributes.ui.hideに重複があります。")
        if hide:
            normalized_ui["hide"] = sorted(hide)

        order = ui.get("order", {})
        if not isinstance(order, dict) or set(order) - set(UI_ORDER_TARGETS):
            raise PluginError("contributes.ui.orderのグループが未対応です。")
        normalized_order: dict[str, list[str]] = {}
        for group, values in order.items():
            if not isinstance(values, list) or not values or len(values) > 64:
                raise PluginError("並び替えの項目数が不正です。")
            allowed = set(UI_ORDER_TARGETS[group])
            if group == "sidebar.primary":
                for value in values:
                    if isinstance(value, str) and value.startswith("plugin:"):
                        plugin_id = value.removeprefix("plugin:")
                        if _valid_plugin_id(plugin_id):
                            allowed.add(value)
            if any(not isinstance(value, str) or value not in allowed for value in values):
                raise PluginError(f"{group}に未対応の並び替えIDがあります。")
            if len(set(values)) != len(values):
                raise PluginError(f"{group}に重複した並び替えIDがあります。")
            normalized_order[group] = list(values)
        if normalized_order:
            normalized_ui["order"] = normalized_order

        styles = ui.get("styles", {})
        if not isinstance(styles, dict) or len(styles) > len(UI_HIDE_TARGETS):
            raise PluginError("contributes.ui.stylesの形式が不正です。")
        normalized_styles: dict[str, dict[str, str]] = {}
        for target, properties in styles.items():
            if target not in UI_HIDE_TARGETS or not isinstance(properties, dict) or not properties:
                raise PluginError("スタイル対象には許可されたUI IDとプロパティを指定してください。")
            if set(properties) - set(UI_STYLE_VALUE_TYPES):
                raise PluginError(f"{target}に未対応のスタイルプロパティがあります。")
            normalized_properties: dict[str, str] = {}
            for property_name, raw_value in properties.items():
                if not isinstance(raw_value, str) or len(raw_value.strip()) > 80:
                    raise PluginError("UIスタイルの値が不正です。")
                value = raw_value.strip()
                value_type = UI_STYLE_VALUE_TYPES[property_name]
                valid = (
                    COLOR_PATTERN.fullmatch(value) is not None
                    if value_type == "color"
                    else UI_LENGTH_PATTERN.fullmatch(value) is not None
                    if value_type == "length"
                    else UI_NUMBER_PATTERN.fullmatch(value) is not None
                )
                if not valid:
                    raise PluginError(f"{target}の{property_name}の値が未対応形式です。")
                normalized_properties[property_name] = value
            normalized_styles[target] = normalized_properties
        if normalized_styles:
            normalized_ui["styles"] = normalized_styles
        if not normalized_ui:
            raise PluginError("contributes.uiに有効な寄与がありません。")
        normalized["ui"] = normalized_ui

    if not normalized:
        raise PluginError("contributesに有効な寄与がありません。")
    return normalized


def _validate_package_dir(
    package_dir: Path,
    *,
    allow_incompatible_api: bool = False,
) -> dict[str, Any]:
    manifest = _read_json(package_dir / "manifest.json", MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict):
        raise PluginError("manifest.jsonの内容が不正です。")
    plugin_id = manifest.get("id")
    if not _valid_plugin_id(plugin_id):
        raise PluginError("idには英小文字・数字・ハイフンの形式を指定してください。")
    if not package_dir.name.startswith(".import-") and package_dir.name != plugin_id:
        raise PluginError("保存フォルダー名とプラグインIDが一致しません。")
    name = manifest.get("name")
    description = manifest.get("description", "")
    version = manifest.get("version")
    plugin_type = manifest.get("type")
    api_version = manifest.get("api_version")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise PluginError("プラグイン名が不正です。")
    if not isinstance(description, str) or len(description) > 1000:
        raise PluginError("プラグインの説明が長すぎます。")
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise PluginError("versionは例 1.0.0 の形式で指定してください。")
    if not isinstance(plugin_type, str) or plugin_type not in ALLOWED_PLUGIN_TYPES:
        raise PluginError("typeはthemeまたはfeatureを指定してください。")
    if type(api_version) is not int or api_version < 1:
        raise PluginError("プラグインのAPIバージョンが不正です。")
    api_compatible = api_version in SUPPORTED_PLUGIN_API_VERSIONS
    if not allow_incompatible_api and not api_compatible:
        raise PluginError(f"このSparkleはプラグインAPI {PLUGIN_API_VERSION} に対応しています。")

    permissions = manifest.get("permissions", [])
    if not isinstance(permissions, list) or any(not isinstance(permission, str) for permission in permissions):
        raise PluginError("プラグイン権限の形式が不正です。")
    if api_compatible:
        if any(permission not in ALLOWED_PERMISSIONS for permission in permissions):
            raise PluginError("未対応のプラグイン権限が指定されています。")
        if len(set(permissions)) != len(permissions):
            raise PluginError("プラグイン権限が重複しています。")
        if api_version < 2 and ("ui.customize" in permissions or "contributes" in manifest):
            raise PluginError("UI寄与はプラグインAPI 2以降で使用できます。")
        if api_version < 4 and set(permissions) & API_V4_PERMISSIONS:
            raise PluginError("Notes, tasks, AI, and network permissions require plugin API 4.")
        if api_version < 3 and set(permissions) & CLIP_PROJECT_DATA_PERMISSIONS:
            raise PluginError("クリップ・プロジェクト権限はプラグインAPI 3以降で使用できます。")

    result = {
        "id": plugin_id,
        "name": name.strip(),
        "version": version,
        "description": description.strip(),
        "type": plugin_type,
        "api_version": api_version,
        "permissions": sorted(permissions),
    }
    if not api_compatible:
        result["permissions"] = []
        result["entry"] = "panel.html" if plugin_type == "feature" else None
        return result
    if plugin_type == "theme":
        result["theme"] = _validate_theme_file(package_dir)
    else:
        panel = package_dir / "panel.html"
        if panel.is_symlink() or not panel.is_file() or panel.stat().st_size > MAX_PANEL_BYTES:
            raise PluginError("機能プラグインには2MB以内のpanel.htmlが必要です。")
        result["entry"] = "panel.html"
    if api_version >= 2:
        contributions = _validate_ui_contributions(manifest, plugin_type)
        if contributions:
            priority = manifest.get("priority", 0)
            if type(priority) is not int or not 0 <= priority <= 1000:
                raise PluginError("priorityは0〜1000の整数で指定してください。")
            result["priority"] = priority
            result["contributes"] = contributions
        elif "priority" in manifest:
            raise PluginError("priorityはcontributesと一緒に指定してください。")
    return result


def _archive_member_path(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise PluginError("ZIP内に不正なパスがあります。")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginError("ZIP内に不正なパスがあります。")
    if any(
        ":" in part
        or part.endswith((".", " "))
        or len(part) > 128
        or len(part.encode("utf-8")) > 240
        for part in path.parts
    ):
        raise PluginError("ZIP内に移植できないファイル名があります。")
    if any(any(char in part for char in '<>"|?*') for part in path.parts):
        raise PluginError("ZIP内に移植できないファイル名があります。")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{number}" for number in range(1, 10))
    reserved.update(f"LPT{number}" for number in range(1, 10))
    if any(part.upper().split(".")[0] in reserved for part in path.parts):
        raise PluginError("ZIP内に予約済みのファイル名があります。")
    return path


@_serialized
def install_plugin_archive(
    archive_bytes: bytes | bytearray,
    directory: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(archive_bytes, (bytes, bytearray)) or not archive_bytes:
        raise PluginError("ZIPファイルが空です。")
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise PluginError("ZIPファイルは20MB以下にしてください。")
    root = _resolve_plugins_dir(directory)
    stage = root / f".import-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        try:
            archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
        except (zipfile.BadZipFile, OSError) as exc:
            raise PluginError("ZIPファイルを開けません。") from exc
        with archive:
            infos = archive.infolist()
            files = [info for info in infos if not info.is_dir()]
            if len(files) > MAX_FILE_COUNT or len(infos) > MAX_FILE_COUNT * 2:
                raise PluginError("ZIP内のファイル数が上限を超えています。")
            total_size = 0
            seen: set[str] = set()
            for info in infos:
                member = _archive_member_path(info.filename.rstrip("/"))
                key = member.as_posix().casefold()
                if key in seen:
                    raise PluginError("ZIP内に重複するファイルパスがあります。")
                seen.add(key)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode):
                    raise PluginError("ZIP内のシンボリックリンクは使用できません。")
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise PluginError("暗号化されたZIPは読み込めません。")
                if info.file_size > MAX_FILE_BYTES:
                    raise PluginError("ZIP内にサイズ上限を超えるファイルがあります。")
                total_size += info.file_size
                if total_size > MAX_UNPACKED_BYTES:
                    raise PluginError("ZIP展開後の合計サイズが上限を超えています。")
                if info.file_size > 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > 200:
                    raise PluginError("圧縮率が高すぎるファイルを含むZIPです。")

            expanded_size = 0
            for info in files:
                member = _archive_member_path(info.filename)
                target = stage.joinpath(*member.parts)
                resolved = target.resolve()
                if not resolved.is_relative_to(stage.resolve()):
                    raise PluginError("ZIPの展開先がプラグイン領域の外です。")
                target.parent.mkdir(parents=True, exist_ok=True)
                file_size = 0
                with archive.open(info, "r") as source, target.open("xb") as destination:
                    while chunk := source.read(64 * 1024):
                        file_size += len(chunk)
                        expanded_size += len(chunk)
                        if file_size > info.file_size or file_size > MAX_FILE_BYTES:
                            raise PluginError("ZIP内のファイルサイズ申告が不正です。")
                        if expanded_size > MAX_UNPACKED_BYTES:
                            raise PluginError("ZIP展開後の合計サイズが上限を超えています。")
                        destination.write(chunk)
                if file_size != info.file_size:
                    raise PluginError("ZIP内のファイルサイズ申告が不正です。")

        manifest = _validate_package_dir(stage)
        destination = _plugin_dir(manifest["id"], root)
        if destination.exists():
            raise PluginError("同じIDのプラグインがすでにあります。先に既存プラグインを削除してください。")
        os.replace(stage, destination)
        state = _read_state(root)
        state["plugins"].pop(manifest["id"], None)
        _write_state(state, root)
        return {**{key: value for key, value in manifest.items() if key != "theme"}, "enabled": False}
    except PluginError:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError, OSError, zlib.error) as exc:
        raise PluginError("ZIP内に破損または非対応のデータがあります。") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


@_serialized
def list_plugins(directory: Path | None = None) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    state = _read_state(root)
    entries: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if not candidate.is_dir() or candidate.is_symlink() or candidate.name.startswith("."):
            continue
        if not _valid_plugin_id(candidate.name):
            continue
        try:
            manifest = _validate_package_dir(candidate, allow_incompatible_api=True)
            active = state["plugins"].get(manifest["id"], {})
            enabled = bool(active.get("enabled")) if isinstance(active, dict) else False
            granted_permissions = _effective_granted_permissions(manifest, active)
            entries.append(
                {
                    key: value
                    for key, value in manifest.items()
                    if key != "theme"
                }
                | {
                    "enabled": enabled,
                    "granted_permissions": granted_permissions,
                    "compatible": manifest["api_version"] in SUPPORTED_PLUGIN_API_VERSIONS,
                    "active_theme": state.get("active_theme") == manifest["id"],
                }
            )
        except PluginError as exc:
            entries.append(
                {
                    "id": candidate.name,
                    "name": candidate.name,
                    "enabled": False,
                    "compatible": False,
                    "error": str(exc),
                }
            )
    return {"api_version": PLUGIN_API_VERSION, "plugins": entries}


@_serialized
def get_plugin_ui_state(directory: Path | None = None) -> dict[str, Any]:
    """Return the merged, reversible UI contributions from enabled plugins."""
    entries = list_plugins(directory)["plugins"]
    contributors = [
        plugin
        for plugin in entries
        if plugin.get("enabled")
        and plugin.get("compatible")
        and plugin.get("type") == "feature"
        and "ui.customize" in plugin.get("granted_permissions", [])
        and isinstance(plugin.get("contributes"), dict)
    ]
    contributors.sort(key=lambda plugin: (plugin.get("priority", 0), plugin["id"]))

    hidden: set[str] = set()
    order: dict[str, list[str]] = {}
    styles: dict[str, dict[str, str]] = {}
    sidebar_items: list[dict[str, str]] = []
    project_actions: list[dict[str, str]] = []
    for plugin in contributors:
        contributes = plugin["contributes"]
        sidebar = contributes.get("sidebar")
        if isinstance(sidebar, dict):
            sidebar_items.append(
                {
                    "plugin_id": plugin["id"],
                    "label": sidebar["label"],
                    "icon": sidebar["icon"],
                }
            )
        project_action = contributes.get("project_action")
        if isinstance(project_action, dict):
            project_actions.append(
                {
                    "plugin_id": plugin["id"],
                    "label": project_action["label"],
                    "icon": project_action["icon"],
                }
            )
        ui = contributes.get("ui", {})
        hidden.update(ui.get("hide", []))
        for group, values in ui.get("order", {}).items():
            order[group] = list(values)
        for target, properties in ui.get("styles", {}).items():
            styles.setdefault(target, {}).update(properties)

    return {
        "api_version": PLUGIN_API_VERSION,
        "hidden": sorted(hidden),
        "order": order,
        "styles": styles,
        "sidebar_items": sidebar_items,
        "project_actions": project_actions,
    }


@_serialized
def set_plugin_enabled(plugin_id: str, enabled: bool, directory: Path | None = None) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    plugin_dir = _plugin_dir(plugin_id, root)
    manifest = _validate_package_dir(plugin_dir)
    state = _read_state(root)
    plugins = state["plugins"]
    current = plugins.get(plugin_id, {})
    if not isinstance(current, dict):
        current = {}
    current["enabled"] = bool(enabled)
    plugins[plugin_id] = current
    if not enabled and state.get("active_theme") == plugin_id:
        state["active_theme"] = None
    _write_state(state, root)
    return {"id": plugin_id, "enabled": bool(enabled), "type": manifest["type"]}


def _effective_granted_permissions(
    manifest: dict[str, Any],
    plugin_state: Any,
) -> list[str]:
    requested = set(manifest.get("permissions", []))
    if isinstance(plugin_state, dict) and isinstance(plugin_state.get("granted_permissions"), list):
        granted = {
            permission
            for permission in plugin_state["granted_permissions"]
            if isinstance(permission, str)
        }
        return sorted(requested & granted)
    # Keep legacy API v1/v2 plugins working until the user explicitly revokes
    # their old manifest-declared grants. API v3 starts with no grants.
    if manifest.get("api_version", 1) < 3:
        return sorted(requested)
    return []


@_serialized
def set_plugin_permission_grant(
    plugin_id: str,
    permission: str,
    granted: bool,
    directory: Path | None = None,
) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    manifest = _validate_package_dir(_plugin_dir(plugin_id, root))
    if permission not in manifest.get("permissions", []):
        raise PluginError("このプラグインはその権限を要求していません。")
    state = _read_state(root)
    current = state["plugins"].get(plugin_id, {})
    if not isinstance(current, dict):
        current = {}
    permissions = set(_effective_granted_permissions(manifest, current))
    if granted:
        permissions.add(permission)
    else:
        permissions.discard(permission)
    current["granted_permissions"] = sorted(permissions)
    state["plugins"][plugin_id] = current
    _write_state(state, root)
    return {"id": plugin_id, "granted_permissions": sorted(permissions)}


@_serialized
def revoke_plugin_permissions(plugin_id: str, directory: Path | None = None) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    target = _plugin_dir(plugin_id, root)
    if not target.exists():
        raise PluginError("プラグインが見つかりません。")
    state = _read_state(root)
    current = state["plugins"].get(plugin_id, {})
    if not isinstance(current, dict):
        current = {}
    try:
        manifest = _validate_package_dir(target, allow_incompatible_api=True)
        previous = _effective_granted_permissions(manifest, current)
    except PluginError:
        previous = []
    if not previous and isinstance(current.get("granted_permissions"), list):
        previous = [item for item in current.get("granted_permissions", []) if isinstance(item, str)]
    current["granted_permissions"] = []
    state["plugins"][plugin_id] = current
    _write_state(state, root)
    return {"id": plugin_id, "granted_permissions": [], "revoked": len(previous)}


def _require_plugin_permission(
    plugin_id: str,
    permission: str,
    directory: Path | None = None,
) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    manifest = _validate_package_dir(_plugin_dir(plugin_id, root))
    state = _read_state(root)
    plugin_state = state["plugins"].get(plugin_id, {})
    if not isinstance(plugin_state, dict) or not bool(plugin_state.get("enabled")):
        raise PluginError("無効なプラグインはSparkleデータにアクセスできません。")
    if permission not in manifest.get("permissions", []):
        raise PluginError("このプラグインはその権限を要求していません。")
    if permission not in _effective_granted_permissions(manifest, plugin_state):
        raise PluginPermissionRequired(permission)
    return manifest


@contextmanager
def plugin_permission_guard(
    plugin_id: str,
    permission: str,
    directory: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Keep a permission grant stable for the full host operation."""
    with PLUGIN_LOCK:
        yield _require_plugin_permission(plugin_id, permission, directory)


@_serialized
def set_active_theme(plugin_id: str | None, directory: Path | None = None) -> dict[str, Any] | None:
    root = _resolve_plugins_dir(directory)
    state = _read_state(root)
    if plugin_id is None:
        state["active_theme"] = None
        _write_state(state, root)
        return None
    plugin_dir = _plugin_dir(plugin_id, root)
    manifest = _validate_package_dir(plugin_dir)
    if manifest["type"] != "theme":
        raise PluginError("テーマ以外のプラグインはテーマに設定できません。")
    plugin_state = state["plugins"].get(plugin_id, {})
    if not isinstance(plugin_state, dict) or not bool(plugin_state.get("enabled")):
        raise PluginError("テーマを有効にしてから適用してください。")
    state["active_theme"] = plugin_id
    _write_state(state, root)
    return get_active_theme(root)


@_serialized
def get_active_theme(directory: Path | None = None) -> dict[str, Any] | None:
    root = _resolve_plugins_dir(directory)
    state = _read_state(root)
    plugin_id = state.get("active_theme")
    plugin_state = state["plugins"].get(plugin_id, {}) if plugin_id else {}
    if not plugin_id or not isinstance(plugin_state, dict) or not bool(plugin_state.get("enabled")):
        return None
    try:
        plugin_dir = _plugin_dir(plugin_id, root)
        manifest = _validate_package_dir(plugin_dir)
    except PluginError:
        return None
    if manifest["type"] != "theme":
        return None
    return {
        "id": plugin_id,
        "name": manifest["name"],
        "colors": manifest["theme"]["colors"],
        "properties": THEME_COLOR_PROPERTIES,
    }


@_serialized
def remove_plugin(
    plugin_id: str,
    *,
    delete_data: bool = False,
    directory: Path | None = None,
) -> dict[str, Any]:
    root = _resolve_plugins_dir(directory)
    target = _plugin_dir(plugin_id, root)
    if not target.exists():
        raise PluginError("プラグインが見つかりません。")
    state = _read_state(root)
    state["plugins"].pop(plugin_id, None)
    if state.get("active_theme") == plugin_id:
        state["active_theme"] = None
    _write_state(state, root)
    shutil.rmtree(target)
    if delete_data:
        data_root = _plugin_data_root(directory)
        data_target = data_root / plugin_id
        if data_target.is_symlink() or data_target.resolve().parent != data_root:
            raise PluginError("プラグインデータの保存先が安全ではありません。")
        if data_target.exists():
            shutil.rmtree(data_target)
    return {"id": plugin_id, "removed": True, "data_deleted": bool(delete_data)}


@_serialized
def plugin_resource_path(
    plugin_id: str,
    relative_path: str,
    directory: Path | None = None,
) -> Path:
    plugin_dir = _plugin_dir(plugin_id, directory)
    state = _read_state(directory)
    if not bool(state["plugins"].get(plugin_id, {}).get("enabled")):
        raise PluginError("無効なプラグインのファイルは開けません。")
    manifest = _validate_package_dir(plugin_dir)
    if manifest["type"] != "feature":
        raise PluginError("テーマプラグインは画面を持ちません。")
    relative = _archive_member_path(relative_path)
    target = plugin_dir.joinpath(*relative.parts)
    resolved = target.resolve()
    if not resolved.is_relative_to(plugin_dir.resolve()) or target.is_symlink() or not target.is_file():
        raise PluginError("プラグインのリソースが見つからないか、安全ではありません。")
    if target.name in {"manifest.json", "theme.json"}:
        raise PluginError("プラグイン設定ファイルはリソースとして公開できません。")
    return resolved


def export_plugin_archive(plugin_id: str, directory: Path | None = None) -> bytes:
    plugin_dir = _plugin_dir(plugin_id, directory)
    _validate_package_dir(plugin_dir, allow_incompatible_api=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(plugin_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(plugin_dir)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise PluginError("プラグイン内にZIP上限を超えるファイルがあります。")
            archive.write(path, relative.as_posix())
    value = buffer.getvalue()
    if len(value) > MAX_ARCHIVE_BYTES:
        raise PluginError("作成したZIPがサイズ上限を超えています。")
    return value


def _validate_storage_key(key: str) -> None:
    if not isinstance(key, str) or not key or len(key) > 128 or "\x00" in key:
        raise PluginError("プラグインデータのキーが不正です。")


def _plugin_data_root(directory: Path | None = None) -> Path:
    data_root = Path(directory).parent / "plugin-data" if directory else get_plugin_data_dir()
    data_root.mkdir(parents=True, exist_ok=True)
    if data_root.is_symlink():
        raise PluginError("プラグインデータの保存先が安全ではありません。")
    return data_root.resolve()


def _plugin_storage_path(plugin_id: str, directory: Path | None = None) -> Path:
    if not _valid_plugin_id(plugin_id):
        raise PluginError("プラグインIDが不正です。")
    data_root = _plugin_data_root(directory)
    target_dir = data_root / plugin_id
    if target_dir.is_symlink():
        raise PluginError("プラグインデータの保存先が安全ではありません。")
    if target_dir.exists() and target_dir.resolve().parent != data_root:
        raise PluginError("プラグインデータの保存先が安全ではありません。")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "storage.json"
    if path.is_symlink() or path.resolve().parent != target_dir.resolve():
        raise PluginError("プラグインデータの保存先が安全ではありません。")
    return path


def _require_storage_permission(plugin_id: str, directory: Path | None) -> None:
    _require_plugin_permission(plugin_id, "storage", directory)


@_serialized
def get_plugin_storage(plugin_id: str, key: str, directory: Path | None = None) -> dict[str, Any]:
    _require_storage_permission(plugin_id, directory)
    _validate_storage_key(key)
    path = _plugin_storage_path(plugin_id, directory)
    try:
        if path.stat().st_size > MAX_STORAGE_BYTES:
            raise PluginError("プラグインデータがサイズ上限を超えています。")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value = {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError("プラグインデータを読み込めません。") from exc
    if not isinstance(value, dict):
        raise PluginError("プラグインデータの形式が不正です。")
    return {"key": key, "value": value.get(key)}


@_serialized
def put_plugin_storage(
    plugin_id: str,
    key: str,
    value: Any,
    directory: Path | None = None,
) -> dict[str, Any]:
    _require_storage_permission(plugin_id, directory)
    _validate_storage_key(key)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PluginError("プラグインデータはJSON形式で指定してください。") from exc
    if len(encoded.encode("utf-8")) > MAX_STORAGE_BYTES:
        raise PluginError("保存できるプラグインデータは1項目あたり2MBまでです。")
    path = _plugin_storage_path(plugin_id, directory)
    current: dict[str, Any] = {}
    if path.exists():
        current = _read_json(path, MAX_STORAGE_BYTES)
        if not isinstance(current, dict):
            raise PluginError("プラグインデータの形式が不正です。")
    current[key] = value
    serialized = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_STORAGE_BYTES:
        raise PluginError("プラグインデータの合計が2MBを超えています。")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"key": key, "value": value}


def _skill_source_dir(source_dir: Path | None = None) -> Path:
    source = Path(source_dir) if source_dir else get_resource_dir() / "skills" / SKILL_ID
    source = source.resolve()
    if not (source / "SKILL.md").is_file():
        raise PluginError("同梱されたプラグイン作成スキルが見つかりません。")
    return source


def get_agent_skill_targets(
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Path]:
    env = dict(os.environ if environ is None else environ)
    user_home = Path(home).expanduser() if home is not None else Path.home()

    def configured_path(value: str) -> Path:
        portable_env = {**env, "HOME": env.get("HOME", str(user_home))}
        portable_env.setdefault("USERPROFILE", str(user_home))

        def expand(match: re.Match[str]) -> str:
            name = next(group for group in match.groups() if group is not None)
            return portable_env.get(name, match.group(0))

        expanded = ENVIRONMENT_PATH_PATTERN.sub(expand, value.strip())
        if expanded == "~" or expanded.startswith(("~/", "~\\")):
            expanded = str(user_home) + expanded[1:]
        return Path(expanded)

    codex_home_value = env.get("CODEX_HOME", "").strip()
    codex_home = configured_path(codex_home_value) if codex_home_value else user_home / ".codex"
    xdg_value = env.get("XDG_CONFIG_HOME", "").strip()
    config_home = configured_path(xdg_value) if xdg_value else user_home / ".config"
    claude_config_value = env.get("CLAUDE_CONFIG_DIR", "").strip()
    claude_config = configured_path(claude_config_value) if claude_config_value else user_home / ".claude"
    return {
        "OpenCode": config_home / "opencode" / "skills" / SKILL_ID,
        "Codex": codex_home / "skills" / SKILL_ID,
        "Claude Code": claude_config / "skills" / SKILL_ID,
    }


def get_authoring_skill_status(
    *,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read the three managed skill locations without creating or changing files."""
    _skill_source_dir()
    results: list[dict[str, str]] = []
    for agent, target in get_agent_skill_targets(home=home, environ=environ).items():
        status = "missing"
        if target.is_symlink():
            status = "conflict"
        elif target.exists():
            marker = target / SKILL_MARKER
            skill_file = target / "SKILL.md"
            try:
                marker_value = json.loads(marker.read_text(encoding="utf-8"))
                if (
                    target.is_dir()
                    and skill_file.is_file()
                    and marker_value.get("owner") == "Sparkle"
                    and marker_value.get("skill") == SKILL_ID
                ):
                    status = "installed" if marker_value.get("version") == SKILL_VERSION else "outdated"
                else:
                    status = "conflict"
            except (OSError, ValueError, AttributeError):
                status = "conflict"
        results.append({"agent": agent, "status": status})
    return {
        "skill": SKILL_ID,
        "version": SKILL_VERSION,
        "all_installed": bool(results) and all(item["status"] == "installed" for item in results),
        "results": results,
    }


def _install_skill_for_target(source: Path, target: Path) -> str:
    if target.is_symlink():
        return "conflict"
    target.parent.mkdir(parents=True, exist_ok=True)
    managed = False
    if target.exists():
        marker = target / SKILL_MARKER
        try:
            marker_value = json.loads(marker.read_text(encoding="utf-8"))
            managed = marker_value.get("owner") == "Sparkle" and marker_value.get("skill") == SKILL_ID
        except (OSError, ValueError, AttributeError):
            managed = False
        if not managed:
            return "conflict"

    stage_parent = Path(tempfile.mkdtemp(prefix=".sparkle-skill-", dir=target.parent))
    stage = stage_parent / SKILL_ID
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    try:
        shutil.copytree(source, stage)
        (stage / SKILL_MARKER).write_text(
            json.dumps({"owner": "Sparkle", "skill": SKILL_ID, "version": SKILL_VERSION}),
            encoding="utf-8",
        )
        if managed:
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except OSError:
            if managed and backup.exists():
                os.replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return "updated" if managed else "installed"
    except OSError:
        return "failed"
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)
        if backup.exists() and not target.exists():
            try:
                os.replace(backup, target)
            except OSError:
                pass


def install_authoring_skill(
    *,
    source_dir: Path | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = _skill_source_dir(source_dir)
    results: list[dict[str, str]] = []
    for agent, target in get_agent_skill_targets(home=home, environ=environ).items():
        try:
            status = _install_skill_for_target(source, target)
        except OSError:
            status = "failed"
        results.append({"agent": agent, "status": status})
    return {"skill": SKILL_ID, "results": results}
