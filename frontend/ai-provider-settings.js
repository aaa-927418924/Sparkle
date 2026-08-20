(() => {
  "use strict";

  const API = window.location.origin;
  const providerNames = { deepseek: "DeepSeek", gemini: "Gemini", openai: "OpenAI" };
  let state = null;

  const $ = (id) => document.getElementById(id);
  const activeSelect = $("aiActiveProvider");
  const activeStatus = $("aiActiveProviderStatus");

  async function readResponse(response) {
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  }

  function card(providerId) {
    return document.querySelector(`[data-ai-provider="${providerId}"]`);
  }

  function setMessage(providerId, message, isError = false) {
    const element = $(`aiProviderMessage-${providerId}`);
    if (!element) return;
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  }

  function setCardBusy(providerId, busy) {
    const element = card(providerId);
    if (!element) return;
    element.querySelectorAll("button, input").forEach((control) => { control.disabled = busy; });
  }

  function render() {
    if (!state || !activeSelect || !activeStatus) return;
    activeSelect.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = state.available ? "APIキーを保存してください" : "資格情報マネージャーを利用できません";
    activeSelect.append(placeholder);

    for (const provider of state.providers || []) {
      const option = document.createElement("option");
      option.value = provider.id;
      option.textContent = `${provider.label}（${provider.configured ? "設定済み" : "未設定"}）`;
      option.disabled = !provider.configured;
      activeSelect.append(option);

      const status = $(`aiProviderStatus-${provider.id}`);
      if (status) {
        status.textContent = provider.configured ? (provider.active ? "使用中" : "設定済み") : "未設定";
        status.classList.toggle("is-active", provider.active);
      }
      const model = $(`aiProviderModel-${provider.id}`);
      if (model && !model.matches(":focus")) model.value = provider.model || provider.default_model || "";
      const save = document.querySelector(`[data-ai-save="${provider.id}"]`);
      const remove = document.querySelector(`[data-ai-delete="${provider.id}"]`);
      if (save) save.disabled = !state.available;
      if (remove) remove.disabled = !state.available || !provider.configured;
    }
    if (state.active_provider) activeSelect.value = state.active_provider;
    activeSelect.disabled = !state.available;
    activeStatus.textContent = state.available
      ? (state.active_provider ? `${providerNames[state.active_provider] || state.active_provider}を使用します。` : "APIキーを保存すると選択できます。")
      : (state.availability_message || "状態を確認できません。");
  }

  async function load() {
    try {
      const response = await fetch(`${API}/ai/providers`, { headers: { Accept: "application/json" } });
      state = await readResponse(response);
    } catch (error) {
      state = { available: false, availability_message: "AIプロバイダーの状態を確認できません。", providers: [] };
    }
    render();
  }

  async function saveProvider(providerId) {
    const keyInput = $(`aiProviderKey-${providerId}`);
    const modelInput = $(`aiProviderModel-${providerId}`);
    const current = (state?.providers || []).find((provider) => provider.id === providerId);
    if (current && !current.configured && !keyInput.value.trim()) {
      setMessage(providerId, "APIキーを入力してください。", true);
      keyInput.focus();
      return;
    }
    setCardBusy(providerId, true);
    setMessage(providerId, "保存しています…");
    try {
      const body = { model: modelInput.value.trim() };
      if (keyInput.value.trim()) body.api_key = keyInput.value.trim();
      state = await readResponse(await fetch(`${API}/ai/providers/${providerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      }));
      keyInput.value = "";
      render();
      setMessage(providerId, "保存しました。APIキーは表示されません。");
      window.projectAssistant?.refresh?.();
    } catch (error) {
      setMessage(providerId, error.message || "保存できませんでした。", true);
    } finally {
      setCardBusy(providerId, false);
      render();
    }
  }

  async function deleteProvider(providerId) {
    const name = providerNames[providerId] || "このプロバイダー";
    if (!window.confirm(`${name}のAPIキーを削除します。よろしいですか？`)) return;
    setCardBusy(providerId, true);
    setMessage(providerId, "削除しています…");
    try {
      state = await readResponse(await fetch(`${API}/ai/providers/${providerId}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      }));
      render();
      setMessage(providerId, "APIキーを削除しました。");
      window.projectAssistant?.refresh?.();
    } catch (error) {
      setMessage(providerId, error.message || "削除できませんでした。", true);
    } finally {
      setCardBusy(providerId, false);
      render();
    }
  }

  async function changeActiveProvider() {
    const providerId = activeSelect.value;
    if (!providerId || providerId === state?.active_provider) return;
    activeSelect.disabled = true;
    activeStatus.textContent = "切り替えています…";
    try {
      state = await readResponse(await fetch(`${API}/ai/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ active_provider: providerId }),
      }));
      render();
      window.projectAssistant?.refresh?.();
    } catch (error) {
      activeStatus.textContent = error.message || "切り替えできませんでした。";
      render();
    }
  }

  document.querySelectorAll("[data-ai-save]").forEach((button) => {
    button.addEventListener("click", () => saveProvider(button.dataset.aiSave));
  });
  document.querySelectorAll("[data-ai-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteProvider(button.dataset.aiDelete));
  });
  activeSelect?.addEventListener("change", changeActiveProvider);
  load();
})();
