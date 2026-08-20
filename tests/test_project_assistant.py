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

    def test_ollama_configuration_uses_base_url_without_api_key(self):
        connection = make_connection()
        try:
            store = FakeSecretStore()
            with patch.object(assistant, "_secret_store", store):
                result = assistant.configure_ai_provider(
                    connection,
                    "ollama",
                    assistant.AIProviderUpdate(
                        base_url="http://server-pc:11434/",
                        model="qwen2.5:7b",
                    ),
                )
            status = next(item for item in result.providers if item.id == "ollama")
            self.assertTrue(status.configured)
            self.assertEqual(status.base_url, "http://server-pc:11434")
            self.assertEqual(status.model, "qwen2.5:7b")
            self.assertIsNone(store.get("ollama"))
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
                if spec.id != "ollama"
            ]

        self.assertEqual(answers, ["deepseek answer", "gemini answer", "openai answer"])
        self.assertEqual([item[0] for item in requests], ["deepseek", "gemini", "openai"])
        for _, url, headers, _ in requests:
            self.assertNotIn("secret-key", url)
            self.assertIn("secret-key", " ".join(headers.values()))

    def test_ollama_uses_configured_openai_compatible_base_url(self):
        requests = []

        def fake_request(provider, url, headers, payload):
            requests.append((provider.id, url, headers, payload))
            return {"choices": [{"message": {"content": "ollama answer"}}]}

        with patch.object(assistant, "_request_json", side_effect=fake_request):
            result = assistant._call_provider(
                assistant.PROVIDER_MAP["ollama"],
                None,
                "system",
                "user",
                "qwen2.5:7b",
                "http://server-pc:11434",
            )

        self.assertEqual(result, "ollama answer")
        self.assertEqual(requests[0][1], "http://server-pc:11434/v1/chat/completions")
        self.assertNotIn("Authorization", requests[0][2])

    def test_scope_all_and_history_are_persisted(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("別",))
            other_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/other", "別クリップ", other_id),
            )
            connection.commit()
            store = FakeSecretStore({"openai": "sk-test"})
            fake_answer = json.dumps({"answer": "全体を確認しました。", "source_ids": [], "actions": []}, ensure_ascii=False)
            with patch.object(assistant, "_secret_store", store), patch.object(
                assistant, "_call_provider", return_value=fake_answer
            ):
                result = assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(message="全体を見て", scope="all"),
                )
            self.assertEqual(result.scope, "all")
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual([message.role for message in history.messages], ["user", "assistant"])
            self.assertEqual(history.messages[-1].scope, "all")
        finally:
            connection.close()

    def test_ai_write_requires_explicit_permission_and_always_is_global(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title) VALUES (?, ?)",
                ("https://example.com/bgm", "BGM1"),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()

            proposal = assistant._create_action_proposal(
                connection,
                project_id,
                assistant.ProjectAssistantActionRequest(operation="attach_clip", clip_ids=[clip_id]),
            )
            connection.commit()
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM project_clips WHERE project_id = ? AND clip_id = ?",
                    (project_id, clip_id),
                ).fetchone()
            )
            result = assistant.execute_project_assistant_action(
                connection,
                project_id,
                assistant.ProjectAssistantActionDecisionRequest(proposal_id=proposal, decision="once"),
            )
            self.assertEqual(result.status, "executed")
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM ai_action_permissions WHERE operation = 'attach_clip'"
                ).fetchone()
            )

            note_proposal = assistant._create_action_proposal(
                connection,
                project_id,
                assistant.ProjectAssistantActionRequest(
                    operation="create_note", title="BGMメモ", body="BGM1を使用"
                ),
            )
            connection.commit()
            note_result = assistant.execute_project_assistant_action(
                connection,
                project_id,
                assistant.ProjectAssistantActionDecisionRequest(proposal_id=note_proposal, decision="always"),
            )
            self.assertEqual(note_result.status, "executed")
            self.assertTrue(
                connection.execute(
                    "SELECT 1 FROM ai_action_permissions WHERE operation = 'create_note' AND mode = 'always'"
                ).fetchone()
            )

            denied = assistant._create_action_proposal(
                connection,
                project_id,
                assistant.ProjectAssistantActionRequest(operation="attach_clip", clip_ids=[clip_id]),
            )
            connection.commit()
            denied_result = assistant.execute_project_assistant_action(
                connection,
                project_id,
                assistant.ProjectAssistantActionDecisionRequest(proposal_id=denied, decision="deny"),
            )
            self.assertEqual(denied_result.status, "denied")
        finally:
            connection.close()

    def test_model_action_is_only_a_proposal_until_user_allows_it(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title) VALUES (?, ?)",
                ("https://example.com/bgm", "BGM1"),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()
            store = FakeSecretStore({"openai": "sk-test"})
            fake_answer = json.dumps(
                {
                    "answer": "BGM1を添付する案を作成しました。",
                    "source_ids": [f"clip:{clip_id}"],
                    "actions": [{"operation": "attach_clip", "clip_ids": [clip_id]}],
                },
                ensure_ascii=False,
            )
            with patch.object(assistant, "_secret_store", store), patch.object(
                assistant, "_call_provider", return_value=fake_answer
            ):
                result = assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(message="BGM1を添付して", scope="all"),
                )
            self.assertEqual(len(result.actions), 1)
            self.assertEqual(result.actions[0].permission, "required")
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM project_clips WHERE project_id = ? AND clip_id = ?",
                    (project_id, clip_id),
                ).fetchone()
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
