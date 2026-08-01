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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installWindowControls, { once: true });
  } else {
    installWindowControls();
  }
})();
