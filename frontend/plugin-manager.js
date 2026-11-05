(() => {
  "use strict";

  const apiRoot = "/plugins";
  const REQUIRED_SKILL_AGENTS = ["OpenCode", "Codex", "Claude Code"];
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
    categoryButtons: Array.from(document.querySelectorAll("[data-settings-category-button]")),
    categoryPanels: Array.from(document.querySelectorAll("[data-settings-category-panel]")),
    generalPanel: document.getElementById("generalSettingsPanel"),
    pluginThemeSelect: document.getElementById("pluginThemeSelect"),
  };
  if (!elements.list || !elements.skillButton) return;

  let plugins = [];

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

  function selectCategory(category) {
    const selectedButton = elements.categoryButtons.find(
      (button) => button.dataset.settingsCategoryButton === category,
    );
    if (!selectedButton) return;

    for (const button of elements.categoryButtons) {
      const selected = button === selectedButton;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    }
    if (elements.generalPanel) elements.generalPanel.hidden = category === "plugins";
    for (const panel of elements.categoryPanels) {
      const categoryMismatch = panel.dataset.settingsCategoryPanel !== category;
      const legacyFeatureDisabled = panel.dataset.legacyFeatureEnabled === "false";
      panel.hidden = categoryMismatch || legacyFeatureDisabled;
    }
    document.querySelector(".settings-main")?.scrollTo({ top: 0, behavior: "auto" });
  }

  function populateThemeSelect(activeTheme, appearanceTheme) {
    const select = elements.pluginThemeSelect;
    if (!select) return;

    const options = [
      new Option("Catppuccin - Macchiato", "catppuccin"),
      new Option("カスタムテーマ", "custom"),
    ];
    const enabledThemes = plugins.filter((plugin) => plugin.type === "theme" && plugin.enabled);
    for (const plugin of enabledThemes) {
      options.push(new Option(plugin.name || plugin.id, `plugin:${plugin.id}`));
    }
    select.replaceChildren(...options);

    const activeId = typeof activeTheme?.id === "string" && enabledThemes.some((plugin) => plugin.id === activeTheme.id)
      ? `plugin:${activeTheme.id}`
      : appearanceTheme === "custom" ? "custom" : "catppuccin";
    select.value = options.some((option) => option.value === activeId) ? activeId : "catppuccin";
  }

  async function refreshThemeSettings() {
    if (!elements.pluginThemeSelect) return;
    try {
      if (!window.SparkleAppearanceTheme && document.readyState === "loading") {
        await new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, { once: true }));
      }
      await window.SparkleAppearanceTheme?.ready;
      const body = await request("/active-theme", { cache: "no-store" });
      if (body.theme) await window.SparkleAppearanceTheme?.selectTheme?.("catppuccin");
      populateThemeSelect(body.theme || null, window.SparkleAppearanceTheme?.getTheme?.());
      window.SparklePluginTheme?.setPluginTheme(body.theme || null);
    } catch {
      elements.pluginThemeSelect.value = "catppuccin";
    }
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

  const permissionLabels = {
    storage: "プラグイン専用ストレージ",
    notifications: "Sparkle内通知",
    "ui.customize": "SparkleのUI変更",
    "clips.read": "クリップの読み取り",
    "clips.write": "クリップの作成・編集",
    "clips.delete": "クリップの削除",
    "projects.read": "プロジェクトの読み取り",
    "projects.write": "プロジェクトの作成・編集",
    "projects.delete": "プロジェクトの削除",
    "notes.read": "メモの読み取り",
    "notes.write": "メモの作成・編集",
    "notes.delete": "メモの削除",
    "tasks.read": "タスクの読み取り",
    "tasks.write": "タスクの作成・編集",
    "tasks.delete": "タスクの削除",
    "ai.request": "設定済みAIの利用",
    "network.request": "外部ネットワークアクセス",
    "auth.oauth": "外部アカウント認証",
  };

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
    const granted = Array.isArray(plugin.granted_permissions) ? plugin.granted_permissions : [];
    card.append(node(
      "p",
      "plugin-card-permissions",
      "許可中の権限: " + (granted.length ? granted.map((permission) => permissionLabels[permission] || permission).join("、") : "なし"),
    ));
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
    actions.append(makeButton(
      "権限を削除",
      () => void revokePluginPermissions(plugin),
      granted.length === 0,
    ));
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
      await refreshThemeSettings();
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
      window.SparklePluginTheme?.setPluginTheme(body.theme || null);
    } catch {
      window.SparklePluginTheme?.syncPluginTheme();
    }
  }

  async function togglePlugin(plugin, input) {
    const enabled = input ? input.checked : !plugin.enabled;
    if (input) input.disabled = true;
    try {
      if (
        enabled &&
        plugin.permissions?.includes("ui.customize") &&
        !plugin.granted_permissions?.includes("ui.customize")
      ) {
        await window.SparklePluginUI?.requestPermission?.(plugin.id, "ui.customize", plugin);
      }
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

  async function revokePluginPermissions(plugin) {
    try {
      const result = await request("/" + encodeURIComponent(plugin.id) + "/permissions", { method: "DELETE" });
      window.SparklePluginUI?.close?.(plugin.id);
      await syncTheme();
      setText(elements.importStatus, (plugin.name || plugin.id) + "の権限をすべて削除しました。必要になった権限は再度許可できます。");
      await refresh();
      return result;
    } catch (error) {
      setText(elements.importStatus, error.message);
    }
  }

  async function activateTheme(selection) {
    try {
      const isPluginTheme = selection.startsWith("plugin:");
      const pluginId = isPluginTheme ? selection.slice("plugin:".length) : null;
      if (isPluginTheme && !plugins.some((plugin) => plugin.id === pluginId && plugin.enabled && plugin.type === "theme")) {
        throw new Error("有効なテーマプラグインを選択してください。");
      }
      const body = await request("/active-theme", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plugin_id: pluginId }),
      });
      await window.SparkleAppearanceTheme?.selectTheme?.(
        isPluginTheme ? "catppuccin" : selection === "custom" ? "custom" : "catppuccin",
      );
      window.SparklePluginTheme?.setPluginTheme(body.theme || null);
      await refresh();
    } catch (error) {
      await refreshThemeSettings();
      setText(elements.importStatus, error.message);
    }
  }

  async function deletePlugin(plugin) {
    const removeData = window.confirm(
      "「" + (plugin.name || plugin.id) + "」を削除しますか？\n\nOKを選ぶとプラグイン本体・権限・専用データを削除します。プラグインがSparkleのクリップやプロジェクトに加えた変更はそのまま残ります。",
    );
    if (!removeData) return;
    try {
      await request("/" + encodeURIComponent(plugin.id) + "?delete_data=true", {
        method: "DELETE",
      });
      window.SparklePluginUI?.close?.(plugin.id);
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
    window.SparklePluginUI?.open?.(plugin.id);
  }

  function statusLabel(status) {
    return {
      missing: "未導入",
      outdated: "更新が必要",
      unknown: "未確認",
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
      const statuses = new Map(
        (Array.isArray(result.results) ? result.results : [])
          .filter((entry) => entry && typeof entry.agent === "string")
          .map((entry) => [entry.agent, entry.status || "unknown"]),
      );
      const allInstalled = REQUIRED_SKILL_AGENTS.every(
        (agent) => statuses.get(agent) === "installed",
      );
      const hasOutdated = REQUIRED_SKILL_AGENTS.some(
        (agent) => statuses.get(agent) === "outdated",
      );
      const hasMissing = REQUIRED_SKILL_AGENTS.some(
        (agent) => statuses.get(agent) === "missing",
      );
      elements.skillButton.textContent = hasOutdated
        ? hasMissing
          ? "作成スキルを更新して未導入のAIにも導入"
          : "作成スキルを更新"
        : hasMissing
          ? "作成スキルをAIへ導入"
          : "作成スキルを3つのAIへ導入";
      elements.skillCard.hidden = allInstalled;
      elements.skillAgents?.replaceChildren(
        ...REQUIRED_SKILL_AGENTS.map((agent) =>
          node("li", "", `${agent}: ${statusLabel(statuses.get(agent) || "missing")}`),
        ),
      );
      setText(elements.skillStatus, "");
    } catch {
      // Older Sparkle builds do not expose the status endpoint. Keep the
      // installation control visible so the user can still install the skill.
      elements.skillCard.hidden = false;
      elements.skillButton.textContent = "作成スキルを3つのAIへ導入";
      elements.skillAgents?.replaceChildren();
      setText(elements.skillStatus, "各AIの導入状況を確認できません。導入ボタンは表示しています。");
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

  for (const button of elements.categoryButtons) {
    button.addEventListener("click", () => selectCategory(button.dataset.settingsCategoryButton));
  }
  selectCategory("general");
  elements.pluginThemeSelect?.addEventListener("change", () => {
    void activateTheme(elements.pluginThemeSelect.value || "catppuccin");
  });
  document.querySelectorAll("[data-open-settings-category]").forEach((button) => {
    button.addEventListener("click", () => selectCategory(button.dataset.openSettingsCategory));
  });
  elements.skillButton.addEventListener("click", () => void installAuthoringSkill());
  elements.zipLabel?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    elements.zipInput?.click();
  });
  elements.zipInput?.addEventListener("change", () => void importPlugin());
  window.SparklePluginUI = Object.assign(window.SparklePluginUI || {}, {
    refresh,
    refreshAuthoringSkillStatus,
  });
  void refreshAuthoringSkillStatus();
  void refresh();
})();
