(() => {
  // The native window disables WebView zoom as well.  This guard keeps the
  // same behavior in browser previews and prevents Ctrl/Cmd zoom gestures
  // from changing the workbench scale.
  document.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
  }, { capture: true, passive: false });

  document.addEventListener("keydown", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    if (["+", "-", "=", "_", "0"].includes(event.key)) event.preventDefault();
  }, true);

  // Chromium can offer previously saved form values even when an individual
  // dialog did not explicitly opt out.  Apply the opt-out to every form
  // control in the page, including controls added later by a dialog.
  const AUTOCOMPLETE_SELECTOR = "form, input, textarea, select";

  function disableBrowserAutocomplete(root) {
    if (root?.nodeType === Node.ELEMENT_NODE && root.matches(AUTOCOMPLETE_SELECTOR)) {
      root.setAttribute("autocomplete", "off");
    }
    root?.querySelectorAll?.(AUTOCOMPLETE_SELECTOR).forEach((element) => {
      element.setAttribute("autocomplete", "off");
    });
  }

  disableBrowserAutocomplete(document);

  const autocompleteObserver = new MutationObserver((records) => {
    records.forEach(({ addedNodes }) => {
      addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) disableBrowserAutocomplete(node);
      });
    });
  });
  autocompleteObserver.observe(document.documentElement, { childList: true, subtree: true });
})();

(() => {
  // Keep the active data owner visible on every page.  The local API proxy
  // intentionally preserves the same-origin frontend, so this small badge is
  // the clearest indication that CRUD and AI requests are currently going to
  // the server database rather than the fallback local database.
  async function showRemoteDataOwner() {
    try {
      const response = await fetch(`${window.location.origin}/settings/remote-client`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data?.enabled || document.querySelector(".remote-data-mode-banner")) return;
      document.body.classList.add("remote-data-mode");
      const banner = document.createElement("div");
      banner.className = "remote-data-mode-banner";
      banner.setAttribute("role", "status");
      banner.textContent = `サーバーDB接続中${data.server_label ? `：${data.server_label}` : ""}`;
      document.body.appendChild(banner);
    } catch {
      // The individual API calls surface connection failures.  The banner is
      // only an additional owner indicator and must never block page startup.
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", showRemoteDataOwner, { once: true });
  } else {
    void showRemoteDataOwner();
  }
})();

(() => {
  // WebView2/pywebview can lose the native selection owner while the pointer
  // moves. Keep Ctrl/Cmd+C working by copying the selected text through the
  // Windows clipboard API first, then use browser fallbacks in previews.
  function getSelectedText(event) {
    const target = event?.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      const start = Number(target.selectionStart);
      const end = Number(target.selectionEnd);
      if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
        return target.value.slice(start, end);
      }
      return "";
    }

    return window.getSelection?.()?.toString() || "";
  }

  async function copyText(text) {
    const value = String(text ?? "");
    if (!value) return false;

    const nativeApi = window.pywebview?.api;
    if (typeof nativeApi?.copy_text_to_clipboard === "function") {
      try {
        if (await nativeApi.copy_text_to_clipboard(value)) return true;
      } catch {
        // Browser fallbacks keep browser previews and restricted hosts usable.
      }
    }

    if (typeof navigator.clipboard?.writeText === "function") {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch {
        // Continue to the synchronous execCommand fallback.
      }
    }

    const active = document.activeElement;
    const start = active && "selectionStart" in active ? active.selectionStart : null;
    const end = active && "selectionEnd" in active ? active.selectionEnd : null;
    const selection = window.getSelection?.();
    const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange()) : [];
    const helper = document.createElement("textarea");
    helper.value = value;
    helper.setAttribute("readonly", "");
    helper.setAttribute("aria-hidden", "true");
    helper.style.position = "fixed";
    helper.style.left = "-9999px";
    helper.style.top = "0";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.focus({ preventScroll: true });
    helper.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    helper.remove();

    if (active && typeof active.focus === "function") {
      active.focus({ preventScroll: true });
      if (start != null && end != null && "selectionStart" in active) {
        active.selectionStart = start;
        active.selectionEnd = end;
      }
    } else if (selection && ranges.length) {
      selection.removeAllRanges();
      ranges.forEach((range) => selection.addRange(range));
    }
    return copied;
  }

  window.sparkleCopyText = copyText;

  document.addEventListener("copy", (event) => {
    const value = getSelectedText(event);
    if (!value) return;

    // Set clipboardData synchronously so the browser has a valid payload even
    // when the native bridge is temporarily unavailable.
    try {
      event.clipboardData?.setData("text/plain", value);
    } catch {
      // The async native/browser fallbacks below may still succeed.
    }

    // The Ask AI composer is a normal textarea. Let WebView2 finish its
    // native copy action for this control while retaining the native bridge
    // fallback for hosts where the default clipboard owner is unavailable.
    if (event.target?.id === "projectAssistantMessage") {
      void copyText(value);
      return;
    }

    event.preventDefault();
    void copyText(value);
  }, true);
})();

