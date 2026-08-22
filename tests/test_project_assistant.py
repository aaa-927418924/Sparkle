import io
import json
import sqlite3
import unittest
import urllib.error
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
    def _insert_history_pair(self, connection, project_id, user_content, answer_content, scope="project"):
        connection.execute(
            "INSERT INTO project_assistant_messages "
            "(project_id, role, content, provider, model, scope, context_item_count) "
            "VALUES (?, 'user', ?, 'ollama', 'test-model', ?, 1)",
            (project_id, user_content, scope),
        )
        user_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            "INSERT INTO project_assistant_messages "
            "(project_id, role, content, provider, model, scope, context_item_count) "
            "VALUES (?, 'assistant', ?, 'ollama', 'test-model', ?, 1)",
            (project_id, answer_content, scope),
        )
        assistant_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return user_id, assistant_id

    def test_delete_assistant_history_message_removes_selected_turn_and_everything_after_it(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            self._insert_history_pair(connection, project_id, "残す質問", "残す回答")
            target_user_id, _ = self._insert_history_pair(connection, project_id, "削除対象", "削除対象の回答")
            self._insert_history_pair(connection, project_id, "後続の質問", "後続の回答")
            connection.commit()

            assistant.delete_project_assistant_message(connection, project_id, target_user_id)

            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual([message.content for message in history.messages], ["残す質問", "残す回答"])
        finally:
            connection.close()

    def test_prepare_assistant_edit_only_removes_latest_user_turn(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            first_user_id, _ = self._insert_history_pair(connection, project_id, "最初の質問", "最初の回答")
            latest_user_id, _ = self._insert_history_pair(connection, project_id, "最後の質問", "最後の回答")
            connection.commit()

            with self.assertRaises(assistant.ProjectAssistantError) as raised:
                assistant.prepare_project_assistant_edit(connection, project_id, first_user_id)
            self.assertEqual(raised.exception.status_code, 409)

            assistant.prepare_project_assistant_edit(connection, project_id, latest_user_id)
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual([message.content for message in history.messages], ["最初の質問", "最初の回答"])
        finally:
            connection.close()

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

    def test_ollama_all_scope_stays_within_budget_and_keeps_context_types(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for index in range(3):
                connection.execute("INSERT INTO projects(name) VALUES (?)", (f"別{index}",))
                other_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute(
                    "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                    (f"https://example.com/{index}", f"クリップ{index}", other_id),
                )
                connection.execute("INSERT INTO tasks(title, project_id) VALUES (?, ?)", (f"タスク{index}", other_id))
                connection.execute(
                    "INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)",
                    (f"メモ{index}", "長い本文" * 600, other_id),
                )
            connection.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES ('ai_active_provider', 'ollama')"
            )
            connection.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES ('ai_base_url_ollama', 'http://server-pc:11434')"
            )
            connection.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES ('ai_model_ollama', 'test-model')"
            )
            connection.commit()

            with patch.object(assistant, "_secret_store", FakeSecretStore()):
                prepared = assistant._prepare_assistant_request(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(message="全体を確認して", provider="ollama", scope="all"),
                )

            kinds = {item.kind for item in prepared.context.items}
            self.assertLessEqual(len(prepared.context.prompt), assistant.MAX_OLLAMA_CONTEXT_CHARS)
            self.assertEqual({"project", "clip", "task", "note"}, kinds)
            self.assertEqual(prepared.context.total_items, 13)
        finally:
            connection.close()

    def test_retrieval_searches_older_matches_without_a_fixed_forty_item_cap(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/kimi", "Meet Kimi K3", project_id),
            )
            kimi_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for index in range(55):
                connection.execute(
                    "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                    (f"https://example.com/filler-{index}", f"別クリップ{index}", project_id),
                )
            connection.commit()

            context = assistant._retrieval_context(
                connection,
                project_id,
                "project",
                "タイトルにKimiが入っているクリップを探して",
                max_chars=assistant.MAX_OLLAMA_CONTEXT_CHARS,
            )

            self.assertEqual(context.total_items, 1)
            self.assertIn(f"clip:{kimi_id}", {item.key for item in context.items})
            self.assertEqual(context.clip_search.fields, ["title"])
        finally:
            connection.close()

    def test_project_scope_search_does_not_include_matching_clip_from_another_project(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("別",))
            other_project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/current", "Kimi対象", project_id),
            )
            current_clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/other", "Kimi外部", other_project_id),
            )
            connection.commit()

            context = assistant._retrieval_context(
                connection,
                project_id,
                "project",
                "Kimiのクリップを探して",
                max_chars=assistant.MAX_OLLAMA_CONTEXT_CHARS,
            )

            self.assertEqual([item.key for item in context.items], [f"clip:{current_clip_id}"])
        finally:
            connection.close()

    def test_follow_up_attachment_reuses_the_previous_user_search_terms(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title) VALUES (?, ?)",
                ("https://example.com/kimi", "Meet Kimi K3"),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            self._insert_history_pair(connection, project_id, "タイトルにKimiが入っているものを探して", "Kimiを見つけました。")
            connection.commit()

            context = assistant._retrieval_context(
                connection,
                project_id,
                "all",
                "それをすべて添付して",
                max_chars=assistant.MAX_OLLAMA_CONTEXT_CHARS,
            )

            self.assertEqual(context.search_terms, ("Kimi",))
            self.assertIn(f"clip:{clip_id}", {item.key for item in context.items})
            self.assertEqual(context.clip_search.fields, ["title"])
        finally:
            connection.close()

    def test_tag_search_and_all_attachment_use_a_query_proposal(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO tags(name) VALUES (?)", ("AMV",))
            tag_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for index in range(125):
                connection.execute(
                    "INSERT INTO clips(url, title) VALUES (?, ?)",
                    (f"https://example.com/amv-{index}", f"編集素材 {index}"),
                )
                clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute("INSERT INTO clip_tags(clip_id, tag_id) VALUES (?, ?)", (clip_id, tag_id))
            connection.commit()

            fake_answer = json.dumps({"answer": "AMVを検索しました。", "source_ids": [], "actions": []}, ensure_ascii=False)
            with patch.object(assistant, "_secret_store", FakeSecretStore({"openai": "sk-test"})), patch.object(
                assistant, "_call_provider", return_value=fake_answer
            ):
                result = assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(
                        message="タグがAMVのクリップをすべて添付して",
                        provider="openai",
                        scope="all",
                    ),
                )

            self.assertEqual(len(result.actions), 1)
            action = result.actions[0]
            self.assertEqual(action.operation, "attach_clip")
            self.assertEqual(action.clip_ids, [])
            self.assertEqual(action.matched_count, 125)
            self.assertIsNotNone(action.clip_search)
            self.assertEqual(action.clip_search.fields, ["tags"])

            execution = assistant.execute_project_assistant_action(
                connection,
                project_id,
                assistant.ProjectAssistantActionDecisionRequest(
                    proposal_id=action.proposal_id,
                    decision="once",
                ),
            )
            self.assertEqual(execution.status, "executed")
            self.assertEqual(len(execution.affected_ids), 125)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM project_clips WHERE project_id = ?", (project_id,)
                ).fetchone()[0],
                125,
            )
        finally:
            connection.close()

    def test_project_context_excludes_current_project_but_keeps_attached_items(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name, description) VALUES (?, ?)", ("現在のプロジェクト", "概要"))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/clip", "添付クリップ", project_id),
            )
            connection.execute("INSERT INTO tasks(title, project_id) VALUES (?, ?)", ("添付タスク", project_id))
            connection.execute("INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)", ("添付メモ", "本文", project_id))
            connection.commit()

            context = assistant._project_context(connection, project_id)

            self.assertNotIn(f"project:{project_id}", {item.key for item in context.items})
            self.assertNotIn("現在のプロジェクト", context.prompt)
            self.assertIn("添付クリップ", context.prompt)
            self.assertIn("添付タスク", context.prompt)
            self.assertIn("添付メモ", context.prompt)
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
            self.assertEqual(result.sources[0].href, "https://example.com")
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual(history.messages[-1].sources[0].href, "https://example.com")
        finally:
            connection.close()

    def test_local_clip_does_not_expose_a_file_path_as_source_link(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, clip_type, project_id) VALUES (?, ?, ?, ?)",
                ("local://C:/Users/example/secret.mov", "ローカル素材", "local", project_id),
            )
            connection.commit()
            context = assistant._project_context(connection, project_id)
            clip = next(item for item in context.items if item.kind == "clip")
            self.assertEqual(clip.href, "")
        finally:
            connection.close()

    def test_non_json_ollama_prose_recovers_source_links_and_newlines(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("鳴潮AMV",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            clips = [
                ("https://example.com/133", "Wuthering Waves - NOBATIDÃO | [GMV/EDIT]"),
                ("https://example.com/131", "Wuthering Waves - 505 | [GMV/EDIT]"),
                ("https://example.com/117", "The Clarity(Wuthering Waves)"),
            ]
            for url, title in clips:
                connection.execute(
                    "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                    (url, title, project_id),
                )
            connection.commit()
            store = FakeSecretStore({"openai": "sk-test"})
            raw_answer = (
                "鳴潮のAMVに関連するクリップは以下です。¥n¥n"
                "- clip:133 | Wuthering Waves - NOBATIDÃO | [GMV/EDIT] ¥n"
                "- clip:131 | Wuthering Waves - 505 | [GMV/EDIT] ¥n"
                "- clip:117(『The Clarity(Wuthering Waves)』)¥n¥n"
                "clip:130以降の情報は参照データにありません。"
            )
            with patch.object(assistant, "_secret_store", store), patch.object(
                assistant, "_call_provider", return_value=raw_answer
            ):
                result = assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(
                        message="鳴潮のAMVだけ探して",
                        provider="openai",
                    ),
                )

            self.assertIn("\n- clip:133", result.answer)
            self.assertNotIn("¥n", result.answer)
            self.assertEqual(
                [(source.kind, source.id) for source in result.sources],
                [("clip", 1), ("clip", 2), ("clip", 3)],
            )
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual(
                [(source.kind, source.id) for source in history.messages[-1].sources],
                [("clip", 1), ("clip", 2), ("clip", 3)],
            )
        finally:
            connection.close()

    def test_ollama_requests_json_mode_and_retries_older_server(self):
        calls = []

        def request_json(provider, url, headers, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise assistant.ProviderRequestError(502, "unsupported", provider_status=400)
            return {"choices": [{"message": {"content": "{}"}}]}

        with patch.object(assistant, "_request_json", side_effect=request_json):
            answer = assistant._call_provider(
                assistant.PROVIDER_MAP["ollama"],
                None,
                "system",
                "user",
                "qwen3.5:2b",
                "http://127.0.0.1:11434",
            )

        self.assertEqual(answer, "{}")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", calls[1])
        self.assertEqual(calls[0]["options"]["temperature"], 0)

    def test_gemini_requests_structured_json_and_retries_without_schema(self):
        calls = []

        def request_json(provider, url, headers, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise assistant.ProviderRequestError(502, "unsupported", provider_status=400)
            return {"candidates": [{"content": {"parts": [{"text": '{"answer":"Gemini answer"}'}]}}]}

        with patch.object(assistant, "_request_json", side_effect=request_json):
            answer = assistant._call_provider(
                assistant.PROVIDER_MAP["gemini"],
                "secret-key",
                "system",
                "user",
                "gemini-3.1-flash-lite",
            )

        self.assertEqual(answer, '{"answer":"Gemini answer"}')
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0]["generationConfig"]["responseFormat"],
            {"text": {"mimeType": "application/json", "schema": assistant.GEMINI_RESPONSE_SCHEMA}},
        )
        self.assertNotIn("responseFormat", calls[1]["generationConfig"])

    def test_gemini_escaped_and_truncated_json_is_unwrapped(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("鳴潮AMV",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                ("https://example.com/133", "Wuthering Waves - NOBATIDÃO | [GMV/EDIT]", project_id),
            )
            clip_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()
            context = assistant._project_context(connection, project_id)

            escaped_json = (
                '{"answer":"鳴潮のAMVです¥ud83d¥udc95¥n'
                '¥"Wuthering Waves¥"を参照しました。",'
                f'"source_ids":["clip:{clip_id}"],"actions":[]}}'
            )
            answer, sources, actions = assistant._parse_model_answer(escaped_json, context)
            self.assertIn("💕", answer)
            self.assertIn("\n", answer)
            self.assertNotIn("¥u", answer)
            self.assertNotIn('"source_ids"', answer)
            self.assertEqual([(source.kind, source.id) for source in sources], [("clip", clip_id)])
            self.assertEqual(actions, [])

            truncated_json = (
                '{"answer":"参照データに含まれる鳴潮クリップです¥n'
                '- Wuthering Waves - NOBATIDÃO | [GMV/EDIT]'
            )
            answer, sources, actions = assistant._parse_model_answer(truncated_json, context)
            self.assertFalse(answer.startswith("{"))
            self.assertIn("Wuthering Waves - NOBATIDÃO", answer)
            self.assertEqual([(source.kind, source.id) for source in sources], [("clip", clip_id)])
            self.assertEqual(actions, [])
        finally:
            connection.close()

    def test_malformed_json_answer_is_unwrapped_and_history_is_clean(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("スターレイルAMV",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for url, title in (
                ("https://example.com/160", "MONTAGEM FAMA X YAO GUANG"),
                ("https://example.com/132", "Black Swan max"),
            ):
                connection.execute(
                    "INSERT INTO clips(url, title, project_id) VALUES (?, ?, ?)",
                    (url, title, project_id),
                )
            connection.commit()
            context = assistant._project_context(connection, project_id)
            malformed_json = (
                '{"answer":"スターレイルのAMVクリップの検索結果です\n\n'
                '- clip:160 - MONTAGEM FAMA X YAO GUANG\n'
                '- clip:132 - Black Swan max\n",\n'
                '"source_ids":\n["clip:160",\n"clip:132"]}'
            )

            answer, sources, actions = assistant._parse_model_answer(malformed_json, context)

            self.assertFalse(answer.startswith("{"))
            self.assertIn("スターレイルのAMVクリップの検索結果です", answer)
            self.assertIn("\n- clip:160", answer)
            self.assertNotIn('"source_ids"', answer)
            self.assertEqual([(source.kind, source.id) for source in sources], [("clip", 1), ("clip", 2)])
            self.assertEqual(actions, [])

            connection.execute(
                "INSERT INTO project_assistant_messages "
                "(project_id, role, content, provider, model, scope, context_item_count) "
                "VALUES (?, 'assistant', ?, 'ollama', 'qwen3-9b-q4km:latest', 'project', 2)",
                (project_id, malformed_json),
            )
            connection.commit()
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertFalse(history.messages[-1].content.startswith("{"))
            self.assertNotIn('"source_ids"', history.messages[-1].content)
        finally:
            connection.close()

    def test_note_source_targets_the_note_editor(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO notes(title, body, project_id) VALUES (?, ?, ?)",
                ("対象メモ", "本文", project_id),
            )
            connection.commit()
            context = assistant._project_context(connection, project_id)
            note = next(item for item in context.items if item.kind == "note")
            self.assertEqual(note.href, f"/Note?id={note.id}")
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

    def test_ollama_context_limit_error_is_explained(self):
        error = urllib.error.HTTPError(
            "http://server-pc:11434/v1/chat/completions",
            500,
            "server error",
            {},
            io.BytesIO(b"input length exceeds the context length"),
        )
        with patch.object(assistant.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(assistant.ProviderRequestError) as raised:
                assistant._request_json(
                    assistant.PROVIDER_MAP["ollama"],
                    "http://server-pc:11434/v1/chat/completions",
                    {},
                    {},
                )
        self.assertIn("コンテキスト上限", raised.exception.message)

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

    def test_conversation_history_prompt_keeps_last_five_turns_and_scope_labels(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for index in range(6):
                self._insert_history_pair(
                    connection,
                    project_id,
                    f"質問{index}",
                    f"回答{index}",
                    scope="all" if index == 1 else "project",
                )
            connection.commit()

            prompt = assistant._conversation_history_prompt(connection, project_id, "project")

            self.assertNotIn("質問0", prompt)
            self.assertNotIn("回答0", prompt)
            for index in range(1, 6):
                self.assertIn(f"質問{index}", prompt)
                self.assertIn(f"回答{index}", prompt)
            self.assertIn("[参照範囲: 全て]", prompt)
            self.assertIn("根拠に使用禁止", prompt)
            self.assertGreaterEqual(prompt.count("[参照範囲: プロジェクト内]"), 8)
        finally:
            connection.close()

    def test_project_scope_sends_history_as_context_but_current_project_data_as_grounding(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("別",))
            other_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO clips(url, title, comment, project_id) VALUES (?, ?, ?, ?)",
                ("https://example.com/current", "現在のBGM", "現在の根拠", project_id),
            )
            connection.execute(
                "INSERT INTO clips(url, title, comment, project_id) VALUES (?, ?, ?, ?)",
                ("https://example.com/other", "外部のBGM", "送信対象外", other_id),
            )
            self._insert_history_pair(
                connection,
                project_id,
                "さっきのBGMについて",
                "全て範囲では外部のBGMも候補です。",
                scope="all",
            )
            connection.commit()

            captured = {}
            fake_answer = json.dumps({"answer": "現在のBGMを確認しました。", "source_ids": [], "actions": []})

            def fake_call(*args):
                captured["system"] = args[2]
                captured["user"] = args[3]
                return fake_answer

            with patch.object(assistant, "_secret_store", FakeSecretStore({"openai": "sk-test"})), patch.object(
                assistant, "_call_provider", side_effect=fake_call
            ):
                assistant.ask_project_assistant(
                    connection,
                    project_id,
                    assistant.ProjectAssistantRequest(message="さっきのBGMをもう一度確認して", provider="openai", scope="project"),
                )

            self.assertIn("さっきのBGMについて", captured["user"])
            self.assertIn("[参照範囲: 全て]", captured["user"])
            self.assertIn("<conversation_history>", captured["user"])
            self.assertIn("<project_data>", captured["user"])
            self.assertIn("現在のBGM", captured["user"])
            current_data = captured["user"].split("<project_data>\n", 1)[1].split("\n</project_data>", 1)[0]
            self.assertNotIn("外部のBGM", current_data)
            self.assertIn("根拠に使用禁止", captured["system"])
            self.assertIn("現在のプロジェクトの参照データだけ", captured["system"])
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

    def test_stream_project_assistant_emits_thinking_and_incremental_answer_before_final_history(self):
        connection = make_connection()
        try:
            connection.execute("INSERT INTO projects(name) VALUES (?)", ("ストリーム対象",))
            project_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.commit()
            store = FakeSecretStore({"openai": "sk-test"})
            chunks = iter(
                [
                    assistant._ProviderStreamChunk(thinking="候補を整理中"),
                    assistant._ProviderStreamChunk(content='{"answer":"B'),
                    assistant._ProviderStreamChunk(content='GMを見つけました。","source_ids":[],"actions":[]}'),
                ]
            )
            with patch.object(assistant, "_secret_store", store), patch.object(
                assistant, "_stream_provider", return_value=chunks
            ):
                events = list(
                    assistant.stream_project_assistant(
                        connection,
                        project_id,
                        assistant.ProjectAssistantRequest(message="BGMを探して", provider="openai"),
                    )
                )

            serialized = b"".join(events).decode("utf-8")
            self.assertIn("event: thinking_delta", serialized)
            self.assertIn('"text":"候補を整理中"', serialized)
            self.assertIn("event: answer_delta", serialized)
            self.assertIn('"text":"B"', serialized)
            self.assertIn('"text":"GMを見つけました。"', serialized)
            self.assertIn("event: complete", serialized)
            self.assertIn("event: done", serialized)
            history = assistant.get_project_assistant_history(connection, project_id)
            self.assertEqual([message.content for message in history.messages], ["BGMを探して", "BGMを見つけました。"])
        finally:
            connection.close()

    def test_ollama_stream_reads_native_thinking_and_content_fields(self):
        class FakeStreamResponse:
            def __init__(self, lines):
                self.lines = iter(lines)

            def readline(self):
                return next(self.lines, b"")

            def close(self):
                return None

        response = FakeStreamResponse(
            [
                '{"message":{"thinking":"考え中","content":""}}\n'.encode("utf-8"),
                '{"message":{"thinking":"","content":"{\\\"answer\\\":\\\"OK\\\"}"}}\n'.encode("utf-8"),
            ]
        )
        with patch.object(assistant, "_stream_request", return_value=response):
            chunks = list(
                assistant._ollama_stream_chunks(
                    assistant.PROVIDER_MAP["ollama"],
                    None,
                    "system",
                    "user",
                    "qwen3:latest",
                    "http://127.0.0.1:11434",
                    native=True,
                    include_thinking=True,
                )
            )
        self.assertEqual(chunks[0].thinking, "考え中")
        self.assertEqual(chunks[1].content, '{"answer":"OK"}')


if __name__ == "__main__":
    unittest.main()
