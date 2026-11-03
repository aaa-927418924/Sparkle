"""AI requests for plugins, routed through Sparkle's configured provider."""

from __future__ import annotations

from sqlite3 import Connection
import urllib.parse

import project_assistant as providers


def generate_plugin_ai_response(
    db: Connection,
    *,
    system_prompt: str | None,
    prompt: str,
) -> dict[str, str]:
    """Generate plain text using the active provider without exposing its key."""
    system_text = (system_prompt or "").strip() or "You are a helpful assistant."
    user_text = prompt.strip()
    if not user_text:
        raise providers.ProjectAssistantError(422, "AIに送るメッセージを入力してください。")
    if len(system_text) > 4_000 or len(user_text) > 32_000:
        raise providers.ProjectAssistantError(422, "AIへの入力が上限を超えています。")

    settings = providers.get_ai_provider_settings(db)
    if not settings.available:
        raise providers.ProjectAssistantError(
            503,
            settings.availability_message or "AIプロバイダーを利用できません。",
        )
    if not settings.active_provider:
        raise providers.ProjectAssistantError(409, "設定画面でAIプロバイダーを設定してください。")

    spec = providers._spec_for(settings.active_provider)
    status = next((item for item in settings.providers if item.id == spec.id), None)
    if status is None or not status.configured:
        raise providers.ProjectAssistantError(409, providers._configuration_message(spec))
    store = providers._get_secret_store()
    api_key = store.get(spec.id)
    if spec.requires_api_key and not api_key:
        raise providers.ProjectAssistantError(409, providers._configuration_message(spec))

    model = providers._stored_model(db, spec)
    base_url = providers._stored_base_url(db, spec)
    if spec.id == "deepseek":
        body = providers._request_json(
            spec,
            "https://api.deepseek.com/chat/completions",
            {"Authorization": f"Bearer {api_key}"},
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 2_000,
            },
        )
        answer = providers._deepseek_text(body)
    elif spec.id == "gemini":
        model_path = model if model.startswith("models/") else f"models/{model}"
        encoded_model = urllib.parse.quote(model_path, safe="/-_.")
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/{encoded_model}:generateContent"
        body = providers._request_json(
            spec,
            endpoint,
            {"x-goog-api-key": api_key or ""},
            {
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                "generationConfig": {"maxOutputTokens": 2_000, "temperature": 0.7},
            },
        )
        answer = providers._gemini_text(body)
    elif spec.id == "openai":
        body = providers._request_json(
            spec,
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {api_key}"},
            {
                "model": model,
                "instructions": system_text,
                "input": user_text,
                "max_output_tokens": 2_000,
            },
        )
        answer = providers._openai_text(body)
    else:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body = providers._request_json(
            spec,
            providers._ollama_endpoint(base_url or spec.default_base_url or ""),
            headers,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 2_000},
            },
        )
        answer = providers._deepseek_text(body)

    if not answer:
        raise providers.ProviderRequestError(502, f"{spec.label}から回答を受け取れませんでした。")
    return {"response": answer[: providers.MAX_PROVIDER_RESPONSE_BYTES], "provider": spec.id, "model": model}
