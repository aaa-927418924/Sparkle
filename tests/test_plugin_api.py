import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


class PluginApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name) / "Sparkle"
        self.plugins = self.base / "plugins"
        self.plugins.mkdir(parents=True)
        self.app = FastAPI()
        self.app.include_router(plugin_api.router)
        self.client = TestClient(self.app)
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
