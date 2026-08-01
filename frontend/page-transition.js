(() => {
  const markerKey = "aiClipSave.sidebarPageEnterAt";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  try {
    const markedAt = Number(sessionStorage.getItem(markerKey));
    sessionStorage.removeItem(markerKey);

    if (
      !reduceMotion.matches &&
      Number.isFinite(markedAt) &&
      Date.now() - markedAt < 2000
    ) {
      document.documentElement.classList.add("sidebar-page-enter");
    }
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }

  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      reduceMotion.matches ||
      !(event.target instanceof Element)
    ) {
      return;
    }

    const link = event.target.closest(".sidebar a.side-btn[href]");
    if (
      !link ||
      link.hasAttribute("download") ||
      (link.target && link.target !== "_self")
    ) {
      return;
    }

    const destination = new URL(link.href, window.location.href);
    if (
      destination.origin !== window.location.origin ||
      destination.href === window.location.href
    ) {
      return;
    }

    try {
      sessionStorage.setItem(markerKey, String(Date.now()));
    } catch {
      // Navigation remains immediate even when the marker cannot be stored.
    }
  }, true);
})();
