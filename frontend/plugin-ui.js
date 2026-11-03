(() => {
  "use strict";

  const apiRoot = "/plugins";
  const allowedHideTargets = new Set([
    "sidebar.home", "sidebar.memo", "sidebar.projects", "sidebar.profile",
    "home.search", "home.sort", "home.categories", "home.clips",
    "notes.status-tabs", "notes.task-list", "notes.memo-list", "notes.new-note",
    "projects.list", "projects.create", "profile.details", "profile.picks",
    "settings.category.general", "settings.category.theme",
    "settings.category.connections", "settings.category.ai",
    "settings.category.advanced",
  ]);
  const allowedIcons = new Set([
    "home", "tasks", "projects", "puzzle", "game", "star",
    "sparkles", "book", "calendar", "calculator", "settings",
  ]);
  const styleProperties = {
    accent: "--accent",
    background: "background-color",
    color: "color",
    border: "border-color",
    margin: "margin",
    padding: "padding",
    width: "width",
    height: "height",
    radius: "border-radius",
    fontSize: "font-size",
    opacity: "opacity",
  };
  const styleValuePatterns = {
    color: /^(?:#[\da-f]{6}(?:[\da-f]{2})?|rgba?\(\s*(?:\d{1,3}%?\s*,\s*){2}\d{1,3}%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\))$/i,
    length: /^(?:0|\d+(?:\.\d+)?(?:px|rem|em|%|vw|vh))$/i,
    number: /^(?:0|1|0?\.\d+)$/,
  };
  const stylePropertyTypes = {
    accent: "color", background: "color", color: "color", border: "color",
    margin: "length", padding: "length", width: "length", height: "length",
    radius: "length", fontSize: "length", opacity: "number",
  };
  const hostUiSelectors = {
    "sidebar.home": ".sidebar a[data-nav='home']",
    "sidebar.memo": ".sidebar a[data-nav='memo']",
    "sidebar.projects": ".sidebar a[data-nav='projects']",
    "sidebar.profile": ".sidebar-tools a[data-nav='profile']",
    "home.search": "#searchWrap",
    "home.sort": "#sortSelect",
    "home.categories": "#categories",
    "home.clips": "#gridWrap, .section-heading",
    "notes.status-tabs": "#statusTabs",
    "notes.task-list": ".task-panel",
    "notes.memo-list": ".memo-col",
    "notes.new-note": "#newNote",
    "projects.list": "#listView",
    "projects.create": "#newProjectBtn",
    "profile.details": ".profile-head, .profile-stats-row",
    "profile.picks": ".profile-picks-head, #profilePicks, #profilePicksEmpty",
    "settings.category.general": "[data-settings-category-button='general'], [data-settings-category-panel='general']",
    "settings.category.theme": "[data-settings-category-button='theme'], [data-settings-category-panel='theme']",
    "settings.category.connections": "[data-settings-category-button='connections'], [data-settings-category-panel='connections']",
    "settings.category.ai": "[data-settings-category-button='ai'], [data-settings-category-panel='ai']",
    "settings.category.advanced": "[data-settings-category-button='advanced'], [data-settings-category-panel='advanced']",
  };
  const iconPaths = {
    home: "M3 10.5 12 3l9 7.5M5.5 9v11h13V9M9 20v-6h6v6",
    tasks: "M4 5h2m4 0h10M4 12h2m4 0h10M4 19h2m4 0h10",
    projects: "M4 5h16M4 12h16M4 19h16",
    puzzle: "M9 4a2 2 0 1 1 4 0v2h3a2 2 0 0 1 2 2v3h2a2 2 0 1 1 0 4h-2v3a2 2 0 0 1-2 2h-3v-2a2 2 0 1 0-4 0v2H6a2 2 0 0 1-2-2v-3H2a2 2 0 1 1 0-4h2V8a2 2 0 0 1 2-2h3V4Z",
    game: "M7 8h10a4 4 0 0 1 3.8 2.8l1 3.3a2.2 2.2 0 0 1-3.5 2.3L16 14H8l-2.3 2.4a2.2 2.2 0 0 1-3.5-2.3l1-3.3A4 4 0 0 1 7 8Zm1 2v4m-2-2h4m5-1h.01M17 13h.01",
    star: "m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z",
    sparkles: "m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm7 12 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z",
    book: "M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22V4.5Zm0 0V22m4-15h8m-8 4h8",
    calendar: "M4 5h16v16H4zM8 3v4m8-4v4M4 10h16",
    calculator: "M5 3h14v18H5zM8 6h8v4H8zm0 8h2m4 0h2m-8 4h2m4 0h2",
    settings: "M4 6h16M4 12h16M4 18h16M9 6a2 2 0 1 0 0 .01M15 12a2 2 0 1 0 0 .01M7 18a2 2 0 1 0 0 .01",
  };

  let plugins = [];
  let activePanelId = null;
  let messageTimes = [];
  let dialogParts = null;

  function make(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }

  function initializeHostUi() {
    if (!document.getElementById("pluginUiStylesheet")) {
      const stylesheet = make("link");
      stylesheet.id = "pluginUiStylesheet";
      stylesheet.rel = "stylesheet";
      stylesheet.href = "plugin-ui.css?v=plugin-ui-api-v2";
      document.head.append(stylesheet);
    }
    for (const [target, selector] of Object.entries(hostUiSelectors)) {
      document.querySelectorAll(selector).forEach((element) => {
        element.dataset.sparkleUiId = target;
      });
    }
  }

  async function request(path, options) {
    const response = await fetch(apiRoot + path, options);
    let body = {};
    try { body = await response.json(); } catch {}
    if (!response.ok) throw new Error(String(body.detail || "プラグイン操作に失敗しました。"));
    return body;
  }

  function ensureDialog() {
    let dialog = document.getElementById("pluginSidebarDialog");
    if (!dialog) {
      dialog = make("dialog", "plugin-panel-dialog plugin-sidebar-dialog");
      dialog.id = "pluginSidebarDialog";
      dialog.setAttribute("aria-labelledby", "pluginSidebarDialogTitle");
      const header = make("div", "plugin-panel-dialog-header");
      const title = make("h2", "modal-title");
      title.id = "pluginSidebarDialogTitle";
      const close = make("button", "modal-btn ghost", "閉じる");
      close.type = "button";
      close.setAttribute("aria-label", "プラグイン画面を閉じる");
      const frame = make("iframe", "plugin-panel-frame");
      frame.title = "プラグイン画面";
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("referrerpolicy", "no-referrer");
      const status = make("p", "plugin-panel-status");
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      header.append(title, close);
      dialog.append(header, frame, status);
      document.body.append(dialog);
      close.addEventListener("click", closePanel);
      dialog.addEventListener("close", () => {
        activePanelId = null;
        frame.src = "about:blank";
        status.textContent = "";
      });
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closePanel();
      });
    }
    dialogParts = {
      dialog,
      title: document.getElementById("pluginSidebarDialogTitle"),
      frame: dialog.querySelector("iframe"),
      status: dialog.querySelector(".plugin-panel-status"),
    };
    return dialogParts;
  }

  function openPanel(pluginId) {
    const plugin = plugins.find((entry) => entry.id === pluginId);
    if (!plugin || !plugin.enabled || !plugin.compatible || plugin.type !== "feature") return;
    const parts = ensureDialog();
    activePanelId = plugin.id;
    messageTimes = [];
    parts.title.textContent = plugin.name || plugin.id;
    parts.status.textContent = "";
    parts.frame.title = plugin.name || "プラグイン画面";
    parts.frame.src = apiRoot + "/" + encodeURIComponent(plugin.id) + "/panel";
    if (!parts.dialog.open) parts.dialog.showModal();
  }

  function closePanel() {
    if (!dialogParts) return;
    activePanelId = null;
    dialogParts.frame.src = "about:blank";
    dialogParts.status.textContent = "";
    if (dialogParts.dialog.open) dialogParts.dialog.close();
  }

  function makeIcon(iconName) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("icon", "icon-nav", "plugin-sidebar-icon");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", iconPaths[iconName] || iconPaths.puzzle);
    svg.append(path);
    return svg;
  }

  function renderSidebarItems(items) {
    const sidebar = document.querySelector(".sidebar");
    if (!sidebar) return;
    sidebar.querySelectorAll(".plugin-sidebar-item").forEach((item) => item.remove());
    const spacer = sidebar.querySelector(".side-spacer");
    if (!spacer) return;
    const validItems = (Array.isArray(items) ? items : []).filter((item) =>
      item && typeof item.plugin_id === "string" && typeof item.label === "string" && allowedIcons.has(item.icon),
    );
    const fragment = document.createDocumentFragment();
    for (const item of validItems) {
      const plugin = plugins.find((entry) => entry.id === item.plugin_id);
      if (!plugin || !plugin.enabled || !plugin.compatible || plugin.type !== "feature") continue;
      const button = make("button", "side-btn plugin-sidebar-item");
      button.type = "button";
      button.dataset.pluginSidebar = item.plugin_id;
      button.dataset.sidebarOrderId = "plugin:" + item.plugin_id;
      button.title = item.label;
      button.setAttribute("aria-label", item.label);
      button.append(makeIcon(item.icon), make("span", "side-label", item.label));
      button.addEventListener("click", () => openPanel(item.plugin_id));
      fragment.append(button);
    }
    const pinSection = sidebar.querySelector(".pins-section");
    sidebar.insertBefore(fragment, pinSection || spacer);
  }

  function renderProjectActions(items) {
    const slots = Array.from(document.querySelectorAll(".plugin-project-action-slot"));
    if (!slots.length) return;
    const validItems = (Array.isArray(items) ? items : []).filter((item) =>
      item && typeof item.plugin_id === "string" && typeof item.label === "string" && allowedIcons.has(item.icon),
    ).filter((item) => {
      const plugin = plugins.find((entry) => entry.id === item.plugin_id);
      return plugin?.enabled && plugin.compatible && plugin.type === "feature";
    });
    for (const slot of slots) {
      slot.replaceChildren();
      slot.hidden = validItems.length === 0;
      for (const item of validItems) {
        const button = make("button", "modal-btn ghost plugin-project-action");
        button.type = "button";
        button.title = item.label;
        button.setAttribute("aria-label", item.label);
        button.append(makeIcon(item.icon), make("span", "plugin-project-action-label", item.label));
        button.addEventListener("click", () => openPanel(item.plugin_id));
        slot.append(button);
      }
    }
  }

  function orderSidebar(order) {
    const sidebar = document.querySelector(".sidebar");
    if (!sidebar) return;
    const candidates = Array.from(sidebar.children).filter((element) =>
      (element.matches("a.side-btn[data-nav='home'], a.side-btn[data-nav='memo'], a.side-btn[data-nav='projects']")) ||
      element.matches(".plugin-sidebar-item"),
    );
    const getId = (element) => element.dataset.sidebarOrderId || element.dataset.nav;
    const requested = Array.isArray(order) ? order : [];
    const defaultOrder = [
      "home", "memo", "projects",
      ...candidates.filter((element) => element.matches(".plugin-sidebar-item")).map(getId),
    ];
    const fullOrder = [...requested, ...defaultOrder.filter((id) => !requested.includes(id))];
    const rank = new Map(fullOrder.map((id, index) => [id, index]));
    const originalPosition = new Map(candidates.map((element, index) => [element, index]));
    candidates.sort((left, right) => {
      const leftId = getId(left);
      const rightId = getId(right);
      const leftRank = rank.has(leftId) ? rank.get(leftId) : fullOrder.length + originalPosition.get(left);
      const rightRank = rank.has(rightId) ? rank.get(rightId) : fullOrder.length + originalPosition.get(right);
      return leftRank - rightRank;
    });
    const fragment = document.createDocumentFragment();
    candidates.forEach((element) => fragment.append(element));
    const pinSection = sidebar.querySelector(".pins-section");
    const insertionPoint = pinSection || sidebar.querySelector(".side-spacer") || sidebar.querySelector(".sidebar-tools");
    if (insertionPoint) sidebar.insertBefore(fragment, insertionPoint);
  }

  function orderSettingsCategories(order) {
    const nav = document.querySelector(".settings-category-nav");
    if (!nav || !Array.isArray(order)) return;
    const buttons = Array.from(nav.querySelectorAll("[data-settings-category-button]"));
    const fullOrder = [...order, ...["general", "theme", "connections", "ai", "advanced", "plugins"].filter((id) => !order.includes(id))];
    const rank = new Map(fullOrder.map((id, index) => [id, index]));
    const originalPosition = new Map(buttons.map((button, index) => [button, index]));
    buttons.sort((left, right) => {
      const leftId = left.dataset.settingsCategoryButton;
      const rightId = right.dataset.settingsCategoryButton;
      const leftRank = rank.has(leftId) ? rank.get(leftId) : fullOrder.length + originalPosition.get(left);
      const rightRank = rank.has(rightId) ? rank.get(rightId) : fullOrder.length + originalPosition.get(right);
      return leftRank - rightRank;
    });
    buttons.forEach((button) => nav.append(button));
  }

  function safeStyle(target, styles) {
    if (!allowedHideTargets.has(target) || !styles || typeof styles !== "object") return null;
    const normalized = {};
    for (const [key, rawValue] of Object.entries(styles)) {
      const valueType = stylePropertyTypes[key];
      if (!valueType || typeof rawValue !== "string" || rawValue.length > 80) continue;
      if (!styleValuePatterns[valueType].test(rawValue.trim())) continue;
      normalized[styleProperties[key]] = rawValue.trim();
    }
    return Object.keys(normalized).length ? normalized : null;
  }

  function applyStyles(styles) {
    let element = document.getElementById("pluginUiContributionStyles");
    if (!element) {
      element = document.createElement("style");
      element.id = "pluginUiContributionStyles";
      document.head.append(element);
    }
    const rules = [];
    if (styles && typeof styles === "object") {
      for (const [target, values] of Object.entries(styles)) {
        const normalized = safeStyle(target, values);
        if (!normalized) continue;
        const declarations = Object.entries(normalized)
          .map(([property, value]) => `${property}:${value} !important`)
          .join(";");
        rules.push(`[data-sparkle-ui-id="${target}"]{${declarations}}`);
      }
    }
    element.textContent = rules.join("\n");
  }

  function applyHidden(targets) {
    document.querySelectorAll(".plugin-ui-hidden").forEach((element) => element.classList.remove("plugin-ui-hidden"));
    const hidden = new Set((Array.isArray(targets) ? targets : []).filter((target) => allowedHideTargets.has(target)));
    document.querySelectorAll("[data-sparkle-ui-id]").forEach((element) => {
      if (hidden.has(element.dataset.sparkleUiId)) element.classList.add("plugin-ui-hidden");
    });
    const selectedCategory = document.querySelector(".settings-category-nav [data-settings-category-button][aria-pressed='true']");
    if (selectedCategory?.classList.contains("plugin-ui-hidden")) {
      const fallback = document.querySelector(".settings-category-nav [data-settings-category-button='plugins']");
      fallback?.click();
    }
  }

  function applyContributions(state) {
    renderSidebarItems(state.sidebar_items);
    renderProjectActions(state.project_actions);
    applyHidden(state.hidden);
    applyStyles(state.styles);
    orderSidebar(state.order?.["sidebar.primary"]);
    orderSettingsCategories(state.order?.["settings.categories"]);
  }

  function allowPanelMessage() {
    const now = Date.now();
    messageTimes = messageTimes.filter((time) => now - time < 10000);
    if (messageTimes.length >= 50) return false;
    messageTimes.push(now);
    return true;
  }

  function respond(frame, requestId, ok, value, error) {
    frame.contentWindow?.postMessage({
      type: "sparkle-plugin-response", requestId, ok, value, error: error || undefined,
    }, "*");
  }

  async function handlePanelMessage(event) {
    const parts = dialogParts;
    if (!parts || !activePanelId || event.source !== parts.frame.contentWindow) return;
    const data = event.data;
    if (!data || data.type !== "sparkle-plugin-request" || typeof data.requestId !== "string" || data.requestId.length > 100) return;
    if (!allowPanelMessage()) {
      respond(parts.frame, data.requestId, false, null, "要求が多すぎます。");
      return;
    }
    const plugin = plugins.find((entry) => entry.id === activePanelId);
    if (!plugin?.enabled) {
      respond(parts.frame, data.requestId, false, null, "プラグインは無効です。");
      return;
    }
    try {
      if (data.method === "notify" && plugin.permissions?.includes("notifications")) {
        if (typeof data.message !== "string" || data.message.length > 500) throw new Error("通知メッセージが長すぎます。");
        parts.status.textContent = data.message;
        respond(parts.frame, data.requestId, true, null);
        return;
      }
      if (data.method === "storage.get" && plugin.permissions?.includes("storage") && typeof data.key === "string") {
        const value = await request("/" + encodeURIComponent(plugin.id) + "/storage/" + encodeURIComponent(data.key), { cache: "no-store" });
        respond(parts.frame, data.requestId, true, value.value);
        return;
      }
      if (data.method === "storage.set" && plugin.permissions?.includes("storage") && typeof data.key === "string") {
        const value = await request("/" + encodeURIComponent(plugin.id) + "/storage/" + encodeURIComponent(data.key), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: data.value }),
        });
        respond(parts.frame, data.requestId, true, value.value);
        return;
      }
      throw new Error("プラグインAPIの権限がありません。");
    } catch (error) {
      respond(parts.frame, data.requestId, false, null, error.message);
    }
  }

  async function refresh() {
    try {
      const [pluginBody, uiState] = await Promise.all([
        request("", { cache: "no-store" }),
        request("/ui", { cache: "no-store" }),
      ]);
      plugins = Array.isArray(pluginBody.plugins) ? pluginBody.plugins : [];
      applyContributions(uiState);
      if (activePanelId) {
        const active = plugins.find((plugin) => plugin.id === activePanelId);
        if (!active?.enabled || !active.compatible) closePanel();
      }
      return true;
    } catch {
      applyContributions({ hidden: [], order: {}, styles: {}, sidebar_items: [], project_actions: [] });
      return false;
    }
  }

  window.addEventListener("message", (event) => void handlePanelMessage(event));
  initializeHostUi();
  window.SparklePluginUI = Object.assign(window.SparklePluginUI || {}, {
    refreshUI: refresh,
    open: openPanel,
    close: closePanel,
  });
  void refresh();
})();
