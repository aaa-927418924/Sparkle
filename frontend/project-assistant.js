(() => {
  "use strict";

  const API = window.location.origin;
  const state = {
    projectId: null,
    providers: null,
    open: false,
    returnFocus: null,
    controller: null,
    requestId: 0,
    previousLayoutAriaHidden: null,
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    button: $("projectAssistantBtn"),
    availability: $("projectAssistantAvailability"),
    modal: $("projectAssistantModal"),
    dialog: document.querySelector("#projectAssistantModal .project-assistant-dialog"),
    close: $("projectAssistantClose"),
    setup: $("projectAssistantSetup"),
    setupMessage: $("projectAssistantSetupMessage"),
    form: $("projectAssistantForm"),
    message: $("projectAssistantMessage"),
    status: $("projectAssistantStatus"),
    submit: $("projectAssistantSubmit"),
    result: $("projectAssistantResult"),
    provider: $("projectAssistantProvider"),
    answer: $("projectAssistantAnswer"),
    sources: $("projectAssistantSources"),
    sourceList: $("projectAssistantSourceList"),
  };

  const providerLabels = {
    deepseek: "DeepSeek",
    gemini: "Gemini",
    openai: "OpenAI",
  };

  function configuredProviders() {
    return (state.providers?.providers || []).filter((provider) => provider.configured);
  }

  function updateTrigger() {
    if (!els.button) return;
    const configured = configuredProviders();
    els.button.disabled = state.projectId == null;
    if (!state.providers) {
      els.availability.textContent = "確認中…";
      return;
    }
    if (!state.providers.available) {
      els.availability.textContent = "利用不可";
      els.button.title = state.providers.availability_message || "AIプロバイダーを利用できません";
      return;
    }
    els.availability.textContent = configured.length ? "利用可能" : "未設定";
    els.button.title = configured.length
      ? "このプロジェクトについてAIに質問"
      : "設定画面でAPIキーを登録すると利用できます";
  }

  async function loadProviders() {
    try {
      const response = await fetch(`${API}/ai/providers`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      state.providers = data;
    } catch (error) {
      state.providers = {
        available: false,
        availability_message: "AIプロバイダーの状態を確認できません。",
        active_provider: null,
        providers: [],
      };
    }
    updateTrigger();
    return state.providers;
  }

  function setLayoutInert(inert) {
    const layout = document.querySelector(".projects-page .layout");
    if (!layout) return;
    if (inert) {
      state.previousLayoutAriaHidden = layout.getAttribute("aria-hidden");
      layout.setAttribute("inert", "");
      layout.setAttribute("aria-hidden", "true");
      document.body.classList.add("project-assistant-open");
    } else {
      layout.removeAttribute("inert");
      if (state.previousLayoutAriaHidden === null) layout.removeAttribute("aria-hidden");
      else layout.setAttribute("aria-hidden", state.previousLayoutAriaHidden);
      state.previousLayoutAriaHidden = null;
      document.body.classList.remove("project-assistant-open");
    }
  }

  function focusableElements() {
    if (!els.dialog) return [];
    return [...els.dialog.querySelectorAll(
      'button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((element) => !element.hidden && element.getClientRects().length > 0);
  }

  function setStatus(message, isError = false) {
    if (!els.status) return;
    els.status.textContent = message;
    els.status.classList.toggle("is-error", isError);
  }

  function resetResult() {
    els.result.hidden = true;
    els.answer.textContent = "";
    els.provider.textContent = "";
    els.sourceList.replaceChildren();
    els.sources.hidden = true;
  }

  function showProviderSetup(providers) {
    const configured = configuredProviders();
    const available = providers?.available !== false;
    els.setup.hidden = available && configured.length > 0;
    els.form.hidden = !available || configured.length === 0;
    if (!available) {
      els.setupMessage.textContent = providers?.availability_message || "AIプロバイダーを利用できません。";
    } else if (!configured.length) {
      els.setupMessage.textContent = "利用するAIプロバイダーのAPIキーが設定されていません。";
    }
  }

  function sourceLabel(source) {
    const labels = { project: "プロジェクト", clip: "クリップ", note: "メモ", task: "タスク" };
    return `${labels[source.kind] || "項目"}: ${source.title || "（無題）"}`;
  }

  function renderSources(sources) {
    els.sourceList.replaceChildren();
    const safeSources = Array.isArray(sources) ? sources : [];
    els.sources.hidden = safeSources.length === 0;
    for (const source of safeSources) {
      const link = document.createElement("a");
      link.className = "project-assistant-source";
      link.href = typeof source.href === "string" && source.href.startsWith("/") ? source.href : "#";
      link.textContent = sourceLabel(source);
      if (source.excerpt) link.title = source.excerpt;
      els.sourceList.append(link);
    }
  }

  async function openAssistant() {
    if (state.projectId == null || !els.modal) return;
    state.returnFocus = document.activeElement;
    state.open = true;
    setLayoutInert(true);
    els.modal.hidden = false;
    els.message.value = "";
    resetResult();
    setStatus("プロバイダーの設定を確認しています…");
    els.form.hidden = true;
    els.setup.hidden = true;
    els.dialog?.focus({ preventScroll: true });

    const providers = await loadProviders();
    if (!state.open) return;
    showProviderSetup(providers);
    setStatus(els.form.hidden ? "" : "プロジェクトの内容だけを参照します。");
    if (!els.form.hidden) els.message.focus({ preventScroll: true });
  }

  function closeAssistant() {
    if (!state.open) return;
    state.open = false;
    state.requestId += 1;
    state.controller?.abort();
    state.controller = null;
    els.modal.hidden = true;
    setLayoutInert(false);
    const target = state.returnFocus;
    state.returnFocus = null;
    if (target && typeof target.focus === "function" && target.isConnected) target.focus({ preventScroll: true });
  }

  async function askAssistant(event) {
    event.preventDefault();
    if (state.projectId == null || els.submit.disabled) return;
    const message = els.message.value.trim();
    if (!message) {
      setStatus("質問を入力してください。", true);
      els.message.focus();
      return;
    }

    const requestId = ++state.requestId;
    state.controller?.abort();
    state.controller = new AbortController();
    els.submit.disabled = true;
    els.message.disabled = true;
    els.result.hidden = true;
    setStatus("回答を生成しています…");
    try {
      const response = await fetch(`${API}/projects/${state.projectId}/assistant`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message }),
        signal: state.controller.signal,
      });
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) throw new Error(data.detail || "回答を取得できませんでした。");
      if (requestId !== state.requestId || !state.open) return;

      els.result.hidden = false;
      els.answer.textContent = data.answer || "回答がありませんでした。";
      const providerLabel = providerLabels[data.provider] || data.provider || "AI";
      els.provider.textContent = data.model ? `${providerLabel} / ${data.model}` : providerLabel;
      renderSources(data.sources);
      const count = Number(data.context_item_count || 0);
      setStatus(`プロジェクト内の${count}件の項目を参照しました。${data.context_truncated ? "一部は上限により省略されています。" : ""}`);
    } catch (error) {
      if (error.name === "AbortError" || requestId !== state.requestId) return;
      setStatus(error.message || "回答を取得できませんでした。", true);
    } finally {
      if (requestId === state.requestId) {
        els.submit.disabled = false;
        els.message.disabled = false;
        state.controller = null;
      }
    }
  }

  function setProject(projectId) {
    const numeric = projectId == null ? null : Number(projectId);
    const next = Number.isInteger(numeric) && numeric > 0 ? numeric : null;
    if (state.open && next !== state.projectId) closeAssistant();
    state.projectId = next;
    updateTrigger();
  }

  els.button?.addEventListener("click", openAssistant);
  els.close?.addEventListener("click", closeAssistant);
  els.form?.addEventListener("submit", askAssistant);
  els.modal?.addEventListener("click", (event) => {
    if (event.target === els.modal) closeAssistant();
  });
  document.addEventListener("keydown", (event) => {
    if (!state.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeAssistant();
      return;
    }
    if (event.key !== "Tab") return;
    const elements = focusableElements();
    if (!elements.length) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  window.projectAssistant = Object.freeze({
    setProject,
    refresh: loadProviders,
  });
  updateTrigger();
  loadProviders();
})();