(() => {
  // The migration, initial setup, and extension guide share the onboarding
  // window profile. The native API keeps the profile editable while leaving
  // the window freely resizable (there is no aspect-ratio lock).
  let attempts = 0;

  function syncWindowProfile() {
    const api = window.pywebview?.api;
    if (!api || typeof api.set_window_profile !== "function") {
      if (attempts < 30) {
        attempts += 1;
        window.setTimeout(syncWindowProfile, 100);
      }
      return;
    }

    attempts = 0;
    const profile = document.body?.classList.contains("migration-page")
      ? "onboarding"
      : "default";
    void api.set_window_profile(profile).catch(() => {});
  }

  window.addEventListener("pywebviewready", syncWindowProfile);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", syncWindowProfile, { once: true });
  } else {
    syncWindowProfile();
  }
})();

(() => {
  // ファイルはホーム画面(index.html)だけで受け付ける。
  // ピンの並べ替えなど、text/plain を使う既存のドラッグ操作は対象外。
  if (document.body?.classList.contains("home-page")) return;

  function hasFilePayload(event) {
    const types = Array.from(event.dataTransfer?.types || []);
    return Boolean(
      event.dataTransfer?.files?.length ||
      types.some((type) => String(type).toLowerCase() === "files")
    );
  }

  function rejectFileDrop(event) {
    if (!hasFilePayload(event)) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.type === "dragover" && event.dataTransfer) {
      event.dataTransfer.dropEffect = "none";
    }
  }

  document.addEventListener("dragenter", rejectFileDrop, true);
  document.addEventListener("dragover", rejectFileDrop, true);
  document.addEventListener("drop", rejectFileDrop, true);
})();

