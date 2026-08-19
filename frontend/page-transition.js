(() => {
  // Keep the gesture at the page-navigation layer. The three workbench pages
  // are separate HTML documents, so the destination is selected from the
  // same route table used by the sidebar rather than from SPA state.
  const ROUTES = [
    { path: "/Home", aliases: ["/", "/index.html"], nav: "home" },
    { path: "/Notes", aliases: ["/notes.html"], nav: "memo" },
    { path: "/Projects", aliases: ["/projects.html"], nav: "projects" },
  ];
  const TRANSITION_KEY = "sparkle.pageTransition";
  const SWIPE_LOCK_KEY = "sparkle.pageSwipeLockUntil";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const SWIPE_THRESHOLD = 96;
  const SWIPE_WINDOW_MS = 220;
  const SWIPE_COOLDOWN_MS = 500;
  const SWIPE_GESTURE_LOCK_MS = 1000;
  const HORIZONTAL_SCROLL_TOLERANCE_PX = 8;
  const AXIS_RATIO = 1.2;
  const LINE_DELTA_PX = 16;
  let installed = false;
  let accumulatedDelta = 0;
  let accumulatedSign = 0;
  let accumulationStartedAt = 0;
  let cooldownUntil = 0;
  let swipeLockUntil = 0;

  function normalizePath(pathname) {
    const value = String(pathname || "/").replace(/\/+$/, "");
    return value || "/";
  }

  function routeIndex(pathname = window.location.pathname) {
    const path = normalizePath(pathname);
    return ROUTES.findIndex(
      (route) => route.path === path || route.aliases?.includes(path),
    );
  }

  function getSwipeContext() {
    const path = normalizePath(window.location.pathname);
    if (path === "/Note" || path === "/note-editor.html") {
      return {
        type: "back",
        targetPath: "/Notes",
        backElementId: "backLink",
      };
    }

    if (
      (path === "/Projects" || path === "/projects.html") &&
      new URLSearchParams(window.location.search).has("id")
    ) {
      return {
        type: "back",
        targetPath: "/Projects",
        backElementId: "backToList",
        sameDocument: true,
      };
    }

    const currentIndex = routeIndex(path);
    return currentIndex < 0 ? null : { type: "route", currentIndex };
  }

  function resetAccumulator() {
    accumulatedDelta = 0;
    accumulatedSign = 0;
    accumulationStartedAt = 0;
  }

  function clearTransitionMarker() {
    try {
      sessionStorage.removeItem(TRANSITION_KEY);
    } catch {
      // Navigation remains usable when storage is unavailable.
    }
  }

  function restoreSwipeLock() {
    try {
      const storedUntil = Number(sessionStorage.getItem(SWIPE_LOCK_KEY));
      swipeLockUntil = Number.isFinite(storedUntil) && storedUntil > Date.now() ? storedUntil : 0;
      if (!swipeLockUntil) sessionStorage.removeItem(SWIPE_LOCK_KEY);
    } catch {
      swipeLockUntil = 0;
    }
  }

  function lockSwipeGesture(now = Date.now()) {
    swipeLockUntil = now + SWIPE_GESTURE_LOCK_MS;
    try {
      sessionStorage.setItem(SWIPE_LOCK_KEY, String(swipeLockUntil));
    } catch {
      // The in-memory lock still protects the current document.
    }
  }

  function isSwipeLocked(now = Date.now()) {
    if (now < swipeLockUntil) {
      // Trackpad inertia can continue after the document navigation. Extend
      // the quiet period whenever another horizontal event from that tail
      // arrives, including on the destination document.
      lockSwipeGesture(now);
      return true;
    }
    if (swipeLockUntil) {
      swipeLockUntil = 0;
      try {
        sessionStorage.removeItem(SWIPE_LOCK_KEY);
      } catch {
        // Ignore storage cleanup failures.
      }
    }
    return false;
  }

  function markTransition(targetPath, direction) {
    try {
      sessionStorage.setItem(
        TRANSITION_KEY,
        JSON.stringify({
          targetPath: normalizePath(targetPath),
          direction,
          markedAt: Date.now(),
        }),
      );
    } catch {
      // Navigation remains usable when storage is unavailable.
    }
  }

  function consumeTransition() {
    let marker = null;
    try {
      const raw = sessionStorage.getItem(TRANSITION_KEY);
      sessionStorage.removeItem(TRANSITION_KEY);
      marker = raw ? JSON.parse(raw) : null;
    } catch {
      marker = null;
    }

    if (
      reduceMotion.matches ||
      !marker ||
      marker.targetPath !== normalizePath(window.location.pathname) ||
      !["forward", "back"].includes(marker.direction) ||
      !Number.isFinite(Number(marker.markedAt)) ||
      Date.now() - Number(marker.markedAt) >= 2000
    ) {
      return;
    }

    const className = `page-transition-enter-${marker.direction}`;
    document.documentElement.classList.add(className);
    window.setTimeout(() => {
      document.documentElement.classList.remove(className);
    }, 360);
  }

  function hasHorizontalScrollParent(target) {
    let element = target;
    while (element && element !== document.body) {
      const style = window.getComputedStyle(element);
      const scrollable = ["auto", "scroll", "overlay"].includes(style.overflowX);
      if (
        scrollable &&
        element.scrollWidth > element.clientWidth + HORIZONTAL_SCROLL_TOLERANCE_PX
      ) {
        return true;
      }
      element = element.parentElement;
    }
    return false;
  }

  function isIgnoredTarget(target) {
    if (
      target.closest(
        ".sidebar, .window-controls, .window-drag-region, " +
          ".modal:not([hidden]), .app-confirm-popover:not([hidden]), " +
          "input, textarea, select, button, a, " +
          "[contenteditable=\"true\"], [data-no-page-swipe]",
      )
    ) {
      return true;
    }

    if (target.closest("[data-page-swipe-surface]")) return false;

    // Notes and Projects use vertical list scrollers whose computed
    // overflowX can become `auto` even though they have no intentional
    // horizontal interaction. Keep the page surface swipeable there.
    if (
      target.closest("#mainContent") &&
      document.body?.matches("body.notes-page, body.projects-page")
    ) {
      return false;
    }

    return hasHorizontalScrollParent(target);
  }

  function normalizeWheelDelta(event) {
    const unit =
      event.deltaMode === 1
        ? LINE_DELTA_PX
        : event.deltaMode === 2
          ? Math.max(window.innerWidth, 1)
          : 1;
    return { x: event.deltaX * unit, y: event.deltaY * unit };
  }

  function navigateBySwipe(deltaSign, context) {
    if (!context) return;
    clearTransitionMarker();

    if (context.type === "back") {
      lockSwipeGesture();
      if (context.sameDocument) {
        const backButton = document.getElementById(context.backElementId);
        if (backButton) {
          backButton.click();
          return;
        }
      } else {
        const backLink = document.getElementById(context.backElementId);
        if (backLink) {
          backLink.click();
          return;
        }
      }
      window.location.assign(context.targetPath);
      return;
    }

    const currentIndex = context.currentIndex;
    if (currentIndex < 0) return;

    // A negative deltaX is a physical left swipe in Chromium's wheel model.
    // The three main pages form a loop, so either direction always advances
    // exactly one page (Home <- Notes <- Projects <- Home).
    const step = deltaSign < 0 ? 1 : -1;
    const targetIndex = (currentIndex + step + ROUTES.length) % ROUTES.length;

    const target = ROUTES[targetIndex];
    lockSwipeGesture();
    window.location.assign(target.path);
  }

  function handleWheel(event) {
    if (
      event.defaultPrevented ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      !(event.target instanceof Element) ||
      !getSwipeContext() ||
      isIgnoredTarget(event.target)
    ) {
      resetAccumulator();
      return;
    }

    const now = Date.now();
    if (now < cooldownUntil) {
      resetAccumulator();
      return;
    }

    const { x, y } = normalizeWheelDelta(event);
    if (!x || Math.abs(x) <= Math.abs(y) * AXIS_RATIO) {
      resetAccumulator();
      return;
    }
    if (isSwipeLocked(now)) {
      resetAccumulator();
      return;
    }

    const sign = Math.sign(x);
    if (
      sign !== accumulatedSign ||
      !accumulationStartedAt ||
      now - accumulationStartedAt > SWIPE_WINDOW_MS
    ) {
      accumulatedDelta = 0;
      accumulatedSign = sign;
      accumulationStartedAt = now;
    }
    accumulatedDelta += x;

    if (Math.abs(accumulatedDelta) < SWIPE_THRESHOLD) return;

    const context = getSwipeContext();
    resetAccumulator();
    cooldownUntil = now + SWIPE_COOLDOWN_MS;
    if (!context) return;

    if (event.cancelable) event.preventDefault();
    navigateBySwipe(sign, context);
  }

  function handleSidebarClick(event) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
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
    const currentIndex = routeIndex();
    const destinationIndex = routeIndex(destination.pathname);
    if (
      destination.origin !== window.location.origin ||
      destinationIndex < 0 ||
      currentIndex < 0 ||
      destinationIndex === currentIndex
    ) {
      return;
    }

    markTransition(
      destination.pathname,
      destinationIndex > currentIndex ? "forward" : "back",
    );
  }

  function boot() {
    if (installed || !window.pywebview?.api) return;
    installed = true;
    restoreSwipeLock();
    consumeTransition();
    document.addEventListener("wheel", handleWheel, {
      capture: true,
      passive: false,
    });
    document.addEventListener("click", handleSidebarClick, true);
  }

  // This feature is for the native desktop WebView2 host. The local browser
  // preview and the separate Remote Web UI do not opt in accidentally.
  if (window.pywebview?.api) {
    boot();
  } else {
    window.addEventListener("pywebviewready", boot, { once: true });
  }
})();
