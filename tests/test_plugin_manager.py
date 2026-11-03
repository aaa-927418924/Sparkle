import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from plugin_manager import (
    PluginError,
    export_plugin_archive,
    get_active_theme,
    get_authoring_skill_status,
    get_agent_skill_targets,
    get_plugin_ui_state,
    get_plugin_storage,
    install_authoring_skill,
    install_plugin_archive,
    list_plugins,
    plugin_resource_path,
    put_plugin_storage,
    revoke_plugin_permissions,
    remove_plugin,
    set_plugin_permission_grant,
    set_active_theme,
    set_plugin_enabled,
)


def make_archive(manifest, *, theme=None, panel=None, assets=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        if theme is not None:
            archive.writestr("theme.json", json.dumps(theme))
        if panel is not None:
            archive.writestr("panel.html", panel)
        for name, content in (assets or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def theme_manifest(plugin_id="ocean-night", api_version=1):
    return {
        "id": plugin_id,
        "name": "Ocean Night",
        "version": "1.0.0",
        "api_version": api_version,
        "type": "theme",
        "description": "A portable dark theme",
        "permissions": [],
    }


def feature_manifest(plugin_id="personal-tool"):
    return {
        "id": plugin_id,
        "name": "Personal Tool",
        "version": "1.0.0",
        "api_version": 1,
        "type": "feature",
        "description": "An isolated personal panel",
        "permissions": ["storage", "notifications"],
    }


def data_feature_manifest(plugin_id="data-tool", *, api_version=3, permissions=None):
    return {
        "id": plugin_id,
        "name": "Data Tool",
        "version": "1.0.0",
        "api_version": api_version,
        "type": "feature",
        "description": "A feature plugin with explicit data permissions",
        "permissions": permissions or [
            "clips.read",
            "clips.write",
            "clips.delete",
            "projects.read",
            "projects.write",
            "projects.delete",
        ],
    }


def ui_feature_manifest(plugin_id="ui-tool", *, priority=0, contributes=None):
    manifest = {
        "id": plugin_id,
        "name": "UI Tool",
        "version": "1.0.0",
        "api_version": 2,
        "type": "feature",
        "description": "A feature plugin with optional UI contributions",
        "permissions": ["ui.customize"],
        "priority": priority,
    }
    if contributes is not None:
        manifest["contributes"] = contributes
    return manifest


class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name) / "Sparkle"
        self.plugins = self.base / "plugins"
        self.plugins.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_plugin_category_and_theme_runtime_are_loaded_by_frontend(self):
        root = Path(__file__).resolve().parents[1]
        settings = (root / "frontend" / "settings.html").read_text(encoding="utf-8")
        self.assertIn('data-plugin-category-button="plugins"', settings)
        self.assertIn('id="pluginSettingsPanel"', settings)
        self.assertIn('plugin-manager.js?v=plugin-manager-v3-permissions-v1', settings)
        self.assertIn('plugin-theme.js?v=plugin-theme-v1', settings)
        html_pages = tuple((root / "frontend").rglob("*.html"))
        self.assertTrue(html_pages)
        for page in html_pages:
            self.assertIn("plugin-theme.js", page.read_text(encoding="utf-8"), page.name)

    def test_theme_import_is_disabled_until_enabled_and_removal_clears_active_theme(self):
        archive = make_archive(
            theme_manifest(),
            theme={"colors": {"background": "#102030", "accent": "#80A0C0"}},
        )
        imported = install_plugin_archive(archive, self.plugins)
        self.assertEqual(imported["id"], "ocean-night")
        self.assertFalse(imported["enabled"])
        self.assertIsNone(get_active_theme(self.plugins))

        set_plugin_enabled("ocean-night", True, self.plugins)
        active = set_active_theme("ocean-night", self.plugins)
        self.assertEqual(active["colors"]["background"], "#102030")
        self.assertTrue(list_plugins(self.plugins)["plugins"][0]["active_theme"])

        remove_plugin("ocean-night", directory=self.plugins)
        self.assertIsNone(get_active_theme(self.plugins))
        self.assertEqual(list_plugins(self.plugins)["plugins"], [])

    def test_theme_rejects_css_and_script_injection(self):
        archive = make_archive(
            theme_manifest(),
            theme={"colors": {"background": "url(https://example.invalid/x)"}},
        )
        with self.assertRaises(PluginError):
            install_plugin_archive(archive, self.plugins)
        self.assertEqual(list_plugins(self.plugins)["plugins"], [])

    def test_feature_panel_is_hidden_until_enabled_and_assets_stay_in_package(self):
        archive = make_archive(
            feature_manifest(),
            panel="<h1>Private panel</h1><script src='assets/panel.js'></script>",
            assets={"assets/panel.js": "window.parent.postMessage({}, '*');"},
        )
        install_plugin_archive(archive, self.plugins)
        with self.assertRaises(PluginError):
            plugin_resource_path("personal-tool", "panel.html", self.plugins)
        set_plugin_enabled("personal-tool", True, self.plugins)
        panel = plugin_resource_path("personal-tool", "panel.html", self.plugins)
        asset = plugin_resource_path("personal-tool", "assets/panel.js", self.plugins)
        self.assertIn("Private panel", panel.read_text(encoding="utf-8"))
        self.assertTrue(asset.is_file())
        with self.assertRaises(PluginError):
            plugin_resource_path("personal-tool", "../manager-state.json", self.plugins)
        with self.assertRaises(PluginError):
            plugin_resource_path("personal-tool", "manifest.json", self.plugins)

    def test_plugin_storage_is_permission_gated_and_separate_from_package(self):
        archive = make_archive(
            feature_manifest(),
            panel="<p>Storage test</p>",
        )
        install_plugin_archive(archive, self.plugins)
        with self.assertRaises(PluginError):
            get_plugin_storage("personal-tool", "counter", self.plugins)

        set_plugin_enabled("personal-tool", True, self.plugins)
        self.assertIsNone(get_plugin_storage("personal-tool", "counter", self.plugins)["value"])
        put_plugin_storage("personal-tool", "counter", {"value": 3}, self.plugins)
        self.assertEqual(
            get_plugin_storage("personal-tool", "counter", self.plugins)["value"],
            {"value": 3},
        )
        data_file = self.base / "plugin-data" / "personal-tool" / "storage.json"
        self.assertTrue(data_file.is_file())
        self.assertFalse((self.plugins / "personal-tool" / "storage.json").exists())

        remove_plugin("personal-tool", delete_data=True, directory=self.plugins)
        self.assertFalse(data_file.exists())

    def test_import_and_export_round_trip_uses_portable_root_manifest(self):
        source = make_archive(
            theme_manifest("portable-theme"),
            theme={"colors": {"background": "#182030"}},
        )
        install_plugin_archive(source, self.plugins)
        exported = export_plugin_archive("portable-theme", self.plugins)

        second_plugins = self.base / "second-install" / "plugins"
        restored = install_plugin_archive(exported, second_plugins)
        self.assertEqual(restored["id"], "portable-theme")
        self.assertFalse(restored["enabled"])
        self.assertTrue((second_plugins / "portable-theme" / "manifest.json").is_file())

    def test_incompatible_plugin_is_retained_and_can_be_exported(self):
        plugin_dir = self.plugins / "future-theme"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            json.dumps(theme_manifest("future-theme", api_version=5)),
            encoding="utf-8",
        )
        (plugin_dir / "theme.json").write_text(
            json.dumps({"colors": {"background": "#102030"}}),
            encoding="utf-8",
        )

        listed = list_plugins(self.plugins)["plugins"][0]
        self.assertFalse(listed["enabled"])
        self.assertFalse(listed["compatible"])
        exported = export_plugin_archive("future-theme", self.plugins)
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["api_version"], 5)
        self.assertTrue(plugin_dir.is_dir())

    def test_zip_traversal_and_incompatible_api_are_rejected(self):
        malicious = io.BytesIO()
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../outside.txt", "not allowed")
            archive.writestr("manifest.json", json.dumps(theme_manifest()))
            archive.writestr("theme.json", json.dumps({"colors": {"background": "#102030"}}))
        with self.assertRaises(PluginError):
            install_plugin_archive(malicious.getvalue(), self.plugins)
        self.assertFalse((self.base.parent / "outside.txt").exists())

        incompatible = make_archive(
            theme_manifest("future-theme", api_version=5),
            theme={"colors": {"background": "#102030"}},
        )
        with self.assertRaises(PluginError):
            install_plugin_archive(incompatible, self.plugins)

    def test_corrupted_member_is_rejected_without_leaving_staging_files(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", json.dumps(theme_manifest("corrupt-theme")))
            archive.writestr("theme.json", json.dumps({"colors": {"background": "#102030"}}))
        corrupted = bytearray(output.getvalue())
        marker = corrupted.find(b"Ocean Night")
        self.assertGreaterEqual(marker, 0)
        corrupted[marker] ^= 1

        with self.assertRaises(PluginError):
            install_plugin_archive(corrupted, self.plugins)
        self.assertEqual(list_plugins(self.plugins)["plugins"], [])
        self.assertFalse(any(path.name.startswith(".import-") for path in self.plugins.iterdir()))

    def test_agent_skill_targets_follow_user_environment_and_are_idempotent(self):
        home = self.base / "portable-home"
        codex_home = self.base / "alternate-codex-home"
        xdg_home = self.base / "alternate-config-home"
        targets = get_agent_skill_targets(
            home=home,
            environ={
                "CODEX_HOME": str(codex_home),
                "XDG_CONFIG_HOME": str(xdg_home),
            },
        )
        self.assertEqual(
            targets["OpenCode"],
            xdg_home / "opencode" / "skills" / "sparkle-plugin-author",
        )
        self.assertEqual(
            targets["Codex"],
            codex_home / "skills" / "sparkle-plugin-author",
        )
        self.assertEqual(
            targets["Claude Code"],
            home / ".claude" / "skills" / "sparkle-plugin-author",
        )

        environment_targets = get_agent_skill_targets(
            home=home,
            environ={
                "USERPROFILE": str(home),
                "HOME": str(home),
                "CODEX_HOME": "%USERPROFILE%/.codex",
                "XDG_CONFIG_HOME": "${HOME}/.config",
                "CLAUDE_CONFIG_DIR": "%USERPROFILE%/.claude-custom",
            },
        )
        self.assertEqual(
            environment_targets["Codex"],
            home / ".codex" / "skills" / "sparkle-plugin-author",
        )
        self.assertEqual(
            environment_targets["OpenCode"],
            home / ".config" / "opencode" / "skills" / "sparkle-plugin-author",
        )

        source = self.base / "bundled-skill"
        source.mkdir()
        (source / "SKILL.md").write_text("Portable skill", encoding="utf-8")
        first = install_authoring_skill(
            source_dir=source,
            home=home,
            environ={"CODEX_HOME": str(codex_home), "XDG_CONFIG_HOME": str(xdg_home)},
        )
        self.assertEqual([result["status"] for result in first["results"]], ["installed"] * 3)
        second = install_authoring_skill(
            source_dir=source,
            home=home,
            environ={"CODEX_HOME": str(codex_home), "XDG_CONFIG_HOME": str(xdg_home)},
        )
        self.assertEqual([result["status"] for result in second["results"]], ["updated"] * 3)
        for target in targets.values():
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "Portable skill")

    def test_authoring_skill_status_requires_all_three_managed_current_copies(self):
        home = self.base / "skill-home"
        environment = {
            "CODEX_HOME": str(self.base / "codex-home"),
            "XDG_CONFIG_HOME": str(self.base / "config-home"),
            "CLAUDE_CONFIG_DIR": str(self.base / "claude-home"),
        }
        status = get_authoring_skill_status(home=home, environ=environment)
        self.assertFalse(status["all_installed"])
        self.assertEqual({item["status"] for item in status["results"]}, {"missing"})
        self.assertFalse((self.base / "codex-home").exists())

        source = Path(__file__).resolve().parents[1] / "skills" / "sparkle-plugin-author"
        install_authoring_skill(source_dir=source, home=home, environ=environment)
        status = get_authoring_skill_status(home=home, environ=environment)
        self.assertTrue(status["all_installed"])
        self.assertEqual({item["status"] for item in status["results"]}, {"installed"})

    def test_api_v2_ui_contributions_merge_and_revert_when_plugins_are_disabled(self):
        first = ui_feature_manifest(
            "tetris-tool",
            priority=10,
            contributes={
                "sidebar": {"label": "テトリス", "icon": "game"},
                "ui": {
                    "hide": ["home.sort"],
                    "order": {"sidebar.primary": ["home", "plugin:tetris-tool", "memo", "projects"]},
                    "styles": {"home.search": {"accent": "#88C0D0", "radius": "14px"}},
                },
            },
        )
        second = ui_feature_manifest(
            "compact-layout",
            priority=20,
            contributes={
                "ui": {
                    "hide": ["sidebar.profile"],
                    "order": {"sidebar.primary": ["projects", "home", "memo"]},
                    "styles": {"home.search": {"radius": "8px"}},
                },
            },
        )
        for manifest in (first, second):
            install_plugin_archive(make_archive(manifest, panel="<main>UI</main>"), self.plugins)
            set_plugin_enabled(manifest["id"], True, self.plugins)

        listed = list_plugins(self.plugins)
        self.assertEqual(listed["api_version"], 4)
        self.assertTrue(all(plugin["compatible"] for plugin in listed["plugins"]))
        state = get_plugin_ui_state(self.plugins)
        self.assertEqual(state["hidden"], ["home.sort", "sidebar.profile"])
        self.assertEqual(state["order"]["sidebar.primary"], ["projects", "home", "memo"])
        self.assertEqual(state["styles"]["home.search"], {"accent": "#88C0D0", "radius": "8px"})
        self.assertEqual(state["sidebar_items"], [{"plugin_id": "tetris-tool", "label": "テトリス", "icon": "game"}])

        set_plugin_enabled("compact-layout", False, self.plugins)
        state = get_plugin_ui_state(self.plugins)
        self.assertEqual(state["hidden"], ["home.sort"])
        self.assertEqual(state["order"]["sidebar.primary"], ["home", "plugin:tetris-tool", "memo", "projects"])
        self.assertEqual(state["styles"]["home.search"]["radius"], "14px")

    def test_api_v2_ui_contributions_reject_protected_targets_and_css_payloads(self):
        invalid_contributions = [
            {"ui": {"hide": ["sidebar.settings"]}},
            {"ui": {"styles": {"home.search": {"background": "url(https://example.invalid/x)"}}}},
            {"sidebar": {"label": "Tool", "icon": "../../remote.svg"}},
        ]
        for index, contributes in enumerate(invalid_contributions):
            manifest = ui_feature_manifest(f"unsafe-ui-{index}", contributes=contributes)
            archive = make_archive(manifest, panel="<main>UI</main>")
            with self.assertRaises(PluginError):
                install_plugin_archive(archive, self.plugins)

    def test_api_v1_plugin_remains_compatible_on_api_v3_host(self):
        archive = make_archive(
            theme_manifest("legacy-theme"),
            theme={"colors": {"background": "#102030"}},
        )
        install_plugin_archive(archive, self.plugins)
        plugin = list_plugins(self.plugins)["plugins"][0]
        self.assertEqual(plugin["api_version"], 1)
        self.assertTrue(plugin["compatible"])

    def test_api_v4_permissions_require_v4_and_start_ungranted(self):
        too_old = data_feature_manifest(
            "notes-api-v3",
            api_version=3,
            permissions=["notes.read"],
        )
        with self.assertRaises(PluginError):
            install_plugin_archive(make_archive(too_old, panel="<main>notes</main>"), self.plugins)

        manifest = data_feature_manifest(
            "notes-api-v4",
            api_version=4,
            permissions=["notes.read", "tasks.write", "ai.request", "network.request"],
        )
        install_plugin_archive(make_archive(manifest, panel="<main>notes</main>"), self.plugins)
        listed = list_plugins(self.plugins)
        self.assertEqual(listed["api_version"], 4)
        self.assertTrue(listed["plugins"][0]["compatible"])
        self.assertEqual(listed["plugins"][0]["granted_permissions"], [])
        set_plugin_enabled("notes-api-v4", True, self.plugins)
        set_plugin_permission_grant("notes-api-v4", "notes.read", True, self.plugins)
        self.assertEqual(
            list_plugins(self.plugins)["plugins"][0]["granted_permissions"],
            ["notes.read"],
        )
        self.assertEqual(revoke_plugin_permissions("notes-api-v4", self.plugins)["revoked"], 1)

    def test_api_v2_legacy_permission_is_available_until_explicit_revoke(self):
        manifest = data_feature_manifest(
            "legacy-data-tool",
            api_version=2,
            permissions=["storage"],
        )
        install_plugin_archive(make_archive(manifest, panel="<main>legacy</main>"), self.plugins)
        set_plugin_enabled("legacy-data-tool", True, self.plugins)
        listed = list_plugins(self.plugins)["plugins"][0]
        self.assertEqual(listed["granted_permissions"], ["storage"])
        revoked = revoke_plugin_permissions("legacy-data-tool", self.plugins)
        self.assertEqual(revoked["granted_permissions"], [])
        self.assertEqual(list_plugins(self.plugins)["plugins"][0]["granted_permissions"], [])

    def test_api_v3_permissions_start_empty_and_revoke_all_grants(self):
        manifest = data_feature_manifest("permission-tool")
        install_plugin_archive(make_archive(manifest, panel="<main>permissions</main>"), self.plugins)
        set_plugin_enabled("permission-tool", True, self.plugins)
        listed = list_plugins(self.plugins)["plugins"][0]
        self.assertEqual(listed["granted_permissions"], [])

        self.assertEqual(
            set_plugin_permission_grant("permission-tool", "clips.read", True, self.plugins)["granted_permissions"],
            ["clips.read"],
        )
        self.assertEqual(
            set_plugin_permission_grant("permission-tool", "projects.write", True, self.plugins)["granted_permissions"],
            ["clips.read", "projects.write"],
        )
        self.assertEqual(
            list_plugins(self.plugins)["plugins"][0]["granted_permissions"],
            ["clips.read", "projects.write"],
        )
        self.assertEqual(revoke_plugin_permissions("permission-tool", self.plugins)["revoked"], 2)
        self.assertEqual(list_plugins(self.plugins)["plugins"][0]["granted_permissions"], [])

    def test_api_v3_ui_contributions_wait_for_explicit_ui_permission(self):
        manifest = ui_feature_manifest(
            "permissioned-ui-tool",
            contributes={"ui": {"hide": ["home.search"]}},
        )
        manifest["api_version"] = 3
        install_plugin_archive(make_archive(manifest, panel="<main>UI</main>"), self.plugins)
        set_plugin_enabled("permissioned-ui-tool", True, self.plugins)

        self.assertEqual(get_plugin_ui_state(self.plugins)["hidden"], [])
        set_plugin_permission_grant("permissioned-ui-tool", "ui.customize", True, self.plugins)
        self.assertEqual(get_plugin_ui_state(self.plugins)["hidden"], ["home.search"])
        revoke_plugin_permissions("permissioned-ui-tool", self.plugins)
        self.assertEqual(get_plugin_ui_state(self.plugins)["hidden"], [])

    def test_bundled_authoring_skill_has_no_machine_specific_paths(self):
        skill_root = Path(__file__).resolve().parents[1] / "skills" / "sparkle-plugin-author"
        skill_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(skill_root.rglob("*"))
            if path.is_file()
        )
        self.assertNotRegex(skill_text, r"(?i)\b[A-Z]:[\\/]")
        posix_user_path = r"(?i)" + chr(47) + r"(?:Users|home)" + chr(47) + r"[^\s/]+"
        self.assertNotRegex(skill_text, posix_user_path)
        self.assertIn("Path.home()", skill_text)

    def test_skill_installer_does_not_overwrite_an_unmanaged_skill(self):
        home = self.base / "home"
        targets = get_agent_skill_targets(home=home, environ={})
        open_code_skill = targets["OpenCode"]
        open_code_skill.mkdir(parents=True)
        existing = open_code_skill / "SKILL.md"
        existing.write_text("User content", encoding="utf-8")
        source = self.base / "bundled-skill"
        source.mkdir()
        (source / "SKILL.md").write_text("Sparkle content", encoding="utf-8")

        result = install_authoring_skill(source_dir=source, home=home, environ={})
        self.assertEqual(result["results"][0]["status"], "conflict")
        self.assertEqual(existing.read_text(encoding="utf-8"), "User content")


if __name__ == "__main__":
    unittest.main()
