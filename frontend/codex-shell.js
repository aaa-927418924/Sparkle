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
    if (!(event.target instanceof Node) || !dialog.contains(event.target)) finish(false);
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
      if (event.target === dialog) finish(false);
    });
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => finish(false));
    dialog.querySelector("[data-confirm-submit]").addEventListener("click", () => finish(true));
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
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
    if (activeRequest) finish(false);
    clearTimeout(hideTimer);

    nextDialog.querySelector(".app-confirm-title").textContent = options.title || "本当に削除しますか？";
    nextDialog.querySelector(".app-confirm-message").textContent = message || "この操作は元に戻せません。";
    nextDialog.querySelector(".app-confirm-cancel").textContent = options.cancelLabel || "キャンセル";
    nextDialog.querySelector(".app-confirm-submit").textContent = options.confirmLabel || "削除する";
    nextDialog.hidden = false;
    nextDialog.setAttribute("aria-hidden", "false");
    const request = {
      anchor: options.anchor,
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

  function isSmallSidebarGap(event, sidebar) {
    const x = event.clientX;
    const y = event.clientY;
    return [...sidebar.querySelectorAll(".sidebar-titlebar, .side-btn, .sidebar-tools")].some((element) => {
      const rect = element.getBoundingClientRect();
      return x >= rect.left && x <= rect.right && y >= rect.top - 4 && y <= rect.bottom + 4;
    });
  }

  function canStartSidebarDrag(event, sidebar) {
    const target = event.target;
    if (target?.closest?.("[data-window-action], .side-btn, .sidebar-tools, .window-controls")) return false;
    if (target?.closest?.(".sidebar-titlebar, .side-spacer")) return true;
    if (target !== sidebar) return false;
    return !isSmallSidebarGap(event, sidebar);
  }

  function startWindowDrag(event) {
    const api = window.pywebview?.api;
    if (!api || typeof api.begin_window_drag !== "function" || typeof api.move_window !== "function") return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const startScreenX = event.screenX;
    const startScreenY = event.screenY;
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

  function installWindowDrag() {
    document.querySelectorAll(".sidebar").forEach((sidebar) => {
      sidebar.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || !canStartSidebarDrag(event, sidebar)) return;
        startWindowDrag(event);
      }, { capture: true });
    });
    document.querySelectorAll(".window-drag-region").forEach((region) => {
      region.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || event.target?.closest?.("button, a, input, select, textarea")) return;
        startWindowDrag(event);
      }, { capture: true });
    });
  }

  function resizeWindowFromPointer(event, direction) {
    const api = window.pywebview?.api;
    if (!api || typeof api.begin_window_resize !== "function" || typeof api.resize_window !== "function") return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const startScreenX = event.screenX;
    const startScreenY = event.screenY;
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
      const minimumWidth = 960;
      const minimumHeight = 640;
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
      installWindowInteraction();
    }, { once: true });
  } else {
    installWindowControls();
    installWindowInteraction();
  }
})();
