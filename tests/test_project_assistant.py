import json
import sqlite3
import unittest
from unittest.mock import patch

import project_assistant as assistant
from db import _SCHEMA, _migrate


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, provider):
        return self.values.get(provider)

    def set(self, provider, value):
        self.values[provider] = value

    def delete(self, provider):
        self.values.pop(provider, None)


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    _migrate(connection)
    return connection


class ProjectAssistantTests(unittest.TestCase):
    def test_provider_status_never_returns_api_key(self):
        connection = make_connection()
        try:
            store = FakeSecretStore({"openai": "sk-secret-test-value"})
            with patch.object(assistant, "_secret_store", store):
                result = assistant.get_ai_provider_settings(connection)
            serialized = result.model_dump_json()
            self.assertTrue(result.available)
            self.assertEqual(result.active_provider, "openai")
            self.assertTrue(next(item for item in result.providers if item.id == "openai").configured)
            self.assertNotIn("sk-secret-test-value", serialized)
        finally:
            connection.close()

    def test_context_is_project_scoped_and_redacts_local_path(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name, description) VALUES (?, ?)", ("対象", "対象の説明"))
            target_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO projects(name, description) VALUES (?, ?)", ("別プロジェクト", "送信禁止"))
            other_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, comment, clip_type, project_id) VALUES (?, ?, ?, ?, ?)",
                ("local://C:/Users/example/secret.mov", "対象クリップ", "対象コメント", "local", target_id),
            )
            connection.execute(
                "INSERT INTO clips(url, title, comment, project_id) VALUES (?, ?, ?, ?)",
                ("https://example.com/other", "別クリップ", "別コメント", other_id),
            )
            connection.execute("INSERT INTO tasks(title, project_id) VALUES (?, ?)", ("対象タスク", target_id))
            connection.execute("INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)", ("対象メモ", "対象本文", target_id))
            connection.commit()

            context = assistant._project_context(connection, target_id)
            self.assertIn("対象クリップ", context.prompt)
            self.assertIn("対象タスク", context.prompt)
            self.assertIn("対象本文", context.prompt)
            self.assertNotIn("別クリップ", context.prompt)
            self.assertNotIn("C:/Users/example/secret.mov", context.prompt)
            self.assertIn("ローカルファイル（パスは送信しません）", context.prompt)
        finally:
            connection.close()

    def test_model_sources_are_limited_to_project_context(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com", "対象クリップ", project_id),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()
            store = FakeSecretStore({"openai": "sk-test"})
            fake_answer = json.dumps(
                {
                    "answer": "対象クリップを参照しました。",
                    "source_ids": [f"clip:{clip_id}", "clip:999999", "note:999999"],
                },
                ensure_ascii=False,
            )
            with patch.object(assistant, "_secret_store", store), patch.object(
                assistant, "_call_provider", return_value=fake_answer
            ):
                result = assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(message="何を参照しましたか？"),
                )
            self.assertEqual(result.answer, "対象クリップを参照しました。")
            self.assertEqual([(source.kind, source.id) for source in result.sources], [("clip", clip_id)])
        finally:
            connection.close()

    def test_configure_keeps_secret_out_of_sqlite(self):
        connection = make_connection()
        try:
            store = FakeSecretStore()
            with patch.object(assistant, "_secret_store", store):
                result = assistant.configure_ai_provider(
                    connection,
                    "gemini",
                    assistant.AIProviderUpdate(api_key="AIza-secret-test", model="gemini-test"),
                )
            database_values = [row[0] for row in connection.execute("SELECT value FROM settings").fetchall()]
            self.assertTrue(next(item for item in result.providers if item.id == "gemini").configured)
            self.assertEqual(store.get("gemini"), "AIza-secret-test")
            self.assertNotIn("AIza-secret-test", database_values)
            self.assertIn("gemini-test", database_values)
        finally:
            connection.close()

    def test_provider_adapters_use_header_auth_without_putting_key_in_url(self):
        requests = []

        def fake_request(provider, url, headers, payload):
            requests.append((provider.id, url, headers, payload))
            if provider.id == "deepseek":
                return {"choices": [{"message": {"content": "deepseek answer"}}]}
            if provider.id == "gemini":
                return {"candidates": [{"content": {"parts": [{"text": "gemini answer"}]}}]}
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "openai answer"}]}]}

        with patch.object(assistant, "_request_json", side_effect=fake_request):
            answers = [
                assistant._call_provider(spec, "secret-key", "system", "user", spec.default_model)
                for spec in assistant.PROVIDERS
            ]

        self.assertEqual(answers, ["deepseek answer", "gemini answer", "openai answer"])
        self.assertEqual([item[0] for item in requests], ["deepseek", "gemini", "openai"])
        for _, url, headers, _ in requests:
            self.assertNotIn("secret-key", url)
            self.assertIn("secret-key", " ".join(headers.values()))


if __name__ == "__main__":
    unittest.main()
