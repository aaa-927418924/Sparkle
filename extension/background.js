// Sparkle - background service worker
// スクリーンショットによるサムネイル選択を仲介する。

let _pendingOpenPopup = false;

chrome.commands.onCommand.addListener((command) => {
  if (command === "take-screenshot") {
    _pendingOpenPopup = true;
    startSelection();
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "start-thumbnail-selection") {
    startSelection();
    return false;
  }

  if (msg && msg.type === "selection-done") {
    // content script から選択矩形が届いた
    const tab = sender.tab;
    const shouldOpen = _pendingOpenPopup;
    _pendingOpenPopup = false;
    handleSelectionDone(tab, msg.rect, msg.dpr)
      .then(() => {
        if (shouldOpen) {
          chrome.action.openPopup().catch(() => {});
        }
        sendResponse({ ok: true });
      })
      .catch((e) => {
        console.error("selection-done failed:", e);
        sendResponse({ ok: false, error: String(e) });
      });
    return true; // 非同期レスポンス
  }

  if (msg && msg.type === "selection-cancelled") {
    _pendingOpenPopup = false;
    return false;
  }

  return false;
});

async function startSelection() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    _pendingOpenPopup = false;
    return;
  }
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "start-selection" });
  } catch (e) {
    // content script が読み込まれていない (chrome:// 等) 場合
    console.warn("Could not start selection on this tab:", e);
    _pendingOpenPopup = false;
  }
}

async function handleSelectionDone(tab, rect, dpr) {
  if (!tab) throw new Error("No source tab");

  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "png",
  });

  const cropped = await cropDataUrl(dataUrl, rect, dpr);

  await chrome.storage.session.set({
    pendingThumbnail: cropped,
    pendingThumbnailUrl: tab.url || null,
  });

  try {
    await chrome.action.setBadgeBackgroundColor({ color: "#d97757" });
    await chrome.action.setBadgeText({ text: "✓" });
  } catch (e) {
    // バッジは任意なので失敗しても無視
  }
}

// captureVisibleTab の画像は物理ピクセル基準なので rect に dpr を掛ける
async function cropDataUrl(dataUrl, rect, dpr) {
  const scale = dpr || 1;
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  const bitmap = await createImageBitmap(blob);

  let sx = Math.round(rect.x * scale);
  let sy = Math.round(rect.y * scale);
  let sw = Math.round(rect.width * scale);
  let sh = Math.round(rect.height * scale);

  // 画像の範囲内にクランプ
  sx = Math.max(0, Math.min(sx, bitmap.width));
  sy = Math.max(0, Math.min(sy, bitmap.height));
  sw = Math.max(1, Math.min(sw, bitmap.width - sx));
  sh = Math.max(1, Math.min(sh, bitmap.height - sy));

  const canvas = new OffscreenCanvas(sw, sh);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, sw, sh);
  bitmap.close();

  const outBlob = await canvas.convertToBlob({ type: "image/png" });
  return await blobToDataUrl(outBlob);
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
