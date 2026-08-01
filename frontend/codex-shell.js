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
  const modalSelector = ".modal, .md-cheatsheet";

  function focusables(modal) {
    return [...modal.querySelectorAll(focusableSelector)].filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }

  function prepareModal(modal) {
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    const title = modal.querySelector(".modal-title, h2, h1");
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

  function installWindowDrag() {
    document.querySelectorAll("[data-window-drag]").forEach((titlebar) => {
      titlebar.addEventListener("mousedown", (event) => {
        if (event.button !== 0) return;
        if (event.target.closest?.("[data-window-action]")) return;

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

        api.begin_window_drag().then((geometry) => {
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
