import unittest
from unittest.mock import patch

import plugin_ai
from db import _SCHEMA, _migrate
import sqlite3


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, provider):
        return self.values.get(provider)


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    _migrate(connection)
    return connection


class PluginAITests(unittest.TestCase):
    def test_ai_request_uses_configured_provider_without_returning_credential(self):
        connection = make_connection()
        try:
            secret = "sk-plugin-ai-test-secret"
            with patch.object(plugin_ai.providers, "_secret_store", FakeSecretStore({"openai": secret})), patch.object(
                plugin_ai.providers,
                "_request_json",
                return_value={"output_text": "A concise answer"},
            ) as request:
                result = plugin_ai.generate_plugin_ai_response(
                    connection,
                    system_prompt="Be concise",
                    prompt="Summarize the notes",
                )

            self.assertEqual(result["response"], "A concise answer")
            self.assertEqual(result["provider"], "openai")
            self.assertNotIn(secret, repr(result))
            self.assertEqual(request.call_args.args[2]["Authorization"], f"Bearer {secret}")
            self.assertEqual(request.call_args.args[3]["input"], "Summarize the notes")
        finally:
            connection.close()

    def test_ai_request_requires_a_configured_provider_and_bounded_prompt(self):
        connection = make_connection()
        try:
            with patch.object(plugin_ai.providers, "_secret_store", FakeSecretStore()):
                with self.assertRaises(plugin_ai.providers.ProjectAssistantError) as raised:
                    plugin_ai.generate_plugin_ai_response(
                        connection,
                        system_prompt=None,
                        prompt="Hello",
                    )
                self.assertEqual(raised.exception.status_code, 409)

                with patch.object(
                    plugin_ai.providers,
                    "_secret_store",
                    FakeSecretStore({"openai": "secret"}),
                ):
                    with self.assertRaises(plugin_ai.providers.ProjectAssistantError) as raised:
                        plugin_ai.generate_plugin_ai_response(
                            connection,
                            system_prompt="",
                            prompt="x" * 32_001,
                        )
                    self.assertEqual(raised.exception.status_code, 422)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
