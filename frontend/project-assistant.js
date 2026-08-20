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
    pendingGeneration: null,
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
    scope: $("projectAssistantScope"),
    description: $("projectAssistantDescription"),
    privacy: $("projectAssistantPrivacy"),
    messages: $("projectAssistantMessages"),
    actions: $("projectAssistantActions"),
    actionList: $("projectAssistantActionList"),
    clearHistory: $("projectAssistantClearHistory"),
    status: $("projectAssistantStatus"),
    scopeProject: $("projectAssistantScopeProject"),
    scopeAll: $("projectAssistantScopeAll"),
  };

  const providerLabels = {
    deepseek: "DeepSeek",
    gemini: "Gemini",
    openai: "OpenAI",
    ollama: "Ollama",
  };
  const scopeLabels = { project: "プロジェクト内", all: "全て" };
  const actionLabels = {
    attach_clip: "クリップ添付",
    create_note: "メモ作成",
    edit_note: "メモ編集",
  };
  const decisionLabels = {
    once: "一回のみ許可",
    always: "常に許可",
    deny: "許可しない",
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
      ? "このプロジェクトについてAIに質問・依頼"
      : "設定画面でAIプロバイダーを設定すると利用できます";
  }

  async function loadProviders() {
    try {
      const response = await fetch(`${API}/ai/providers`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      state.providers = data;
    } catch {
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

  async function loadHistory() {
    if (state.projectId == null || !els.messages) return;
    try {
      const response = await fetch(`${API}/projects/${state.projectId}/assistant/history?limit=100`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      renderHistory(data.messages);
    } catch {
      els.messages.replaceChildren();
      appendBubble("assistant", "過去の履歴を読み込めませんでした。新しい質問は続けて利用できます。", { error: true });
    }
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

  function setStatus(message, isError = false, generating = false) {
    if (!els.status) return;
    els.status.textContent = message;
    els.status.classList.toggle("is-error", isError);
    els.status.classList.toggle("is-generating", generating);
  }

  function updateScopeCopy() {
    const scope = els.scope?.checked ? "all" : "project";
    els.scope?.setAttribute("aria-checked", String(scope === "all"));
    els.scope?.setAttribute("aria-label", `参照範囲: ${scopeLabels[scope]}`);
    els.scopeProject?.classList.toggle("is-active", scope === "project");
    els.scopeAll?.classList.toggle("is-active", scope === "all");
    if (els.description) {
      els.description.textContent = scope === "all"
        ? "アプリ内のプロジェクト・クリップ・メモ・タスクを参照して回答します。"
        : "このプロジェクトに紐づくクリップ・メモ・タスクだけを参照して回答します。";
    }
    if (els.privacy) {
      els.privacy.textContent = scope === "all"
        ? "質問すると、アプリ内で選択されたデータがAIプロバイダーへ送信されます。ローカルファイルの絶対パスは送信しません。"
        : "質問すると、このプロジェクトの内容が設定したAIプロバイダーへ送信されます。ローカルファイルの絶対パスは送信しません。";
    }
  }

  function showProviderSetup(providers) {
    const configured = configuredProviders();
    const available = providers?.available !== false;
    els.setup.hidden = available && configured.length > 0;
    els.form.hidden = !available || configured.length === 0;
    if (!available) {
      els.setupMessage.textContent = providers?.availability_message || "AIプロバイダーを利用できません。";
    } else if (!configured.length) {
      els.setupMessage.textContent = "APIキーまたはOllamaのBase URLを設定してください。";
    }
  }

  function appendBubble(role, content, options = {}) {
    const bubble = document.createElement("article");
    bubble.className = `project-assistant-message-bubble is-${role}${options.generating ? " is-generating" : ""}${options.error ? " is-error" : ""}`;
    bubble.dataset.role = role;
    const meta = document.createElement("div");
    meta.className = "project-assistant-message-meta";
    meta.textContent = role === "user" ? "あなた" : (options.provider || "専属AI");
    const body = document.createElement("div");
    body.className = "project-assistant-message-content";
    body.textContent = String(content ?? "");
    bubble.append(meta, body);

    els.messages?.append(bubble);
    if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
    return bubble;
  }

  function safeSourceHref(value) {
    if (typeof value !== "string") return "";
    const href = value.trim();
    if (!href) return "";
    if (href.startsWith("/")) return href;
    try {
      const parsed = new URL(href, window.location.origin);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
    } catch {
      return "";
    }
  }

  function appendSources(container, sources) {
    const safeSources = Array.isArray(sources) ? sources : [];
    if (!safeSources.length) return;
    const section = document.createElement("div");
    section.className = "project-assistant-message-sources";
    const label = document.createElement("span");
    label.textContent = "参照した項目";
    section.append(label);
    for (const source of safeSources) {
      const kindLabels = { project: "プロジェクト", clip: "クリップ", note: "メモ", task: "タスク" };
      const sourceLabel = `${kindLabels[source.kind] || "項目"}: ${source.title || "（無題）"}`;
      const item = document.createElement("div");
      item.className = "project-assistant-source";
      const text = document.createElement("span");
      text.className = "project-assistant-source-label";
      text.textContent = sourceLabel;
      if (source.excerpt) item.title = source.excerpt;
      item.append(text);
      const href = safeSourceHref(source.href);
      if (href) {
        const link = document.createElement("a");
        link.className = "project-assistant-source-link";
        link.href = href;
        link.textContent = "開く";
        link.title = `${sourceLabel}を開く`;
        link.setAttribute("aria-label", `${sourceLabel}を開く`);
        try {
          if (new URL(href, window.location.origin).origin !== window.location.origin) {
            link.target = "_blank";
            link.rel = "noopener noreferrer";
          }
        } catch {}
        item.append(link);
      }
      section.append(item);
    }
    container.append(section);
  }

  function appendAssistantAnswer(data) {
    const providerLabel = providerLabels[data.provider] || data.provider || "AI";
    const bubble = appendBubble("assistant", data.answer || "回答がありませんでした。", {
      provider: data.model ? `${providerLabel} / ${data.model}` : providerLabel,
    });
    appendSources(bubble, data.sources);
    return bubble;
  }

  function renderHistory(messages) {
    els.messages?.replaceChildren();
    for (const message of Array.isArray(messages) ? messages : []) {
      const bubble = appendBubble(message.role, message.content, {
        provider: message.provider ? `${providerLabels[message.provider] || message.provider}${message.model ? ` / ${message.model}` : ""}` : "専属AI",
      });
      if (message.role === "assistant") {
        const scope = document.createElement("span");
        scope.className = "project-assistant-message-scope";
        scope.textContent = `参照範囲: ${scopeLabels[message.scope] || "プロジェクト内"}`;
        bubble.querySelector(".project-assistant-message-meta")?.append(" · ", scope);
        appendSources(bubble, message.sources);
      }
    }
  }

  function closeActionDialog(restoreFocus = true) {
    if (!els.actions || !els.actionList) return;
    els.actions.hidden = true;
    els.actionList.replaceChildren();
    if (restoreFocus && state.open && !els.form.hidden && !els.message.disabled) {
      els.message.focus({ preventScroll: true });
    }
  }

  function removeResolvedAction(card) {
    card.remove();
    if (els.actionList?.children.length) {
      els.actionList.querySelector("button:not([disabled])")?.focus({ preventScroll: true });
      return;
    }
    closeActionDialog();
  }

  function renderActionPlans(actions) {
    els.actionList?.replaceChildren();
    const plans = Array.isArray(actions) ? actions : [];
    els.actions.hidden = plans.length === 0;
    for (const plan of plans) {
      const card = document.createElement("article");
      card.className = "project-assistant-action-card";
      const title = document.createElement("h4");
      title.textContent = actionLabels[plan.operation] || "変更操作";
      const summary = document.createElement("p");
      summary.textContent = plan.summary || "AIが変更操作を提案しました。";
      const status = document.createElement("p");
      status.className = "project-assistant-action-status";
      const controls = document.createElement("div");
      controls.className = "project-assistant-action-controls";
      card.append(title, summary, status, controls);
      els.actionList.append(card);

      if (plan.permission === "always") {
        status.textContent = "常に許可済みです。実行しています…";
        decideAction(plan, "once", card, status, controls);
        continue;
      }
      status.textContent = "実行するか選択してください。";
      for (const decision of ["once", "always", "deny"]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = decision === "always" ? "modal-btn" : "modal-btn ghost";
        button.textContent = decisionLabels[decision];
        button.addEventListener("click", () => decideAction(plan, decision, card, status, controls));
        controls.append(button);
      }
    }
    if (!els.actions.hidden) {
      els.actionList?.querySelector("button:not([disabled])")?.focus({ preventScroll: true });
    }
  }

  async function decideAction(plan, decision, card, status, controls) {
    controls.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    if (decision !== "deny") status.textContent = decision === "always" ? "常に許可として実行しています…" : "一回のみ実行しています…";
    try {
      const response = await fetch(`${API}/projects/${state.projectId}/assistant/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ proposal_id: plan.proposal_id, decision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "変更操作を実行できませんでした。");
      status.textContent = data.message || (data.status === "denied" ? "今回は実行しませんでした。" : "実行しました。");
      card.classList.add(`is-${data.status || "executed"}`);
      removeResolvedAction(card);
      window.loadAll?.({ silent: true });
    } catch (error) {
      status.textContent = error.message || "変更操作を実行できませんでした。";
      status.classList.add("is-error");
      controls.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
  }

  async function openAssistant() {
    if (state.projectId == null || !els.modal) return;
    state.returnFocus = document.activeElement;
    state.open = true;
    setLayoutInert(true);
    els.modal.hidden = false;
    els.message.value = "";
    closeActionDialog(false);
    els.form.hidden = true;
    els.setup.hidden = true;
    updateScopeCopy();
    setStatus("設定と履歴を確認しています…");
    els.dialog?.focus({ preventScroll: true });

    const [providers] = await Promise.all([loadProviders(), loadHistory()]);
    if (!state.open) return;
    showProviderSetup(providers);
    setStatus(els.form.hidden ? "" : "準備ができました。", false);
    if (!els.form.hidden) els.message.focus({ preventScroll: true });
  }

  function closeAssistant() {
    if (!state.open) return;
    state.open = false;
    state.requestId += 1;
    state.controller?.abort();
    state.controller = null;
    closeActionDialog(false);
    els.modal.hidden = true;
    setLayoutInert(false);
    const target = state.returnFocus;
    state.returnFocus = null;
    if (target && typeof target.focus === "function" && target.isConnected) target.focus({ preventScroll: true });
  }

  async function clearHistory() {
    if (state.projectId == null || !window.confirm("このプロジェクトの専属AI履歴を消去します。続けますか？")) return;
    try {
      const response = await fetch(`${API}/projects/${state.projectId}/assistant/history`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "履歴を消去できませんでした。");
      }
      renderHistory([]);
      setStatus("履歴を消去しました。", false);
    } catch (error) {
      setStatus(error.message || "履歴を消去できませんでした。", true);
    }
  }

  async function askAssistant(event) {
    event?.preventDefault();
    if (state.projectId == null || els.message.disabled) return;
    const message = els.message.value.trim();
    if (!message) {
      setStatus("質問・依頼を入力してください。", true);
      els.message.focus();
      return;
    }

    const requestId = ++state.requestId;
    state.controller?.abort();
    state.controller = new AbortController();
    els.message.disabled = true;
    const scope = els.scope.checked ? "all" : "project";
    appendBubble("user", message);
    const generation = appendBubble("assistant", "生成中…", { generating: true });
    state.pendingGeneration = generation;
    els.message.value = "";
    setStatus("生成中…", false, true);
    try {
      const response = await fetch(`${API}/projects/${state.projectId}/assistant`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message, scope }),
        signal: state.controller.signal,
      });
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) throw new Error(data.detail || "回答を取得できませんでした。");
      if (requestId !== state.requestId || !state.open) return;
      generation.remove();
      state.pendingGeneration = null;
      appendAssistantAnswer(data);
      renderActionPlans(data.actions);
      const count = Number(data.context_item_count || 0);
      setStatus(`${scopeLabels[data.scope] || scopeLabels[scope]}の${count}件を参照しました。${data.context_truncated ? "一部は上限により省略されています。" : ""}`);
    } catch (error) {
      if (error.name === "AbortError" || requestId !== state.requestId) return;
      generation.remove();
      state.pendingGeneration = null;
      appendBubble("assistant", error.message || "回答を取得できませんでした。", { error: true });
      setStatus(error.message || "回答を取得できませんでした。", true);
    } finally {
      if (requestId === state.requestId) {
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
  els.scope?.addEventListener("change", updateScopeCopy);
  els.message?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    askAssistant();
  });
  els.clearHistory?.addEventListener("click", clearHistory);
  els.modal?.addEventListener("click", (event) => {
    if (event.target === els.modal || event.target.matches?.("[data-project-assistant-close]")) closeAssistant();
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
