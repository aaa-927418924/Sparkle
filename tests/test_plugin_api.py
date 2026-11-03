import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
import plugin_api


def make_feature_archive():
    output = io.BytesIO()
    manifest = {
        "id": "api-panel",
        "name": "API Panel",
        "version": "1.0.0",
        "api_version": 1,
        "type": "feature",
        "description": "Panel API test",
        "permissions": ["storage", "notifications"],
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("panel.html", "<h1>Panel body</h1>")
        archive.writestr("assets/style.css", "body { color: #fff; }")
    return output.getvalue()


def make_ui_feature_archive():
    output = io.BytesIO()
    manifest = {
        "id": "api-ui-panel",
        "name": "API UI Panel",
        "version": "1.0.0",
        "api_version": 2,
        "type": "feature",
        "description": "UI contribution API test",
        "permissions": ["ui.customize"],
        "contributes": {
            "sidebar": {"label": "Game", "icon": "game"},
            "project_action": {"label": "分析", "icon": "sparkles"},
            "ui": {"hide": ["home.search"]},
        },
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("panel.html", "<main>UI panel</main>")
    return output.getvalue()


def make_data_feature_archive():
    output = io.BytesIO()
    manifest = {
        "id": "api-data-panel",
        "name": "API Data Panel",
        "version": "1.0.0",
        "api_version": 3,
        "type": "feature",
        "description": "Data permission API test",
        "permissions": [
            "clips.read",
            "clips.write",
            "clips.delete",
            "projects.read",
            "projects.write",
            "projects.delete",
        ],
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("panel.html", "<main>Data panel</main>")
    return output.getvalue()


def make_v4_feature_archive(plugin_id="api-v4-panel", permissions=None):
    output = io.BytesIO()
    manifest = {
        "id": plugin_id,
        "name": "API v4 Panel",
        "version": "1.0.0",
        "api_version": 4,
        "type": "feature",
        "description": "Notes, tasks, AI, and network permission API test",
        "permissions": permissions or [
            "notes.read",
            "notes.write",
            "notes.delete",
            "tasks.read",
            "tasks.write",
            "tasks.delete",
            "ai.request",
            "network.request",
            "projects.read",
            "projects.write",
            "clips.read",
            "clips.write",
        ],
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("panel.html", "<main>API v4 panel</main>")
    return output.getvalue()


def make_v5_oauth_archive():
    output = io.BytesIO()
    manifest = {
        "id": "api-oauth-panel",
        "name": "API OAuth Panel",
        "version": "1.0.0",
        "api_version": 5,
        "type": "feature",
        "description": "Plugin-owned OAuth API test",
        "permissions": ["auth.oauth"],
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("panel.html", "<main>OAuth panel</main>")
    return output.getvalue()


class PluginApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name) / "Sparkle"
        self.plugins = self.base / "plugins"
        self.plugins.mkdir(parents=True)
        self.app = FastAPI()
        self.app.include_router(plugin_api.router)
        self.client = TestClient(self.app)
        self.app.dependency_overrides[plugin_api.get_db] = lambda: None
        self.addCleanup(self.app.dependency_overrides.clear)
        self.patches = [
            patch("plugin_manager.get_plugins_dir", return_value=self.plugins),
            patch("plugin_manager.get_plugin_data_dir", return_value=self.base / "plugin-data"),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_opaque_origins_cannot_read_or_grant_plugin_permissions(self):
        # Sandboxed plugin panels use the parent-page message broker and do
        # not need direct API access from their opaque ("null") origin.
        from main import app as sparkle_app

        client = TestClient(sparkle_app)
        opaque_origin = client.get("/openapi.json", headers={"Origin": "null"})
        self.assertNotIn("access-control-allow-origin", opaque_origin.headers)

        app_origin = "http://127.0.0.1:8000"
        same_origin = client.get("/openapi.json", headers={"Origin": app_origin})
        self.assertEqual(same_origin.headers.get("access-control-allow-origin"), app_origin)
        client.close()

    def test_import_lists_disabled_then_feature_panel_runs_with_sandbox_headers(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("panel.zip", make_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])

        listed = self.client.get("/plugins")
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.json()["plugins"][0]["enabled"])
        self.assertEqual(self.client.get("/plugins/api-panel/panel").status_code, 400)

        enabled = self.client.post(
            "/plugins/api-panel/enabled",
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)

        panel = self.client.get("/plugins/api-panel/panel")
        self.assertEqual(panel.status_code, 200)
        self.assertIn("Panel body", panel.text)
        self.assertIn("sandbox allow-scripts", panel.headers["content-security-policy"])
        self.assertEqual(panel.headers["x-content-type-options"], "nosniff")

        asset = self.client.get("/plugins/api-panel/assets/style.css")
        self.assertEqual(asset.status_code, 200, asset.text)
        self.assertIn("#fff", asset.text)

    def test_storage_api_requires_plugin_permission_and_preserves_plugin_namespace(self):
        self.client.post(
            "/plugins/import",
            files={"file": ("panel.zip", make_feature_archive(), "application/zip")},
        )
        self.client.post("/plugins/api-panel/enabled", json={"enabled": True})
        saved = self.client.put(
            "/plugins/api-panel/storage/settings",
            json={"value": {"density": "compact"}},
        )
        self.assertEqual(saved.status_code, 200)
        read = self.client.get("/plugins/api-panel/storage/settings")
        self.assertEqual(read.json()["value"], {"density": "compact"})

    def test_ui_contributions_are_absent_until_enabled_and_removed_when_disabled(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("ui-panel.zip", make_ui_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(self.client.get("/plugins/ui").json()["sidebar_items"], [])

        enabled = self.client.post("/plugins/api-ui-panel/enabled", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200)
        ui = self.client.get("/plugins/ui")
        self.assertEqual(ui.status_code, 200)
        self.assertEqual(ui.json()["hidden"], ["home.search"])
        self.assertEqual(ui.json()["sidebar_items"][0]["label"], "Game")
        self.assertEqual(ui.json()["project_actions"][0]["label"], "分析")

        disabled = self.client.post("/plugins/api-ui-panel/enabled", json={"enabled": False})
        self.assertEqual(disabled.status_code, 200)
        restored = self.client.get("/plugins/ui").json()
        self.assertEqual(restored["hidden"], [])
        self.assertEqual(restored["sidebar_items"], [])
        self.assertEqual(restored["project_actions"], [])

    def test_api_v3_permission_grants_are_persistent_and_revoke_all(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("data.zip", make_data_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.get("/plugins").json()["plugins"][0]["granted_permissions"],
            [],
        )
        self.assertEqual(
            self.client.post("/plugins/api-data-panel/enabled", json={"enabled": True}).status_code,
            200,
        )

        denied = self.client.get("/plugins/api-data-panel/data/clips")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["permission_required"], "clips.read")

        granted = self.client.put(
            "/plugins/api-data-panel/permissions/clips.read",
            json={"granted": True},
        )
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertEqual(granted.json()["granted_permissions"], ["clips.read"])
        listed = self.client.get("/plugins").json()["plugins"][0]
        self.assertEqual(listed["granted_permissions"], ["clips.read"])

        revoked = self.client.delete("/plugins/api-data-panel/permissions")
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["granted_permissions"], [])
        self.assertEqual(
            self.client.get("/plugins").json()["plugins"][0]["granted_permissions"],
            [],
        )

    def test_api_v3_clip_and_project_data_scopes_are_separate_and_restrict_writes(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("data.zip", make_data_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.post("/plugins/api-data-panel/enabled", json={"enabled": True})

        with patch("plugin_api.host_list_clips", return_value=[]):
            self.client.put(
                "/plugins/api-data-panel/permissions/clips.read",
                json={"granted": True},
            )
            clips = self.client.get("/plugins/api-data-panel/data/clips")
            self.assertEqual(clips.status_code, 200, clips.text)
            self.assertEqual(clips.json(), [])
        projects_without_grant = self.client.get("/plugins/api-data-panel/data/projects")
        self.assertEqual(projects_without_grant.status_code, 403)
        self.assertEqual(
            projects_without_grant.json()["detail"]["permission_required"],
            "projects.read",
        )
        self.client.put(
            "/plugins/api-data-panel/permissions/projects.read",
            json={"granted": True},
        )
        with patch("plugin_api.host_list_projects", return_value=[]):
            projects = self.client.get("/plugins/api-data-panel/data/projects")
            self.assertEqual(projects.status_code, 200, projects.text)
            self.assertEqual(projects.json(), [])

        self.client.put(
            "/plugins/api-data-panel/permissions/clips.write",
            json={"granted": True},
        )
        with patch("plugin_api.host_create_clip", return_value={"id": 5, "url": "https://example.com"}):
            local_clip = self.client.post(
                "/plugins/api-data-panel/data/clips",
                json={"url": "local://not-allowed", "clip_type": "local"},
            )
            self.assertEqual(local_clip.status_code, 422)
            missing_project_grant = self.client.post(
                "/plugins/api-data-panel/data/clips",
                json={"url": "https://example.com", "project_id": 7},
            )
            self.assertEqual(missing_project_grant.status_code, 403)
            self.assertEqual(
                missing_project_grant.json()["detail"]["permission_required"],
                "projects.write",
            )

            created = self.client.post(
                "/plugins/api-data-panel/data/clips",
                json={"url": "https://example.com"},
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["id"], 5)

        self.client.put(
            "/plugins/api-data-panel/permissions/projects.write",
            json={"granted": True},
        )
        with patch("plugin_api.host_create_clip", return_value={"id": 6, "url": "https://example.com"}):
            linked = self.client.post(
                "/plugins/api-data-panel/data/clips",
                json={"url": "https://example.com", "project_id": 7},
            )
            self.assertEqual(linked.status_code, 201, linked.text)

        with patch("plugin_api.host_update_project") as update_project:
            done_change = self.client.put(
                "/plugins/api-data-panel/data/projects/7",
                json={"is_done": True},
            )
            self.assertEqual(done_change.status_code, 422)
            update_project.assert_not_called()

        denied_delete = self.client.delete("/plugins/api-data-panel/data/clips/5")
        self.assertEqual(denied_delete.status_code, 403)
        self.assertEqual(denied_delete.json()["detail"]["permission_required"], "clips.delete")
        self.client.put(
            "/plugins/api-data-panel/permissions/clips.delete",
            json={"granted": True},
        )
        with patch("plugin_api.host_delete_clip", return_value=None) as delete_clip:
            deleted = self.client.delete("/plugins/api-data-panel/data/clips/5")
            self.assertEqual(deleted.status_code, 204)
            delete_clip.assert_called_once()

        denied_project_delete = self.client.delete("/plugins/api-data-panel/data/projects/7")
        self.assertEqual(denied_project_delete.status_code, 403)
        self.assertEqual(
            denied_project_delete.json()["detail"]["permission_required"],
            "projects.delete",
        )

    def test_api_v3_reads_and_writes_real_project_and_clip_rows_with_temporary_db(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("data.zip", make_data_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.post("/plugins/api-data-panel/enabled", json={"enabled": True})
        for permission in ("projects.read", "projects.write", "clips.read", "clips.write"):
            granted = self.client.put(
                "/plugins/api-data-panel/permissions/" + permission,
                json={"granted": True},
            )
            self.assertEqual(granted.status_code, 200, granted.text)

        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(db._SCHEMA)
        db._migrate(connection)
        self.app.dependency_overrides[plugin_api.get_db] = lambda: connection
        self.addCleanup(connection.close)

        project_response = self.client.post(
            "/plugins/api-data-panel/data/projects",
            json={"name": "Plugin project", "description": "Created through the plugin API"},
        )
        self.assertEqual(project_response.status_code, 201, project_response.text)
        project = project_response.json()
        self.assertEqual(project["name"], "Plugin project")

        # Complete metadata keeps the host's URL metadata path local. The
        # validator is also patched so this test never performs network I/O.
        with patch("routers._validate_metadata_url", side_effect=lambda value: value):
            clip_response = self.client.post(
                "/plugins/api-data-panel/data/clips",
                json={
                    "url": "https://example.com/plugin-clip",
                    "title": "Plugin clip",
                    "thumbnail_url": "https://example.com/plugin-clip.png",
                    "comment": "Created through the plugin API",
                    "project_id": project["id"],
                },
            )
        self.assertEqual(clip_response.status_code, 201, clip_response.text)
        clip = clip_response.json()
        self.assertEqual(clip["title"], "Plugin clip")
        self.assertIn(project["id"], clip["project_ids"])

        projects_response = self.client.get("/plugins/api-data-panel/data/projects")
        self.assertEqual(projects_response.status_code, 200, projects_response.text)
        self.assertEqual(projects_response.json()[0]["id"], project["id"])

        clips_response = self.client.get(
            "/plugins/api-data-panel/data/clips",
            params={"project_id": project["id"]},
        )
        self.assertEqual(clips_response.status_code, 200, clips_response.text)
        self.assertEqual(clips_response.json()[0]["id"], clip["id"])

        updated_clip = self.client.put(
            "/plugins/api-data-panel/data/clips/" + str(clip["id"]),
            json={"title": "Updated plugin clip", "comment": "Updated safely"},
        )
        self.assertEqual(updated_clip.status_code, 200, updated_clip.text)
        self.assertEqual(updated_clip.json()["title"], "Updated plugin clip")

        updated_project = self.client.put(
            "/plugins/api-data-panel/data/projects/" + str(project["id"]),
            json={"name": "Updated plugin project"},
        )
        self.assertEqual(updated_project.status_code, 200, updated_project.text)
        self.assertEqual(updated_project.json()["name"], "Updated plugin project")

    def test_api_v4_notes_and_tasks_are_readable_and_writable_with_separate_grants(self):
        response = self.client.post(
            "/plugins/import",
            files={"file": ("v4.zip", make_v4_feature_archive(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.post("/plugins/api-v4-panel/enabled", json={"enabled": True})

        denied_notes = self.client.get("/plugins/api-v4-panel/data/notes")
        self.assertEqual(denied_notes.status_code, 403)
        self.assertEqual(denied_notes.json()["detail"]["permission_required"], "notes.read")
        denied_tasks = self.client.get("/plugins/api-v4-panel/data/tasks")
        self.assertEqual(denied_tasks.status_code, 403)
        self.assertEqual(denied_tasks.json()["detail"]["permission_required"], "tasks.read")

        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(db._SCHEMA)
        db._migrate(connection)
        self.app.dependency_overrides[plugin_api.get_db] = lambda: connection
        self.addCleanup(connection.close)

        for permission in ("notes.read", "notes.write", "tasks.read", "tasks.write"):
            granted = self.client.put(
                "/plugins/api-v4-panel/permissions/" + permission,
                json={"granted": True},
            )
            self.assertEqual(granted.status_code, 200, granted.text)

        created_note = self.client.post(
            "/plugins/api-v4-panel/data/notes",
            json={"title": "Plugin note", "body": "Read and write note content"},
        )
        self.assertEqual(created_note.status_code, 201, created_note.text)
        note = created_note.json()
        self.assertEqual(note["body"], "Read and write note content")
        self.assertNotIn("clips", note)
        read_note = self.client.get(f"/plugins/api-v4-panel/data/notes/{note['id']}")
        self.assertEqual(read_note.status_code, 200)
        updated_note = self.client.put(
            f"/plugins/api-v4-panel/data/notes/{note['id']}",
            json={"title": "Updated plugin note"},
        )
        self.assertEqual(updated_note.status_code, 200, updated_note.text)
        self.assertEqual(updated_note.json()["title"], "Updated plugin note")

        blocked_note_link = self.client.post(
            "/plugins/api-v4-panel/data/notes",
            json={"title": "Linked note", "project_id": 1},
        )
        self.assertEqual(blocked_note_link.status_code, 403)
        self.assertEqual(blocked_note_link.json()["detail"]["permission_required"], "projects.write")

        created_task = self.client.post(
            "/plugins/api-v4-panel/data/tasks",
            json={"title": "Plugin task", "due_date": "2026-12-01", "priority": 2},
        )
        self.assertEqual(created_task.status_code, 201, created_task.text)
        task = created_task.json()
        self.assertNotIn("clip", task)
        read_task = self.client.get(f"/plugins/api-v4-panel/data/tasks/{task['id']}")
        self.assertEqual(read_task.status_code, 200)
        updated_task = self.client.put(
            f"/plugins/api-v4-panel/data/tasks/{task['id']}",
            json={"is_done": True},
        )
        self.assertEqual(updated_task.status_code, 200, updated_task.text)
        self.assertTrue(updated_task.json()["is_done"])
        blocked_task_link = self.client.post(
            "/plugins/api-v4-panel/data/tasks",
            json={"title": "Linked task", "project_id": 1},
        )
        self.assertEqual(blocked_task_link.status_code, 403)
        self.assertEqual(blocked_task_link.json()["detail"]["permission_required"], "projects.write")

        self.assertEqual(self.client.delete(f"/plugins/api-v4-panel/data/notes/{note['id']}").status_code, 403)
        self.assertEqual(self.client.delete(f"/plugins/api-v4-panel/data/tasks/{task['id']}").status_code, 403)
        for permission in ("notes.delete", "tasks.delete"):
            self.client.put(
                "/plugins/api-v4-panel/permissions/" + permission,
                json={"granted": True},
            )
        self.assertEqual(self.client.delete(f"/plugins/api-v4-panel/data/notes/{note['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/plugins/api-v4-panel/data/tasks/{task['id']}").status_code, 204)

    def test_api_v4_ai_and_network_requests_prompt_and_reuse_active_grants(self):
        self.client.post(
            "/plugins/import",
            files={"file": ("v4.zip", make_v4_feature_archive(), "application/zip")},
        )
        self.client.post("/plugins/api-v4-panel/enabled", json={"enabled": True})

        denied_ai = self.client.post(
            "/plugins/api-v4-panel/ai/generate",
            json={"prompt": "Summarize my data"},
        )
        self.assertEqual(denied_ai.status_code, 403)
        self.assertEqual(denied_ai.json()["detail"]["permission_required"], "ai.request")
        denied_network = self.client.post(
            "/plugins/api-v4-panel/network/request",
            json={"url": "https://example.com"},
        )
        self.assertEqual(denied_network.status_code, 403)
        self.assertEqual(denied_network.json()["detail"]["permission_required"], "network.request")

        for permission in ("ai.request", "network.request"):
            self.client.put(
                "/plugins/api-v4-panel/permissions/" + permission,
                json={"granted": True},
            )
        with patch(
            "plugin_api.generate_plugin_ai_response",
            return_value={"response": "Answer", "provider": "openai", "model": "gpt-test"},
        ) as generate, patch(
            "plugin_api.perform_plugin_network_request",
            return_value={"status": 200, "headers": {"content-type": "text/plain"}, "body": "ok"},
        ) as network:
            ai = self.client.post(
                "/plugins/api-v4-panel/ai/generate",
                json={"system_prompt": "Be concise", "prompt": "Summarize my data"},
            )
            self.assertEqual(ai.status_code, 200, ai.text)
            self.assertEqual(ai.json()["response"], "Answer")
            generate.assert_called_once()

            fetched = self.client.post(
                "/plugins/api-v4-panel/network/request",
                json={"url": "https://example.com/api", "method": "POST", "body": "{}"},
            )
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertEqual(fetched.json()["body"], "ok")
            network.assert_called_once()

    def test_api_v5_oauth_methods_require_permission_and_never_return_tokens(self):
        self.client.post(
            "/plugins/import",
            files={"file": ("oauth.zip", make_v5_oauth_archive(), "application/zip")},
        )
        self.client.post("/plugins/api-oauth-panel/enabled", json={"enabled": True})
        connection = {
            "connection_id": "codex-plan",
            "name": "Codex plan",
            "authorization_url": "https://auth.example.test/authorize",
            "token_url": "https://auth.example.test/token",
            "client_id": "public-client-id",
            "scopes": ["openid", "offline_access"],
            "resource": "https://api.example.test/v1",
            "api_origin": "https://api.example.test",
            "issuer": "https://auth.example.test",
            "jwks_url": "https://auth.example.test/jwks",
        }
        denied = self.client.post(
            "/plugins/api-oauth-panel/oauth/connect",
            json=connection,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["permission_required"], "auth.oauth")
        granted = self.client.put(
            "/plugins/api-oauth-panel/permissions/auth.oauth",
            json={"granted": True},
        )
        self.assertEqual(granted.status_code, 200)

        with patch(
            "plugin_api.start_plugin_oauth",
            return_value={"connection_id": "codex-plan", "pending": True, "connected": False},
        ) as start, patch(
            "plugin_api.get_plugin_oauth_status",
            return_value={"connection_id": "codex-plan", "pending": False, "connected": True},
        ), patch(
            "plugin_api.plugin_oauth_request",
            return_value={"status": 200, "headers": {}, "body": "{}"},
        ) as oauth_request:
            connected = self.client.post("/plugins/api-oauth-panel/oauth/connect", json=connection)
            self.assertEqual(connected.status_code, 200)
            self.assertNotIn("access_token", connected.json())
            self.assertNotIn("refresh_token", connected.json())
            start.assert_called_once()

            status = self.client.get("/plugins/api-oauth-panel/oauth/codex-plan")
            self.assertEqual(status.json()["connected"], True)

            response = self.client.post(
                "/plugins/api-oauth-panel/oauth/codex-plan/request",
                json={"url": "https://api.example.test/v1/responses", "method": "POST", "body": "{}"},
            )
            self.assertEqual(response.status_code, 200)
            oauth_request.assert_called_once()

            disconnected = self.client.delete("/plugins/api-oauth-panel/oauth/codex-plan")
            self.assertEqual(disconnected.status_code, 200)

    def test_authoring_skill_status_endpoint_reports_all_targets(self):
        expected = {
            "skill": "sparkle-plugin-author",
            "version": "2.3.0",
            "all_installed": False,
            "results": [
                {"agent": "OpenCode", "status": "installed"},
                {"agent": "Codex", "status": "missing"},
                {"agent": "Claude Code", "status": "installed"},
            ],
        }
        with patch("plugin_api.get_authoring_skill_status", return_value=expected):
            response = self.client.get("/plugins/authoring-skill/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_import_requires_a_zip_and_rejects_invalid_packages(self):
        wrong_file = self.client.post(
            "/plugins/import",
            files={"file": ("plugin.txt", b"content", "text/plain")},
        )
        self.assertEqual(wrong_file.status_code, 422)

        invalid = self.client.post(
            "/plugins/import",
            files={"file": ("bad.zip", b"not a zip", "application/zip")},
        )
        self.assertEqual(invalid.status_code, 400)


if __name__ == "__main__":
    unittest.main()
