(() => {
  "use strict";

  const apiRoot = "/plugins";
  const SIDEBAR_CACHE_KEY = "sparkle.plugin-ui.sidebar-items.v1";
  const PENDING_PAGE_CONTEXT_KEY = "sparkle.plugin-ui.pending-page-context.v1";
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
  const permissionText = {
    storage: {
      title: "プラグイン専用ストレージ",
      detail: "このプラグインが自分専用の設定や保存データを読み書きします。Sparkleのクリップやプロジェクトにはアクセスしません。",
    },
    notifications: {
      title: "Sparkle内通知",
      detail: "このプラグインがSparkle画面内に通知を表示できます。",
    },
    "ui.customize": {
      title: "SparkleのUI変更",
      detail: "このプラグインが申告した範囲で、UI項目を追加・非表示・並び替え・スタイル変更できます。アプリのデータや機能は変更しません。",
    },
    "clips.read": {
      title: "クリップの読み取り",
      detail: "クリップのURL、タイトル、コメント、カテゴリ、タグ、プロジェクトとの関連を読み取れます。保存済みファイルの内容やローカルパスは取得できません。",
    },
    "clips.write": {
      title: "クリップの作成・編集",
      detail: "Webクリップを作成し、タイトル、コメント、カテゴリ、タグなどを編集できます。必要な場合はSparkleが公開URLからメタデータを取得します。変更はプラグイン削除後も残ります。",
    },
    "clips.delete": {
      title: "クリップの削除",
      detail: "Sparkleからクリップを削除できます。コピー保存されたローカルファイルも削除される場合があります。削除はプラグインを消しても元に戻りません。",
    },
    "projects.read": {
      title: "プロジェクトの読み取り",
      detail: "プロジェクト名、説明、完了状態を読み取れます。クリップの内容を読むには、別途クリップの読み取り許可が必要です。",
    },
    "projects.write": {
      title: "プロジェクトの作成・編集",
      detail: "プロジェクトの作成と名前・説明の変更ができます。完了状態の変更は含みません。変更はプラグイン削除後も残ります。",
    },
    "projects.delete": {
      title: "プロジェクトの削除",
      detail: "プロジェクトを削除して関連付けとそのプロジェクトのAI履歴を解除できます。クリップやタスクなどのレコード自体は削除しません。削除はプラグインを消しても元に戻りません。",
    },
    "notes.read": {
      title: "メモの読み取り",
      detail: "メモのタイトル、本文、完了状態、作成・更新日時と関連付けIDを読み取れます。リンク先のクリップ情報はクリップの読み取り権限が別途必要です。",
    },
    "notes.write": {
      title: "メモの作成・編集",
      detail: "メモの作成とタイトル・本文の編集ができます。プロジェクトやクリップとの関連付けには、それぞれの書き込み権限も必要です。変更はプラグインを削除しても残ります。",
    },
    "notes.delete": {
      title: "メモの削除",
      detail: "Sparkleのメモを削除できます。削除はプラグインを削除しても元に戻りません。",
    },
    "tasks.read": {
      title: "タスクの読み取り",
      detail: "タスク名、完了状態、期限、優先度と関連付けIDを読み取れます。リンク先のクリップ情報はクリップの読み取り権限が別途必要です。",
    },
    "tasks.write": {
      title: "タスクの作成・編集",
      detail: "タスクの作成と名前・完了状態・期限・優先度の編集ができます。プロジェクトやクリップとの関連付けには、それぞれの書き込み権限も必要です。",
    },
    "tasks.delete": {
      title: "タスクの削除",
      detail: "Sparkleのタスクを削除できます。タスクの削除で関連するメモとのリンクも解除されます。削除は元に戻りません。",
    },
    "ai.request": {
      title: "設定済みAIへの送信",
      detail: "プラグインが指定したプロンプトを、設定画面で選択中のAIプロバイダーへ送信し、回答を受け取れます。プロバイダーのAPIキーはプラグインに渡しません。プロンプトに含めたSparkleデータはそのAIプロバイダーへ送信されます。",
    },
    "network.request": {
      title: "外部ネットワークアクセス",
      detail: "プラグインから公開HTTPSサイトへリクエストを送信できます。localhostやプライベートネットワークには接続できません。プラグインが送信したデータは接続先へ渡ります。",
    },
    "auth.oauth": {
      title: "外部アカウント認証",
      detail: "プラグインはOAuthのブラウザー認証を開始し、接続先APIへ認証付きリクエストを送れます。PKCEとコールバック検証はSparkleが行い、資格情報はWindows資格情報マネージャーに保存します。アクセストークンはプラグインに渡しません。送信先と権限はプラグインが指定します。",
    },
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

  function currentPluginRouteId() {
    const match = window.location.pathname.match(/^\/Plugin\/([^/]+)\/?$/i);
    if (!match) return "";
    try {
      const pluginId = decodeURIComponent(match[1]);
      return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(pluginId) ? pluginId : "";
    } catch {
      return "";
    }
  }

  function pluginPageHref(pluginId) {
    const query = new URLSearchParams();
    if (new URLSearchParams(window.location.search).get("nativeBackdrop") === "1") {
      query.set("nativeBackdrop", "1");
    }
    const suffix = query.toString();
    return "/Plugin/" + encodeURIComponent(pluginId) + (suffix ? "?" + suffix : "");
  }

  function navigateBackFromPluginPage() {
    try {
      const referrer = document.referrer ? new URL(document.referrer) : null;
      if (referrer?.origin === window.location.origin && window.history.length > 1) {
        window.history.back();
        return;
      }
    } catch {
      // Fall through to the safe app entry point for direct or malformed referrers.
    }
    window.location.assign("/Home");
  }

  let plugins = [];
  let activePanelId = null;
  let activePanelContext = {};
  let messageTimes = [];
  let dialogParts = null;
  let pageParts = null;
  let activePanelDisplay = null;
  let panelReturnFocus = null;
  let suspendedPagePanel = null;
  let permissionDialogParts = null;
  let permissionPromptQueue = Promise.resolve();

  function make(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }

  function normalizeSidebarItems(items) {
    if (!Array.isArray(items)) return [];
    const seen = new Set();
    const normalized = [];
    for (const item of items) {
      if (
        !item ||
        typeof item.plugin_id !== "string" ||
        !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(item.plugin_id) ||
        item.plugin_id.length > 64 ||
        typeof item.label !== "string" ||
        !item.label.trim() ||
        item.label.length > 100 ||
        !allowedIcons.has(item.icon) ||
        seen.has(item.plugin_id)
      ) continue;
      seen.add(item.plugin_id);
      normalized.push({ plugin_id: item.plugin_id, label: item.label.trim(), icon: item.icon });
      if (normalized.length >= 128) break;
    }
    return normalized;
  }

  function restoreCachedSidebarItems() {
    try {
      const cached = JSON.parse(sessionStorage.getItem(SIDEBAR_CACHE_KEY) || "null");
      const items = normalizeSidebarItems(cached);
      if (items.length) renderSidebarItems(items, { cached: true });
    } catch {
      // The plugin list remains available when session storage is blocked.
    }
  }

  function cacheSidebarItems(items) {
    try {
      sessionStorage.setItem(SIDEBAR_CACHE_KEY, JSON.stringify(normalizeSidebarItems(items)));
    } catch {
      // Caching is an enhancement; it must not affect plugin UI rendering.
    }
  }

  function initializeHostUi() {
    if (!document.getElementById("pluginUiStylesheet")) {
      const stylesheet = make("link");
      stylesheet.id = "pluginUiStylesheet";
      stylesheet.rel = "stylesheet";
      stylesheet.href = "plugin-ui.css?v=plugin-ui-api-v6-standalone-route-v3-no-page-header";
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
    if (!response.ok) {
      const detail = body.detail;
      const message = detail && typeof detail === "object" ? detail.message : detail;
      const error = new Error(String(message || "プラグイン操作に失敗しました。"));
      if (detail && typeof detail === "object" && typeof detail.permission_required === "string") {
        error.permissionRequired = detail.permission_required;
      }
      throw error;
    }
    return body;
  }

  function ensurePermissionDialog() {
    if (!permissionDialogParts) {
      const dialog = make("dialog", "plugin-permission-dialog");
      dialog.setAttribute("aria-labelledby", "pluginPermissionTitle");
      const title = make("h2", "plugin-permission-title");
      title.id = "pluginPermissionTitle";
      const description = make("p", "plugin-permission-description");
      const persistence = make("p", "plugin-permission-persistence", "許可はこのPCに保存されます。各プラグインの「権限を削除」から、いつでもすべて取り消せます。");
      const status = make("p", "plugin-permission-status");
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      const actions = make("div", "plugin-permission-actions");
      const deny = make("button", "modal-btn ghost", "今回は許可しない");
      deny.type = "button";
      const allow = make("button", "modal-btn", "許可する");
      allow.type = "button";
      actions.append(deny, allow);
      dialog.append(title, description, persistence, status, actions);
      document.body.append(dialog);
      permissionDialogParts = { dialog, title, description, status, deny, allow };
    }
    return permissionDialogParts;
  }

  function requestPermission(pluginId, permission, pluginHint) {
    const run = async () => {
      await refresh();
      const plugin = plugins.find((entry) => entry.id === pluginId) || pluginHint;
      if (!plugin || !plugin.permissions?.includes(permission)) return false;
      if (plugin.granted_permissions?.includes(permission)) return true;
      const copy = permissionText[permission];
      if (!copy) return false;

      const parts = ensurePermissionDialog();
      parts.title.textContent = (plugin.name || plugin.id) + "が権限を要求しています";
      parts.description.textContent = copy.title + "：" + copy.detail;
      parts.status.textContent = "";
      parts.allow.disabled = false;
      parts.deny.disabled = false;

      return new Promise((resolve) => {
        let settled = false;
        const finish = (granted) => {
          if (settled) return;
          settled = true;
          parts.allow.removeEventListener("click", allowPermission);
          parts.deny.removeEventListener("click", denyPermission);
          parts.dialog.removeEventListener("cancel", cancelPermission);
          parts.dialog.removeEventListener("close", closePermission);
          if (parts.dialog.open) parts.dialog.close();
          resolve(granted);
        };
        const denyPermission = () => finish(false);
        const cancelPermission = (event) => {
          event.preventDefault();
          finish(false);
        };
        const closePermission = () => finish(false);
        const allowPermission = async () => {
          parts.allow.disabled = true;
          parts.deny.disabled = true;
          try {
            const result = await request("/" + encodeURIComponent(pluginId) + "/permissions/" + encodeURIComponent(permission), {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ granted: true }),
            });
            plugins = plugins.map((entry) => entry.id === pluginId
              ? { ...entry, granted_permissions: result.granted_permissions || [] }
              : entry);
            await refresh();
            finish(true);
          } catch (error) {
            parts.status.textContent = error.message;
            parts.allow.disabled = false;
            parts.deny.disabled = false;
          }
        };
        parts.allow.addEventListener("click", allowPermission);
        parts.deny.addEventListener("click", denyPermission);
        parts.dialog.addEventListener("cancel", cancelPermission);
        parts.dialog.addEventListener("close", closePermission);
        parts.dialog.showModal();
      });
    };
    const next = permissionPromptQueue.then(run, run);
    permissionPromptQueue = next.then(() => undefined, () => undefined);
    return next;
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
      close.addEventListener("click", () => closePanel());
      dialog.addEventListener("close", () => {
        if (dialog.open) return;
        frame.src = "about:blank";
        status.textContent = "";
        if (activePanelDisplay === "dialog") closePanel(activePanelId);
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

  function ensurePage() {
    if (!pageParts) {
      const page = document.getElementById("pluginFeaturePage");
      const frame = page?.querySelector(".plugin-feature-page-frame");
      const status = page?.querySelector(".plugin-feature-page-status");
      if (!page || !frame || !status) return null;
      pageParts = { page, frame, status };
    }
    return pageParts;
  }

  function activePanelParts() {
    if (activePanelDisplay === "page") return pageParts;
    if (activePanelDisplay === "dialog") return dialogParts;
    return null;
  }

  function postCurrentTheme(frame) {
    const theme = window.SparklePluginTheme?.getPluginTheme?.() || null;
    frame?.contentWindow?.postMessage({ type: "sparkle-plugin-theme", theme }, "*");
  }

  window.addEventListener("sparkle-plugin-theme-changed", () => {
    if (!activePanelId) return;
    postCurrentTheme(activePanelParts()?.frame);
  });

  function openPanel(pluginId, context = {}) {
    const plugin = plugins.find((entry) => entry.id === pluginId);
    if (!plugin || !plugin.enabled || !plugin.compatible || plugin.type !== "feature") return;
    const safeContext = {};
    if (context?.view === "list" || context?.view === "detail") safeContext.view = context.view;
    if (context?.project_id !== undefined) {
      try { safeContext.project_id = positiveId(context.project_id); } catch {}
    }
    if (plugin.panel_display === "page") {
      if (currentPluginRouteId() === plugin.id) {
        showRoutedPlugin(plugin, safeContext);
        return;
      }
      try {
        sessionStorage.setItem(PENDING_PAGE_CONTEXT_KEY, JSON.stringify({
          plugin_id: plugin.id,
          context: safeContext,
          saved_at: Date.now(),
        }));
      } catch {
        // Navigation still works if optional context storage is unavailable.
      }
      window.location.assign(pluginPageHref(plugin.id));
      return;
    }
    const returnFocus = document.activeElement;
    if (activePanelId && activePanelDisplay === "page" && currentPluginRouteId()) {
      suspendedPagePanel = { pluginId: activePanelId, context: activePanelContext };
      activePanelId = null;
      activePanelContext = {};
      activePanelDisplay = null;
      panelReturnFocus = null;
    } else if (activePanelId) {
      closePanel(undefined, false);
    }
    const display = "dialog";
    const parts = ensureDialog();
    if (!parts) return;
    activePanelId = plugin.id;
    activePanelContext = safeContext;
    activePanelDisplay = display;
    panelReturnFocus = returnFocus instanceof HTMLElement ? returnFocus : null;
    messageTimes = [];
    parts.title.textContent = plugin.name || plugin.id;
    parts.status.textContent = "";
    parts.frame.title = plugin.name || "プラグイン画面";
    parts.frame.onload = () => {
      if (activePanelId !== plugin.id) return;
      parts.frame.contentWindow?.postMessage({
        type: "sparkle-plugin-context",
        context: activePanelContext,
      }, "*");
      postCurrentTheme(parts.frame);
    };
    parts.frame.src = apiRoot + "/" + encodeURIComponent(plugin.id) + "/panel";
    if (!parts.dialog.open) {
      parts.dialog.showModal();
    }
  }

  function showRoutedPlugin(plugin, context = {}) {
    const parts = ensurePage();
    if (!parts) return false;
    if (activePanelId && activePanelId !== plugin.id) closePanel(undefined, false);
    activePanelId = plugin.id;
    activePanelContext = context;
    activePanelDisplay = "page";
    panelReturnFocus = null;
    messageTimes = [];
    parts.page.setAttribute("aria-label", (plugin.name || plugin.id) + " プラグインページ");
    parts.status.textContent = "";
    parts.frame.title = plugin.name || "プラグイン画面";
    parts.frame.setAttribute("sandbox", plugin.id === "ai-chat"
      ? "allow-scripts allow-popups allow-popups-to-escape-sandbox"
      : "allow-scripts");
    document.title = (plugin.name || plugin.id) + " — Sparkle";
    parts.frame.onload = () => {
      if (activePanelId !== plugin.id) return;
      parts.frame.contentWindow?.postMessage({
        type: "sparkle-plugin-context",
        context: activePanelContext,
      }, "*");
      postCurrentTheme(parts.frame);
    };
    const panelUrl = apiRoot + "/" + encodeURIComponent(plugin.id) + "/panel";
    if (parts.frame.getAttribute("src") !== panelUrl) {
      parts.frame.src = panelUrl;
    } else {
      parts.frame.contentWindow?.postMessage({
        type: "sparkle-plugin-context",
        context: activePanelContext,
      }, "*");
      postCurrentTheme(parts.frame);
    }
    return true;
  }

  function takePendingPageContext(pluginId) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(PENDING_PAGE_CONTEXT_KEY) || "null");
      sessionStorage.removeItem(PENDING_PAGE_CONTEXT_KEY);
      if (!saved || saved.plugin_id !== pluginId || Date.now() - Number(saved.saved_at) > 60_000) return {};
      const context = {};
      if (saved.context?.view === "list" || saved.context?.view === "detail") context.view = saved.context.view;
      if (saved.context?.project_id !== undefined) {
        try { context.project_id = positiveId(saved.context.project_id); } catch {}
      }
      return context;
    } catch {
      return {};
    }
  }

  function closePanel(pluginId, restoreFocus = true) {
    if (pluginId && activePanelId !== pluginId) return;
    const display = activePanelDisplay;
    const returnFocus = panelReturnFocus;
    activePanelId = null;
    activePanelContext = {};
    activePanelDisplay = null;
    panelReturnFocus = null;
    if (dialogParts) {
      dialogParts.frame.src = "about:blank";
      dialogParts.status.textContent = "";
      if (display === "dialog" && dialogParts.dialog.open) dialogParts.dialog.close();
    }
    if (display === "page" && pageParts) {
      pageParts.frame.src = "about:blank";
      pageParts.status.textContent = "";
      if (currentPluginRouteId()) {
        navigateBackFromPluginPage();
        return;
      }
    }
    if (display === "dialog" && suspendedPagePanel && currentPluginRouteId()) {
      const suspended = suspendedPagePanel;
      suspendedPagePanel = null;
      const plugin = plugins.find((entry) => entry.id === suspended.pluginId);
      if (plugin?.enabled && plugin.compatible && plugin.type === "feature") {
        showRoutedPlugin(plugin, suspended.context);
      }
    }
    if (restoreFocus && returnFocus?.isConnected) {
      returnFocus.focus({ preventScroll: true });
    }
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

  function renderSidebarItems(items, { cached = false } = {}) {
    const sidebar = document.querySelector(".sidebar");
    if (!sidebar) return;
    sidebar.querySelectorAll(".plugin-sidebar-item").forEach((item) => item.remove());
    const spacer = sidebar.querySelector(".side-spacer");
    if (!spacer) return;
    const validItems = normalizeSidebarItems(items);
    const fragment = document.createDocumentFragment();
    for (const item of validItems) {
      const plugin = plugins.find((entry) => entry.id === item.plugin_id);
      if (!cached && (!plugin || !plugin.enabled || !plugin.compatible || plugin.type !== "feature")) continue;
      const isPage = plugin?.panel_display === "page";
      const button = make(isPage ? "a" : "button", "side-btn plugin-sidebar-item");
      if (isPage) button.href = pluginPageHref(item.plugin_id);
      else button.type = "button";
      button.dataset.pluginSidebar = item.plugin_id;
      button.dataset.sidebarOrderId = "plugin:" + item.plugin_id;
      button.title = item.label;
      button.setAttribute("aria-label", item.label);
      if (currentPluginRouteId() === item.plugin_id) {
        button.classList.add("active");
        button.setAttribute("aria-current", "page");
      }
      button.append(makeIcon(item.icon), make("span", "side-label", item.label));
      if (!isPage) button.addEventListener("click", () => openPanel(item.plugin_id));
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
        button.addEventListener("click", () => {
          const detailView = slot.closest("#detailView");
          const context = { view: detailView && !detailView.hidden ? "detail" : "list" };
          if (context.view === "detail" && detailView.dataset.projectId) {
            context.project_id = detailView.dataset.projectId;
          }
          openPanel(item.plugin_id, context);
        });
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
    cacheSidebarItems(state.sidebar_items);
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

  function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function positiveId(value) {
    const id = Number(value);
    if (!Number.isSafeInteger(id) || id < 1) throw new Error("IDには正の整数を指定してください。");
    return id;
  }

  async function executePanelRequest(plugin, parts, data) {
    if (data.method === "notify") {
      if (!plugin.permissions?.includes("notifications")) throw new Error("このプラグインは通知権限を要求していません。");
      if (!plugin.granted_permissions?.includes("notifications")) {
        const error = new Error("Sparkle内通知の許可が必要です。");
        error.permissionRequired = "notifications";
        throw error;
      }
      if (typeof data.message !== "string" || data.message.length > 500) throw new Error("通知メッセージが長すぎます。");
      parts.status.textContent = data.message;
      return null;
    }
    if (data.method === "storage.get" || data.method === "storage.set") {
      if (!plugin.permissions?.includes("storage")) throw new Error("このプラグインはストレージ権限を要求していません。");
      if (typeof data.key !== "string") throw new Error("ストレージキーが不正です。");
      const path = "/" + encodeURIComponent(plugin.id) + "/storage/" + encodeURIComponent(data.key);
      if (data.method === "storage.get") {
        const result = await request(path, { cache: "no-store" });
        return result.value;
      }
      const result = await request(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: data.value }),
      });
      return result.value;
    }
    if (data.method === "session.get" || data.method === "session.set" || data.method === "session.remove") {
      if (!plugin.permissions?.includes("storage")) throw new Error("このプラグインはストレージ権限を要求していません。");
      if (typeof data.key !== "string" || data.key.length < 1 || data.key.length > 128) throw new Error("セッションストレージキーが不正です。");
      const key = `sparkle.plugin-session.${encodeURIComponent(plugin.id)}.${data.key}`;
      if (data.method === "session.get") {
        const raw = window.sessionStorage.getItem(key);
        if (raw === null) return null;
        try { return JSON.parse(raw); } catch { return null; }
      }
      if (data.method === "session.remove") {
        window.sessionStorage.removeItem(key);
        return null;
      }
      let serialized;
      try { serialized = JSON.stringify(data.value); } catch { throw new Error("セッションデータを保存できませんでした。"); }
      if (typeof serialized !== "string" || serialized.length > 1_000_000) throw new Error("セッションデータが大きすぎます。");
      window.sessionStorage.setItem(key, serialized);
      return data.value;
    }

    const base = "/" + encodeURIComponent(plugin.id) + "/data/";
    const payload = objectValue(data.payload);
    const methods = {
      "clips.list": () => {
        const query = new URLSearchParams();
        const filters = objectValue(data.filters) || {};
        for (const key of ["category", "tag", "url"]) {
          if (typeof filters[key] === "string") query.set(key, filters[key]);
        }
        for (const key of ["project_id", "exclude_project"]) {
          if (filters[key] !== undefined && filters[key] !== null) query.set(key, String(positiveId(filters[key])));
        }
        const serialized = query.toString();
        return request(base + "clips" + (serialized ? "?" + serialized : ""), { cache: "no-store" });
      },
      "clips.get": () => request(base + "clips/" + positiveId(data.id), { cache: "no-store" }),
      "clips.create": () => request(base + "clips", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "clips.update": () => request(base + "clips/" + positiveId(data.id), {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "clips.delete": () => request(base + "clips/" + positiveId(data.id), { method: "DELETE" }),
      "projects.list": () => request(base + "projects", { cache: "no-store" }),
      "projects.get": () => request(base + "projects/" + positiveId(data.id), { cache: "no-store" }),
      "projects.create": () => request(base + "projects", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "projects.update": () => request(base + "projects/" + positiveId(data.id), {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "projects.delete": () => request(base + "projects/" + positiveId(data.id), { method: "DELETE" }),
      "notes.list": () => {
        const query = new URLSearchParams();
        const filters = objectValue(data.filters) || {};
        for (const key of ["project_id", "exclude_project"]) {
          if (filters[key] !== undefined && filters[key] !== null) query.set(key, String(positiveId(filters[key])));
        }
        const serialized = query.toString();
        return request(base + "notes" + (serialized ? "?" + serialized : ""), { cache: "no-store" });
      },
      "notes.get": () => request(base + "notes/" + positiveId(data.id), { cache: "no-store" }),
      "notes.create": () => request(base + "notes", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "notes.update": () => request(base + "notes/" + positiveId(data.id), {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "notes.delete": () => request(base + "notes/" + positiveId(data.id), { method: "DELETE" }),
      "tasks.list": () => {
        const query = new URLSearchParams();
        const filters = objectValue(data.filters) || {};
        if (typeof filters.done === "boolean") query.set("done", String(filters.done));
        for (const key of ["project_id", "exclude_project"]) {
          if (filters[key] !== undefined && filters[key] !== null) query.set(key, String(positiveId(filters[key])));
        }
        const serialized = query.toString();
        return request(base + "tasks" + (serialized ? "?" + serialized : ""), { cache: "no-store" });
      },
      "tasks.get": () => request(base + "tasks/" + positiveId(data.id), { cache: "no-store" }),
      "tasks.create": () => request(base + "tasks", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "tasks.update": () => request(base + "tasks/" + positiveId(data.id), {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
      }),
      "tasks.delete": () => request(base + "tasks/" + positiveId(data.id), { method: "DELETE" }),
      "ai.generate": () => request("/" + encodeURIComponent(plugin.id) + "/ai/generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_prompt: data.system_prompt, prompt: data.prompt }),
      }),
      "network.request": () => request("/" + encodeURIComponent(plugin.id) + "/network/request", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: data.url,
          method: data.requestMethod || "GET",
          headers: objectValue(data.headers) || {},
          body: data.body,
        }),
      }),
      "oauth.connect": () => request("/" + encodeURIComponent(plugin.id) + "/oauth/connect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(objectValue(data.connection) || {}),
      }),
      "oauth.status": () => request("/" + encodeURIComponent(plugin.id) + "/oauth/" + encodeURIComponent(String(data.connection_id || "")), {
        cache: "no-store",
      }),
      "oauth.disconnect": () => request("/" + encodeURIComponent(plugin.id) + "/oauth/" + encodeURIComponent(String(data.connection_id || "")), {
        method: "DELETE",
      }),
      "oauth.request": () => request("/" + encodeURIComponent(plugin.id) + "/oauth/" + encodeURIComponent(String(data.connection_id || "")) + "/request", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: data.url,
          method: data.requestMethod || "GET",
          headers: objectValue(data.headers) || {},
          body: data.body,
        }),
      }),
    };
    if (typeof data.method !== "string" || !Object.hasOwn(methods, data.method)) {
      throw new Error("未対応のプラグインAPIです。");
    }
    const execute = methods[data.method];
    return execute();
  }

  async function handlePanelMessage(event) {
    const parts = activePanelParts();
    if (!parts || !activePanelId || event.source !== parts.frame.contentWindow) return;
    const data = event.data;
    if (data?.type === "sparkle-plugin-open-link") {
      if (activePanelId !== "ai-chat" || activePanelDisplay !== "page" || !allowPanelMessage()) return;
      if (typeof data.url !== "string" || data.url.length > 2048) return;
      try {
        const url = new URL(data.url);
        if (url.protocol !== "http:" && url.protocol !== "https:") return;
        window.open(url.href, "_blank", "noopener,noreferrer");
      } catch {
        // Ignore malformed or non-web URLs sent by a plugin frame.
      }
      return;
    }
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
      let value;
      try {
        value = await executePanelRequest(plugin, parts, data);
      } catch (error) {
        if (!error.permissionRequired) throw error;
        const granted = await requestPermission(plugin.id, error.permissionRequired, plugin);
        if (!granted) throw new Error("権限は許可されませんでした。");
        const refreshedPlugin = plugins.find((entry) => entry.id === plugin.id) || plugin;
        value = await executePanelRequest(refreshedPlugin, parts, data);
      }
      respond(parts.frame, data.requestId, true, value);
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
      const routeId = currentPluginRouteId();
      if (routeId) {
        const active = plugins.find((plugin) => plugin.id === routeId);
        if (!active?.enabled || !active.compatible || active.type !== "feature" || active.panel_display !== "page") {
          const parts = ensurePage();
          if (parts) {
            parts.page.setAttribute("aria-label", (active?.name || "プラグイン") + " プラグインページ");
            parts.status.textContent = "このプラグインは利用できないか、無効になっています。";
            if (activePanelId === routeId) {
              activePanelId = null;
              activePanelContext = {};
              activePanelDisplay = null;
              parts.frame.src = "about:blank";
            }
          }
        } else if (
          activePanelDisplay === "dialog" && suspendedPagePanel?.pluginId === active.id
        ) {
          // Keep a dialog opened from this route active while refreshing plugin state.
        } else if (activePanelId !== active.id || activePanelDisplay !== "page") {
          showRoutedPlugin(active, takePendingPageContext(active.id));
        } else {
          const parts = ensurePage();
          if (parts) parts.page.setAttribute("aria-label", (active.name || active.id) + " プラグインページ");
        }
      }
      if (activePanelId) {
        const active = plugins.find((plugin) => plugin.id === activePanelId);
        if ((!active?.enabled || !active.compatible) && !currentPluginRouteId()) closePanel();
      }
      return true;
    } catch {
      const parts = currentPluginRouteId() ? ensurePage() : null;
      if (parts) parts.status.textContent = "プラグイン情報を読み込めませんでした。接続を確認して再読み込みしてください。";
      return false;
    }
  }

  window.addEventListener("message", (event) => void handlePanelMessage(event));
  initializeHostUi();
  restoreCachedSidebarItems();
  window.SparklePluginUI = Object.assign(window.SparklePluginUI || {}, {
    refreshUI: refresh,
    open: openPanel,
    close: closePanel,
    requestPermission,
  });
  void refresh();
})();