(() => {
  let dialog = null;
  let activeRequest = null;
  let hideTimer = null;

  function handleDocumentPointerDown(event) {
    if (!activeRequest || !dialog || dialog.hidden) return;
    if (event.target instanceof Node && dialog.contains(event.target)) return;
    if (activeRequest.dismissOnOutsideClick === false) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    finish(false);
  }

  function ensureDialog() {
    if (dialog) return dialog;

    dialog = document.createElement("div");
    dialog.className = "app-confirm-popover";
    dialog.hidden = true;
    dialog.tabIndex = -1;
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "appConfirmTitle");
    dialog.setAttribute("aria-describedby", "appConfirmMessage");
    dialog.setAttribute("aria-hidden", "true");
    dialog.innerHTML = `
      <div class="app-confirm-card">
        <div class="app-confirm-mark" aria-hidden="true">!</div>
        <div class="app-confirm-copy">
          <h2 id="appConfirmTitle" class="app-confirm-title">本当に削除しますか？</h2>
          <p id="appConfirmMessage" class="app-confirm-message"></p>
        </div>
        <div class="app-confirm-actions">
          <button class="app-confirm-btn app-confirm-cancel" type="button" data-confirm-cancel>キャンセル</button>
          <button class="app-confirm-btn app-confirm-submit" type="button" data-confirm-submit>削除する</button>
        </div>
      </div>`;

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && activeRequest?.dismissOnOutsideClick !== false) finish(false);
    });
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => finish(false));
    dialog.querySelector("[data-confirm-submit]").addEventListener("click", () => finish(true));
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      if (activeRequest?.dismissOnEscape === false) return;
      finish(false);
    });
    document.body.appendChild(dialog);
    return dialog;
  }

  function position(request) {
    if (!dialog || dialog.hidden) return;

    const margin = 12;
    const gap = 10;
    const anchor = request.anchor && typeof request.anchor.getBoundingClientRect === "function"
      ? request.anchor
      : null;
    const anchorRect = anchor?.isConnected ? anchor.getBoundingClientRect() : null;
    const rect = dialog.getBoundingClientRect();
    const maxLeft = Math.max(margin, window.innerWidth - rect.width - margin);
    let left = anchorRect
      ? anchorRect.left + (anchorRect.width - rect.width) / 2
      : (window.innerWidth - rect.width) / 2;
    let top = anchorRect ? anchorRect.top - rect.height - gap : (window.innerHeight - rect.height) / 2;
    let placement = "above";

    if (anchorRect && top < margin) {
      top = anchorRect.bottom + gap;
      placement = "below";
    }

    left = Math.min(Math.max(left, margin), maxLeft);
    top = Math.min(Math.max(top, margin), Math.max(margin, window.innerHeight - rect.height - margin));
    dialog.style.left = `${Math.round(left)}px`;
    dialog.style.top = `${Math.round(top)}px`;
    dialog.dataset.placement = placement;
  }

  function finish(result) {
    if (!activeRequest || !dialog) return;
    const request = activeRequest;
    activeRequest = null;
    window.removeEventListener("resize", request.reposition);
    window.removeEventListener("scroll", request.reposition, true);
    document.removeEventListener("pointerdown", handleDocumentPointerDown, true);
    clearTimeout(hideTimer);
    dialog.classList.remove("is-open");
    dialog.setAttribute("aria-hidden", "true");
    hideTimer = window.setTimeout(() => {
      if (!activeRequest) dialog.hidden = true;
    }, 160);
    if (!result && request.returnFocus?.isConnected) {
      request.returnFocus.focus({ preventScroll: true });
    }
    request.resolve(result);
  }

  window.appConfirm = (message, options = {}) => {
    if (!document.body) return Promise.resolve(window.confirm(message));
    const nextDialog = ensureDialog();
    if (activeRequest) {
      if (activeRequest.blockReplacement) return Promise.resolve(false);
      finish(false);
    }
    clearTimeout(hideTimer);

    nextDialog.querySelector(".app-confirm-title").textContent = options.title || "本当に削除しますか？";
    nextDialog.querySelector(".app-confirm-message").textContent = message || "この操作は元に戻せません。";
    nextDialog.querySelector(".app-confirm-cancel").textContent = options.cancelLabel || "キャンセル";
    nextDialog.querySelector(".app-confirm-submit").textContent = options.confirmLabel || "削除する";
    nextDialog.hidden = false;
    nextDialog.setAttribute("aria-hidden", "false");
    const request = {
      anchor: options.anchor,
      dismissOnOutsideClick: options.dismissOnOutsideClick !== false,
      dismissOnEscape: options.dismissOnEscape !== false,
      blockReplacement: options.blockReplacement === true,
      returnFocus: document.activeElement,
      reposition: null,
      resolve: null,
    };
    request.reposition = () => position(request);

    const promise = new Promise((resolve) => {
      request.resolve = resolve;
      activeRequest = request;
    });
    position(request);
    window.addEventListener("resize", request.reposition);
    window.addEventListener("scroll", request.reposition, true);
    document.addEventListener("pointerdown", handleDocumentPointerDown, true);
    requestAnimationFrame(() => {
      if (activeRequest !== request) return;
      nextDialog.classList.add("is-open");
      nextDialog.querySelector("[data-confirm-cancel]").focus();
    });
    return promise;
  };

  window.confirmDeletion = (message, options = {}) => {
    if (options.immediate) return Promise.resolve(true);
    if (typeof window.appConfirm === "function") {
      return window.appConfirm(message, {
        anchor: options.anchor,
        title: options.title,
        cancelLabel: options.cancelLabel,
        confirmLabel: options.confirmLabel,
      });
    }
    return Promise.resolve(window.confirm(message));
  };
})();

