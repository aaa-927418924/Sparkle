// AI Clip Save - content script
// "start-selection" を受けてページ上でドラッグ範囲選択UIを表示する。

(function () {
  if (window.__aiClipSelectionInjected) return;
  window.__aiClipSelectionInjected = true;

  let overlay = null;
  let selectionBox = null;
  let startX = 0;
  let startY = 0;
  let dragging = false;

  const OVERLAY_ID = "__ai-clip-selection-overlay";

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "start-selection") {
      beginSelection();
    }
  });

  function beginSelection() {
    if (overlay) return;

    overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    Object.assign(overlay.style, {
      position: "fixed",
      inset: "0",
      zIndex: "999999",
      cursor: "crosshair",
      background: "rgba(0, 0, 0, 0.35)",
      userSelect: "none",
      margin: "0",
    });

    // 選択中の明るくくり抜く矩形
    selectionBox = document.createElement("div");
    Object.assign(selectionBox.style, {
      position: "fixed",
      border: "2px solid #d97757",
      // 周囲を暗く保ちつつ選択部分を明るく見せる
      boxShadow: "0 0 0 100000px rgba(0, 0, 0, 0.35)",
      background: "transparent",
      pointerEvents: "none",
      display: "none",
      left: "0px",
      top: "0px",
      width: "0px",
      height: "0px",
    });

    const hint = document.createElement("div");
    hint.textContent = "ドラッグで範囲を選択  (Esc でキャンセル)";
    Object.assign(hint.style, {
      position: "fixed",
      top: "12px",
      left: "50%",
      transform: "translateX(-50%)",
      background: "rgba(0, 0, 0, 0.75)",
      color: "#fff",
      padding: "6px 14px",
      borderRadius: "999px",
      fontSize: "13px",
      fontFamily: "system-ui, sans-serif",
      pointerEvents: "none",
      zIndex: "1000000",
    });
    overlay.__hint = hint;

    overlay.appendChild(selectionBox);
    overlay.appendChild(hint);
    document.documentElement.appendChild(overlay);

    overlay.addEventListener("mousedown", onMouseDown);
    overlay.addEventListener("mousemove", onMouseMove);
    overlay.addEventListener("mouseup", onMouseUp);
    document.addEventListener("keydown", onKeyDown, true);
  }

  function onMouseDown(e) {
    e.preventDefault();
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    // ドラッグ開始したらオーバーレイ自身の暗幕は selectionBox の boxShadow に任せる
    overlay.style.background = "transparent";
    if (overlay.__hint) overlay.__hint.style.display = "none";
    selectionBox.style.display = "block";
    updateBox(startX, startY, 0, 0);
  }

  function onMouseMove(e) {
    if (!dragging) return;
    const x = Math.min(startX, e.clientX);
    const y = Math.min(startY, e.clientY);
    const w = Math.abs(e.clientX - startX);
    const h = Math.abs(e.clientY - startY);
    updateBox(x, y, w, h);
  }

  function onMouseUp(e) {
    if (!dragging) return;
    dragging = false;

    const x = Math.min(startX, e.clientX);
    const y = Math.min(startY, e.clientY);
    const w = Math.abs(e.clientX - startX);
    const h = Math.abs(e.clientY - startY);

    const dpr = window.devicePixelRatio || 1;
    cleanup();

    if (w < 4 || h < 4) {
      // 実質クリックのみ → キャンセル扱い
      chrome.runtime.sendMessage({ type: "selection-cancelled" });
      return;
    }

    chrome.runtime.sendMessage({
      type: "selection-done",
      rect: { x, y, width: w, height: h },
      dpr,
    });
  }

  function onKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      cleanup();
      chrome.runtime.sendMessage({ type: "selection-cancelled" });
    }
  }

  function updateBox(x, y, w, h) {
    selectionBox.style.left = x + "px";
    selectionBox.style.top = y + "px";
    selectionBox.style.width = w + "px";
    selectionBox.style.height = h + "px";
  }

  function cleanup() {
    document.removeEventListener("keydown", onKeyDown, true);
    if (overlay) {
      overlay.removeEventListener("mousedown", onMouseDown);
      overlay.removeEventListener("mousemove", onMouseMove);
      overlay.removeEventListener("mouseup", onMouseUp);
      overlay.remove();
    }
    overlay = null;
    selectionBox = null;
    dragging = false;
  }
})();
