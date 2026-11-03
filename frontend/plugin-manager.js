(() => {
  "use strict";

  const apiRoot = "/plugins";
  const elements = {
    skillCard: document.getElementById("pluginSkillCard"),
    skillButton: document.getElementById("pluginSkillInstall"),
    skillStatus: document.getElementById("pluginSkillStatus"),
    skillAgents: document.getElementById("pluginSkillAgents"),
    zipLabel: document.getElementById("pluginZipLabel"),
    zipInput: document.getElementById("pluginZipInput"),
    zipFileName: document.getElementById("pluginZipFileName"),
    importStatus: document.getElementById("pluginImportStatus"),
    list: document.getElementById("pluginList"),
    empty: document.getElementById("pluginEmpty"),
    dialog: document.getElementById("pluginPanelDialog"),
    dialogTitle: document.getElementById("pluginPanelTitle"),
    dialogClose: document.getElementById("pluginPanelClose"),
    frame: document.getElementById("pluginPanelFrame"),
    panelStatus: document.getElementById("pluginPanelStatus"),
  };
  if (!elements.list || !elements.skillButton || !elements.dialog) return;

  let plugins = [];
  let activePanelId = null;
  let messageTimes = [];

  function setText(element, value) {
    if (element) element.textContent = String(value || "");
  }

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }

  async function readResponse(response) {
    let body = {};
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    if (!response.ok) {
      const detail = body.detail || "プラグイン操作に失敗しました。";
      throw new Error(String(detail));
    }
    return body;
  }

  async function request(path, options) {
    return readResponse(await fetch(apiRoot + path, options));
  }

  function makeButton(label, action, disabled) {
    const button = node("button", "modal-btn ghost", label);
    button.type = "button";
    button.disabled = disabled === true;
    button.addEventListener("click", action);
    return button;
  }

  function updateToggleLabel(input, checked) {
    const label = input?.parentElement?.querySelector(".plugin-toggle-label");
    setText(label, checked ? "有効" : "無効");
    input?.setAttribute(
      "aria-label",
      (input.parentElement?.closest(".plugin-card")?.querySelector(".plugin-card-title")?.textContent || "プラグイン") +
        "を" + (checked ? "無効" : "有効") + "にする",
    );
  }

  function makeToggle(plugin) {
    const wrapper = node("label", "plugin-toggle");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "plugin-toggle-input";
    input.setAttribute("role", "switch");
    input.checked = Boolean(plugin.enabled);
    input.disabled = Boolean(plugin.error) || !plugin.compatible;
    input.setAttribute("aria-label", (plugin.name || plugin.id) + "を" + (plugin.enabled ? "無効" : "有効") + "にする");
    const track = node("span", "plugin-toggle-track");
    track.setAttribute("aria-hidden", "true");
    const label = node("span", "plugin-toggle-label", plugin.enabled ? "有効" : "無効");
    input.addEventListener("change", () => {
      updateToggleLabel(input, input.checked);
      void togglePlugin(plugin, input);
    });
    wrapper.append(input, track, label);
    return wrapper;
  }

  function statusForPlugin(plugin) {
    if (plugin.error) return "読み込みエラー";
    if (!plugin.compatible) return "このSparkleでは未対応";
    return plugin.enabled ? "有効" : "無効";
  }

  function renderPlugin(plugin) {
    const card = node("article", "plugin-card");
    card.setAttribute("aria-label", plugin.name + "、" + statusForPlugin(plugin));

    const header = node("div", "plugin-card-header");
    const title = node("h4", "plugin-card-title", plugin.name || plugin.id);
    const meta = node(
      "p",
      "plugin-card-meta",
      (plugin.type === "theme" ? "テーマ" : plugin.type === "feature" ? "機能" : "プラグイン") +
        " · v" + (plugin.version || "不明") +
        " · " + statusForPlugin(plugin),
    );
    header.append(title, meta);
    card.append(header);

    if (plugin.description) {
      card.append(node("p", "plugin-card-description", plugin.description));
    }
    if (plugin.contributes) {
      const capabilities = [];
      if (plugin.contributes.sidebar?.label) {
        capabilities.push("サイドバーに「" + plugin.contributes.sidebar.label + "」を追加");
      }
      if (plugin.contributes.project_action?.label) {
        capabilities.push("プロジェクト画面に「" + plugin.contributes.project_action.label + "」を追加");
      }
      if (plugin.contributes.ui?.hide?.length) {
        capabilities.push("指定したUIを非表示");
      }
      if (plugin.contributes.ui?.order && Object.keys(plugin.contributes.ui.order).length) {
        capabilities.push("UIを並び替え");
      }
      if (plugin.contributes.ui?.styles && Object.keys(plugin.contributes.ui.styles).length) {
        capabilities.push("指定UIのスタイルを変更");
      }
      if (capabilities.length) {
        card.append(node("p", "plugin-card-capabilities", "UI寄与: " + capabilities.join("・")));
      }
    }
    if (plugin.error) {
      card.append(node("p", "plugin-card-error", plugin.error));
    }

    const actions = node("div", "plugin-actions");
    if (!plugin.error && plugin.compatible) {
      actions.append(
        makeToggle(plugin),
      );
      if (plugin.type === "theme") {
        actions.append(
          makeButton(
            plugin.active_theme ? "適用中" : "テーマに適用",
            () => void activateTheme(plugin.id),
            !plugin.enabled || plugin.active_theme,
          ),
        );
      }
      if (plugin.type === "feature") {
        actions.append(
          makeButton(
            "開く",
            () => openFeaturePanel(plugin),
            !plugin.enabled,
          ),
        );
      }
      actions.append(makeButton("ZIPでエクスポート", () => void exportPlugin(plugin)));
    }
    actions.append(
      makeButton(
        "削除",
        () => void deletePlugin(plugin),
      ),
    );
    card.append(actions);
    return card;
  }

  function render() {
    elements.list.replaceChildren();
    elements.empty.hidden = plugins.length > 0;
    for (const plugin of plugins) {
      elements.list.append(renderPlugin(plugin));
    }
  }

  async function refresh() {
    try {
      const body = await request("", { cache: "no-store" });
      plugins = Array.isArray(body.plugins) ? body.plugins : [];
      render();
      await refreshAuthoringSkillStatus();
      await window.SparklePluginUI?.refreshUI?.();
      return true;
    } catch (error) {
      setText(elements.importStatus, error.message);
      return false;
    }
  }

  async function syncTheme() {
    try {
      const body = await request("/active-theme", { cache: "no-store" });
      window.SparkleAppearanceTheme?.setPluginTheme(body.theme || null);
    } catch {
      window.SparkleAppearanceTheme?.syncPluginTheme();
    }
  }

  async function togglePlugin(plugin, input) {
    const enabled = input ? input.checked : !plugin.enabled;
    if (input) input.disabled = true;
    try {
      await request("/" + encodeURIComponent(plugin.id) + "/enabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      await syncTheme();
      await refresh();
    } catch (error) {
      if (input) {
        input.checked = Boolean(plugin.enabled);
        input.disabled = false;
        updateToggleLabel(input, input.checked);
      }
      setText(elements.importStatus, error.message);
    }
  }

  async function activateTheme(pluginId) {
    try {
      const body = await request("/active-theme", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plugin_id: pluginId }),
      });
      window.SparkleAppearanceTheme?.setPluginTheme(body.theme || null);
      setText(elements.importStatus, "テーマを適用しました。");
      await refresh();
    } catch (error) {
      setText(elements.importStatus, error.message);
    }
  }

  async function deletePlugin(plugin) {
    const removeData = window.confirm(
      "「" + (plugin.name || plugin.id) + "」を削除しますか？\n\nキャンセルすると削除しません。OKを選ぶとプラグイン専用データも削除します。",
    );
    if (!removeData) return;
    try {
      await request("/" + encodeURIComponent(plugin.id) + "?delete_data=true", {
        method: "DELETE",
      });
      if (activePanelId === plugin.id) closeFeaturePanel();
      await syncTheme();
      setText(elements.importStatus, "プラグインと専用データを削除しました。");
      await refresh();
    } catch (error) {
      setText(elements.importStatus, error.message);
    }
  }

  async function exportPlugin(plugin) {
    try {
      const response = await fetch(
        apiRoot + "/" + encodeURIComponent(plugin.id) + "/export",
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("ZIPを作成できませんでした。");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = plugin.id + ".zip";
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setText(elements.importStatus, error.message);
    }
  }

  function openFeaturePanel(plugin) {
    if (!plugin.enabled || plugin.type !== "feature") return;
    activePanelId = plugin.id;
    messageTimes = [];
    setText(elements.dialogTitle, plugin.name || plugin.id);
    setText(elements.panelStatus, "");
    elements.frame.title = plugin.name || "プラグイン画面";
    elements.frame.src = apiRoot + "/" + encodeURIComponent(plugin.id) + "/panel";
    elements.dialog.showModal();
  }

  function closeFeaturePanel() {
    activePanelId = null;
    elements.frame.src = "about:blank";
    setText(elements.panelStatus, "");
    if (elements.dialog.open) elements.dialog.close();
  }

  function sendPanelResponse(requestId, ok, value, error) {
    if (!elements.frame.contentWindow) return;
    elements.frame.contentWindow.postMessage(
      {
        type: "sparkle-plugin-response",
        requestId,
        ok,
        value,
        error: error || undefined,
      },
      "*",
    );
  }

  function allowPanelMessage() {
    const now = Date.now();
    messageTimes = messageTimes.filter((time) => now - time < 10000);
    if (messageTimes.length >= 50) return false;
    messageTimes.push(now);
    return true;
  }

  async function handlePanelMessage(event) {
    if (!activePanelId || event.source !== elements.frame.contentWindow) return;
    const data = event.data;
    if (!data || data.type !== "sparkle-plugin-request") return;
    if (typeof data.requestId !== "string" || data.requestId.length > 100) return;
    if (!allowPanelMessage()) {
      sendPanelResponse(data.requestId, false, null, "要求が多すぎます。");
      return;
    }
    const plugin = plugins.find((entry) => entry.id === activePanelId);
    if (!plugin || !plugin.enabled) {
      sendPanelResponse(data.requestId, false, null, "プラグインは無効です。");
      return;
    }
    try {
      if (data.method === "notify" && plugin.permissions?.includes("notifications")) {
        if (typeof data.message !== "string" || data.message.length > 500) {
          throw new Error("通知メッセージが長すぎます。");
        }
        setText(elements.panelStatus, data.message);
        sendPanelResponse(data.requestId, true, null);
        return;
      }
      if (
        data.method === "storage.get" &&
        plugin.permissions?.includes("storage") &&
        typeof data.key === "string"
      ) {
        const result = await request(
          "/" + encodeURIComponent(plugin.id) + "/storage/" + encodeURIComponent(data.key),
          { cache: "no-store" },
        );
        sendPanelResponse(data.requestId, true, result.value);
        return;
      }
      if (
        data.method === "storage.set" &&
        plugin.permissions?.includes("storage") &&
        typeof data.key === "string"
      ) {
        const result = await request(
          "/" + encodeURIComponent(plugin.id) + "/storage/" + encodeURIComponent(data.key),
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ value: data.value }),
          },
        );
        sendPanelResponse(data.requestId, true, result.value);
        return;
      }
      throw new Error("プラグインAPIの権限がありません。");
    } catch (error) {
      sendPanelResponse(data.requestId, false, null, error.message);
    }
  }

  function statusLabel(status) {
    return {
      installed: "導入済み",
      updated: "更新済み",
      conflict: "同名スキルがあるため変更していません",
      failed: "導入できませんでした",
    }[status] || "状態不明";
  }

  async function refreshAuthoringSkillStatus() {
    if (!elements.skillCard) return;
    try {
      const result = await request("/authoring-skill/status", { cache: "no-store" });
      elements.skillCard.hidden = result.all_installed !== true;
    } catch {
      // Older Sparkle builds do not expose the status endpoint. Keep the
      // installation control visible so the user can still install the skill.
      elements.skillCard.hidden = false;
    }
  }

  async function installAuthoringSkill() {
    elements.skillButton.disabled = true;
    setText(elements.skillStatus, "3つのAI向けスキルを導入しています…");
    elements.skillAgents.replaceChildren();
    try {
      const result = await request("/install-authoring-skill", { method: "POST" });
      for (const agentResult of result.results || []) {
        const item = node(
          "li",
          "",
          agentResult.agent + ": " + statusLabel(agentResult.status),
        );
        elements.skillAgents.append(item);
      }
      const failures = (result.results || []).filter(
        (entry) => entry.status === "failed" || entry.status === "conflict",
      ).length;
      setText(
        elements.skillStatus,
        failures ? "一部のAIに導入できませんでした。" : "作成スキルを導入しました。必要に応じて各AIを再起動してください。",
      );
      await refreshAuthoringSkillStatus();
    } catch (error) {
      setText(elements.skillStatus, error.message);
    } finally {
      elements.skillButton.disabled = false;
    }
  }

  async function importPlugin() {
    const file = elements.zipInput?.files?.[0];
    if (!file) return;
    setText(elements.zipFileName, file.name);
    if (file.size > 20 * 1024 * 1024) {
      setText(elements.importStatus, "ZIPファイルは20MB以下にしてください。");
      elements.zipInput.value = "";
      setText(elements.zipFileName, "ファイルが選択されていません");
      return;
    }
    setText(elements.importStatus, "ZIPを検査してインポートしています…");
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const plugin = await request("/import", { method: "POST", body: form });
      setText(elements.importStatus, (plugin.name || plugin.id) + "を無効状態で追加しました。");
      await refresh();
    } catch (error) {
      setText(elements.importStatus, error.message);
    } finally {
      elements.zipInput.value = "";
      setText(elements.zipFileName, "ファイルが選択されていません");
    }
  }

  elements.skillButton.addEventListener("click", () => void installAuthoringSkill());
  elements.zipLabel?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    elements.zipInput?.click();
  });
  elements.zipInput?.addEventListener("change", () => void importPlugin());
  elements.dialogClose?.addEventListener("click", closeFeaturePanel);
  elements.dialog.addEventListener("close", () => {
    if (activePanelId) closeFeaturePanel();
  });
  elements.dialog.addEventListener("cancel", () => {
    activePanelId = null;
    elements.frame.src = "about:blank";
  });
  elements.dialog.addEventListener("click", (event) => {
    if (event.target === elements.dialog) closeFeaturePanel();
  });
  window.addEventListener("message", (event) => void handlePanelMessage(event));
  window.SparklePluginUI = Object.assign(window.SparklePluginUI || {}, {
    refresh,
    refreshAuthoringSkillStatus,
  });
  void refresh();
})();