(() => {
  const focusableSelector = [
    "button:not([disabled])",
    "[href]",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex=\"-1\"])",
  ].join(",");
  const openState = new WeakMap();
  const returnFocus = new WeakMap();
  const modalSelector = ".modal, .md-cheatsheet, .app-confirm-popover";

  function focusables(modal) {
    return [...modal.querySelectorAll(focusableSelector)].filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }

  function prepareModal(modal) {
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    const title = modal.querySelector(".modal-title, .app-confirm-title, h2, h1");
    if (title) {
      if (!title.id) title.id = `${modal.id || "modal"}-title`;
      modal.setAttribute("aria-labelledby", title.id);
    }
    if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
  }

  function syncModal(modal) {
    prepareModal(modal);
    const isOpen = !modal.hidden;
    const wasOpen = openState.get(modal) === true;
    modal.setAttribute("aria-hidden", String(!isOpen));
    openState.set(modal, isOpen);

    if (isOpen && !wasOpen) {
      returnFocus.set(modal, document.activeElement);
      requestAnimationFrame(() => {
        const first = focusables(modal)[0];
        if (first && !modal.hidden) first.focus();
      });
    } else if (!isOpen && wasOpen) {
      const previous = returnFocus.get(modal);
      if (previous && typeof previous.focus === "function" && document.contains(previous)) {
        previous.focus();
      }
      returnFocus.delete(modal);
    }
  }

  function install() {
    const status = document.createElement("div");
    status.id = "appStatus";
    status.className = "sr-only";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    document.body.appendChild(status);

    const modals = [...document.querySelectorAll(modalSelector)];
    modals.forEach(syncModal);
    const observer = new MutationObserver((records) => {
      const touched = new Set();
      records.forEach((record) => {
        if (record.target instanceof HTMLElement && record.target.matches(modalSelector)) {
          touched.add(record.target);
        }
      });
      touched.forEach(syncModal);
    });
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["hidden"] });

    document.addEventListener("keydown", (event) => {
      const modal = [...document.querySelectorAll(modalSelector)].find((candidate) => !candidate.hidden);
      if (!modal || event.key !== "Tab") return;
      const items = focusables(modal);
      if (!items.length) {
        event.preventDefault();
        modal.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    document.addEventListener("focusin", (event) => {
      const modal = [...document.querySelectorAll(modalSelector)].find((candidate) => !candidate.hidden);
      if (!modal || modal.contains(event.target)) return;
      const first = focusables(modal)[0];
      if (first) first.focus();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true });
  else install();
})();

(() => {
  const DISMISSED_RELEASE_KEY = "sparkle.update.dismissedRelease";
  const POLL_DELAY_MS = 800;
  const MAX_POLL_ATTEMPTS = 24;
  const shownReleaseTags = new Set();
  let promptActive = false;

  function isOnboardingPage() {
    return Boolean(document.body?.classList.contains("migration-page"));
  }

  function normalizeVersion(value) {
    return String(value || "").trim().replace(/^v/i, "");
  }

  function versionLabel(value) {
    const version = normalizeVersion(value);
    return version ? `v${version}` : "不明";
  }

  function readDismissedRelease() {
    try {
      return normalizeVersion(localStorage.getItem(DISMISSED_RELEASE_KEY));
    } catch {
      return "";
    }
  }

  function dismissRelease(tag) {
    if (!tag) return;
    try {
      localStorage.setItem(DISMISSED_RELEASE_KEY, tag);
    } catch {
      // Restricted browser storage should not prevent the update prompt.
    }
  }

  async function fetchUpdateState() {
    try {
      const response = await fetch(`${window.location.origin}/update/status`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  }

  async function readResponse(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  function updateLiveStatus(message) {
    const status = document.getElementById("appStatus");
    if (status) status.textContent = message;
  }

  async function showUpdateError(message) {
    updateLiveStatus(message);
    if (typeof window.appConfirm !== "function") return;
    const openSettings = await window.appConfirm(
      `${message}\n設定画面から、もう一度更新できます。`,
      {
        title: "アップデートに失敗しました",
        cancelLabel: "閉じる",
        confirmLabel: "設定を開く",
      },
    );
    if (openSettings) window.location.href = "/Settings";
  }

  async function waitForDownloadReady(timeoutMs = 180000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const state = await fetchUpdateState();
      if (state?.stage === "ready" || state?.stage === "installing") return state;
      if (state?.stage === "error") return state;
      updateLiveStatus("アップデートをダウンロードしています…");
      await new Promise((resolve) => window.setTimeout(resolve, 800));
    }
    return null;
  }

  async function applyUpdate(state) {
    const downloadResponse = await fetch(`${window.location.origin}/update/download`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const downloadResult = await readResponse(downloadResponse);
    if (!downloadResponse.ok || downloadResult.ok === false) {
      throw new Error(downloadResult.detail || "アップデートのダウンロードを開始できませんでした。");
    }

    updateLiveStatus(`アップデート ${versionLabel(state.latest)} を準備しています…`);
    const readyState = await waitForDownloadReady();
    if (!readyState || readyState.stage === "error") {
      throw new Error(readyState?.error || "ダウンロードまたは検証に失敗しました。");
    }

    updateLiveStatus("アップデートを適用しています。アプリは再起動します…");
    try {
      const applyResponse = await fetch(`${window.location.origin}/update/apply`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (!applyResponse.ok) {
        const result = await readResponse(applyResponse);
        throw new Error(result.detail || "アップデートの適用に失敗しました。");
      }
    } catch (error) {
      // Applying the update intentionally closes the server and WebView. A
      // fetch rejection at this point usually means the restart has started.
      const currentState = await fetchUpdateState();
      if (!currentState) return;
      throw error;
    }
  }

  async function showUpdatePrompt(state) {
    if (promptActive || typeof window.appConfirm !== "function") return;

    const tag = normalizeVersion(state.latest);
    if (!tag || shownReleaseTags.has(tag) || readDismissedRelease() === tag) return;
    shownReleaseTags.add(tag);
    promptActive = true;
    const profileAnchor = document.querySelector(".side-btn-profile .profile-avatar")
      || document.querySelector(".side-btn-profile");

    try {
      const updateNow = await window.appConfirm(
        `新しいバージョン ${versionLabel(tag)} が利用できます。\n現在のバージョン: ${versionLabel(state.current)}`,
        {
          title: "Sparkleのアップデートがあります",
          cancelLabel: "閉じる",
          confirmLabel: "アップデートする",
          anchor: profileAnchor,
          dismissOnOutsideClick: false,
          dismissOnEscape: false,
          blockReplacement: true,
        },
      );

      if (!updateNow) {
        dismissRelease(tag);
        updateLiveStatus(`アップデート ${versionLabel(tag)} の通知を閉じました。`);
        return;
      }

      try {
        await applyUpdate(state);
      } catch (error) {
        await showUpdateError(error instanceof Error ? error.message : "アップデートに失敗しました。");
      }
    } finally {
      promptActive = false;
    }
  }

  async function checkForAvailableUpdate() {
    if (isOnboardingPage()) return;

    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      const state = await fetchUpdateState();
      if (!state || state.enabled === false) return;
      if (state.stage === "available") {
        await showUpdatePrompt(state);
        return;
      }
      if (state.stage !== "idle" && state.stage !== "checking") return;
      await new Promise((resolve) => window.setTimeout(resolve, POLL_DELAY_MS));
    }
  }

  // 設定画面の手動チェック完了後にも、同じ通知経路を再利用する。
  window.sparkleUpdateNotice = {
    check: checkForAvailableUpdate,
  };

  function installUpdateNotice() {
    void checkForAvailableUpdate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installUpdateNotice, { once: true });
  } else {
    installUpdateNotice();
  }
})();

(() => {
  let activeDrag = null;
  let activeResize = null;

  function updateMaximizeButton(button, maximized) {
    if (!button || typeof maximized !== "boolean") return;
    const label = maximized ? "元に戻す" : "最大化";
    button.title = label;
    button.setAttribute("aria-label", label);
  }

  function installWindowControls() {
    document.querySelectorAll("[data-window-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const action = button.dataset.windowAction;
        const api = window.pywebview?.api;
        if (!action || !api || typeof api[action] !== "function") return;

        try {
          const result = await api[action]();
          if (action === "toggle_maximize_window") {
            updateMaximizeButton(button, result);
          }
        } catch {
          // Browser previews do not expose the native window API.
        }
      });
    });
  }

  function installHistoryControls() {
    document.querySelectorAll("[data-history-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.historyAction;
        if (action === "back") window.history.back();
        if (action === "forward") window.history.forward();
      });
    });
  }

  function isSmallSidebarGap(event, sidebar) {
    const x = event.clientX;
    const y = event.clientY;
    return [...sidebar.querySelectorAll(".sidebar-history, .side-btn, .sidebar-tools")].some((element) => {
      const rect = element.getBoundingClientRect();
      return x >= rect.left && x <= rect.right && y >= rect.top - 4 && y <= rect.bottom + 4;
    });
  }

  function canStartSidebarDrag(event, sidebar) {
    const target = event.target;
    if (target?.closest?.("[data-window-action], [data-history-action], .side-btn, .sidebar-tools, .window-controls")) return false;
    if (target?.closest?.(".sidebar-history, .side-spacer")) return true;
    if (target !== sidebar) return false;
    return !isSmallSidebarGap(event, sidebar);
  }

  function startWindowDragFallback(api, startScreenX, startScreenY) {
    if (typeof api.begin_window_drag !== "function" || typeof api.move_window !== "function") return;

    const drag = { api, geometry: null, startScreenX, startScreenY };
    activeDrag = drag;

    const cleanup = () => {
      if (activeDrag !== drag) return;
      activeDrag = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", cleanup);
      window.removeEventListener("blur", cleanup);
    };

    const onMouseMove = (moveEvent) => {
      if (activeDrag !== drag || !drag.geometry) return;
      const x = drag.geometry.x + moveEvent.screenX - drag.startScreenX;
      const y = drag.geometry.y + moveEvent.screenY - drag.startScreenY;
      void drag.api.move_window(Math.round(x), Math.round(y));
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", cleanup);
    window.addEventListener("blur", cleanup);

    api.begin_window_drag(startScreenX, startScreenY).then((geometry) => {
      if (activeDrag !== drag) return;
      if (!geometry || typeof geometry.x !== "number") {
        cleanup();
        return;
      }
      drag.geometry = geometry;
      if (geometry.restored) {
        updateMaximizeButton(
          document.querySelector('[data-window-action="toggle_maximize_window"]'),
          false,
        );
      }
    }).catch(cleanup);
  }

  function startWindowDrag(event) {
    const api = window.pywebview?.api;
    if (!api) return;

    // With the native Windows caption enabled, the OS title bar owns window
    // moving. Dragging in-app regions would fight the caption drag, so the
    // sidebar/header drag handlers are disabled in that mode.
    if (document.documentElement.classList.contains("native-titlebar")) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const startScreenX = event.screenX;
    const startScreenY = event.screenY;

    // Let Windows own the pointer loop. The previous implementation moved the
    // window from WebView mousemove events, which stops receiving events as
    // soon as the window leaves the pointer's original position.
    if (typeof api.begin_native_drag === "function") {
      try {
        Promise.resolve(api.begin_native_drag(startScreenX, startScreenY)).then((started) => {
          if (started !== false || activeDrag !== null) return;
          startWindowDragFallback(api, startScreenX, startScreenY);
        }).catch(() => {
          if (activeDrag === null) startWindowDragFallback(api, startScreenX, startScreenY);
        });
      } catch {
        startWindowDragFallback(api, startScreenX, startScreenY);
      }
      return;
    }

    startWindowDragFallback(api, startScreenX, startScreenY);
  }

  function installWindowDrag() {
    document.querySelectorAll(".sidebar").forEach((sidebar) => {
      sidebar.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || !canStartSidebarDrag(event, sidebar)) return;
        startWindowDrag(event);
      }, { capture: true });
    });
    const dragRegionSelector = `.window-drag-region, #stickyHeader`;
    const dragRegionExclude = "button, a, input, select, textarea, [role=listbox], .sort-select, .fav-only, .search-wrap";

    document.querySelectorAll(dragRegionSelector).forEach((region) => {
      region.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || event.target?.closest?.(dragRegionExclude)) return;
        startWindowDrag(event);
      }, { capture: true });
    });
  }

  function resizeWindowFromPointer(event, direction) {
    const api = window.pywebview?.api;
    const hasNativeResize = typeof api?.begin_native_resize === "function";
    const hasFallbackResize = typeof api?.begin_window_resize === "function"
      && typeof api?.resize_window === "function";
    if (!api || (!hasNativeResize && !hasFallbackResize)) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const startScreenX = event.screenX;
    const startScreenY = event.screenY;

    // Let Windows own the pointer loop. Resizing by repeatedly calling the
    // WebView API loses mouse events as soon as the edge moves away from the
    // pointer, just like the old custom window drag implementation.
    if (typeof api.begin_native_resize === "function") {
      try {
        Promise.resolve(api.begin_native_resize(direction)).then((started) => {
          if (started !== false || activeResize !== null) return;
          if (hasFallbackResize) {
            startWindowResizeFallback(api, direction, startScreenX, startScreenY);
          }
        }).catch(() => {
          if (hasFallbackResize && activeResize === null) {
            startWindowResizeFallback(api, direction, startScreenX, startScreenY);
          }
        });
      } catch {
        if (hasFallbackResize) {
          startWindowResizeFallback(api, direction, startScreenX, startScreenY);
        }
      }
      return;
    }

    if (hasFallbackResize) {
      startWindowResizeFallback(api, direction, startScreenX, startScreenY);
    }
  }

  function startWindowResizeFallback(api, direction, startScreenX, startScreenY) {
    const resize = { api, direction, geometry: null, startScreenX, startScreenY };
    activeResize = resize;

    const cleanup = () => {
      if (activeResize !== resize) return;
      activeResize = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", cleanup);
      window.removeEventListener("blur", cleanup);
    };

    const onMouseMove = (moveEvent) => {
      if (activeResize !== resize || !resize.geometry) return;

      const deltaX = moveEvent.screenX - resize.startScreenX;
      const deltaY = moveEvent.screenY - resize.startScreenY;
      const minimumWidth = Number.isFinite(resize.geometry.minimum_width)
        ? resize.geometry.minimum_width
        : 960;
      const minimumHeight = Number.isFinite(resize.geometry.minimum_height)
        ? resize.geometry.minimum_height
        : 640;
      let { x, y, width, height } = resize.geometry;

      if (direction.includes("w")) {
        const nextWidth = Math.max(minimumWidth, resize.geometry.width - deltaX);
        x = resize.geometry.x + resize.geometry.width - nextWidth;
        width = nextWidth;
      } else if (direction.includes("e")) {
        width = Math.max(minimumWidth, resize.geometry.width + deltaX);
      }

      if (direction.includes("n")) {
        const nextHeight = Math.max(minimumHeight, resize.geometry.height - deltaY);
        y = resize.geometry.y + resize.geometry.height - nextHeight;
        height = nextHeight;
      } else if (direction.includes("s")) {
        height = Math.max(minimumHeight, resize.geometry.height + deltaY);
      }

      void resize.api.resize_window(Math.round(width), Math.round(height), Math.round(x), Math.round(y));
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", cleanup);
    window.addEventListener("blur", cleanup);

    api.begin_window_resize().then((geometry) => {
      if (activeResize !== resize) return;
      if (!geometry || typeof geometry.x !== "number") {
        cleanup();
        return;
      }
      resize.geometry = geometry;
      if (geometry.restored) {
        updateMaximizeButton(
          document.querySelector('[data-window-action="toggle_maximize_window"]'),
          false,
        );
      }
    }).catch(cleanup);
  }

  function installWindowResizeHandles() {
    if (document.querySelector("[data-window-resize]")) return;

    const directions = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
    const fragment = document.createDocumentFragment();
    directions.forEach((direction) => {
      const handle = document.createElement("div");
      handle.className = `window-resize-handle window-resize-${direction}`;
      handle.dataset.windowResize = direction;
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("mousedown", (event) => resizeWindowFromPointer(event, direction), { capture: true });
      fragment.appendChild(handle);
    });
    document.body.appendChild(fragment);
  }

  function installWindowInteraction() {
    installWindowDrag();
    installWindowResizeHandles();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      installWindowControls();
      installHistoryControls();
      installWindowInteraction();
    }, { once: true });
  } else {
    installWindowControls();
    installHistoryControls();
    installWindowInteraction();
  }
})();
