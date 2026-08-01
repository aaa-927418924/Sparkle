const API_ROOT = window.location.origin;
const PIN_KEY = "pins";
const PIN_MAX = 10;
// API is defined by each page's main script (app.js/notes.js/projects.js)

function getPins() {
  try { return JSON.parse(localStorage.getItem(PIN_KEY)) || []; } catch { return []; }
}

function savePins(pins) {
  localStorage.setItem(PIN_KEY, JSON.stringify(pins));
}

function addPin(id, type) {
  let pins = getPins();
  if (pins.some((p) => p.id === id && p.type === type)) return;
  if (pins.length >= PIN_MAX) {
    alert(`ピン止めは最大${PIN_MAX}個までです。\n既存のピンを右クリックで解除してから追加してください。`);
    return;
  }
  pins.push({ id, type, order: pins.length });
  savePins(pins);
}

function removePin(id, type) {
  let pins = getPins().filter((p) => !(p.id === id && p.type === type));
  pins.forEach((p, i) => (p.order = i));
  savePins(pins);
}

function isPinned(id, type) {
  return getPins().some((p) => p.id === id && p.type === type);
}

function syncPinButtonStates() {
  const pins = getPins();
  document.querySelectorAll("[data-pin][data-pin-type]").forEach((button) => {
    const id = Number(button.dataset.pin);
    const type = button.dataset.pinType;
    const pinned = pins.some((pin) => pin.id === id && pin.type === type);
    button.classList.toggle("on", pinned);
    button.title = pinned ? "ピン止めを解除" : "ピン止め";
  });
}

function togglePin(id, type) {
  if (isPinned(id, type)) removePin(id, type);
  else addPin(id, type);
}

// ---- Sidebar Injection ----

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

let tooltipEl = null;
let tooltipTimer = null;
let tooltipDataCache = {};
let tooltipGen = 0;

function getPinIcon(type) {
  return type === "clip" ? "icons/clip3.svg" :
    type === "note" ? "icons/memo.svg" :
      "icons/project.svg";
}

function getPinLabel(type) {
  return type === "clip" ? "クリップ" :
    type === "note" ? "メモ" : "プロジェクト";
}

function getPinName(data, type) {
  if (!data) return "";
  const name = type === "project" ? data.name : data.title;
  return typeof name === "string" ? name.trim() : "";
}

function buildProjectPinCounts(data) {
  const counts = [
    { icon: "icons/clip.svg", label: "クリップ", value: (data._clips || []).length },
    { icon: "icons/checkbox.svg", label: "タスク", value: (data._tasks || []).length },
    { icon: "icons/clipboard.svg", label: "メモ", value: (data._notes || []).length },
  ];
  return counts.map((item) => {
    const label = `${item.label} ${item.value}件`;
    return `<span class="pin-count" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">
      <img class="icon icon-inline icon-pin-count" src="${item.icon}" alt="" />${item.value}
    </span>`;
  }).join("");
}

function applyPinData(pinItem, data, type) {
  const nameEl = pinItem.querySelector(".pin-item-name");
  const countsEl = pinItem.querySelector(".pin-item-counts");
  const name = getPinName(data, type);
  if (name && nameEl) {
    nameEl.textContent = name;
    pinItem.title = name;
  }
  if (!countsEl) return;
  if (type === "project" && data) {
    countsEl.innerHTML = buildProjectPinCounts(data);
    countsEl.hidden = false;
  } else {
    countsEl.replaceChildren();
    countsEl.hidden = true;
  }
}

async function hydratePinItem(pinItem, pin) {
  const data = await fetchPinData(Number(pin.id), pin.type);
  if (!data || !pinItem.isConnected) return;
  if (pinItem.dataset.id !== String(pin.id) || pinItem.dataset.type !== pin.type) return;
  applyPinData(pinItem, data, pin.type);
}

async function fetchPinData(id, type) {
  const key = `${type}_${id}`;
  if (tooltipDataCache[key]) return tooltipDataCache[key];
  try {
    const res = await fetch(`${API}/${type === "clip" ? "clips" : type === "note" ? "notes" : "projects"}/${id}`);
    if (!res.ok) return null;
    const data = await res.json();
    // Fetch additional linked data for projects
    if (type === "project") {
      const [clips, tasks, notes] = await Promise.all([
        fetch(`${API}/clips?project_id=${id}`).then((r) => r.ok ? r.json() : []),
        fetch(`${API}/tasks?project_id=${id}`).then((r) => r.ok ? r.json() : []),
        fetch(`${API}/notes?project_id=${id}`).then((r) => r.ok ? r.json() : []),
      ]);
      data._clips = clips;
      data._tasks = tasks;
      data._notes = notes;
    }
    tooltipDataCache[key] = data;
    return data;
  } catch { return null; }
}

function showTooltip(pinItem, id, type) {
  hideTooltip();
  const gen = ++tooltipGen;
  tooltipTimer = setTimeout(async () => {
    const data = await fetchPinData(id, type);
    if (!data || gen !== tooltipGen) return;
    const rect = pinItem.getBoundingClientRect();
    tooltipEl = document.createElement("div");
    tooltipEl.className = `pin-tooltip pin-tooltip-${type}`;
    tooltipEl.innerHTML = buildTooltipHtml(data, type);
    document.body.appendChild(tooltipEl);
    const tRect = tooltipEl.getBoundingClientRect();
    let left = rect.right + 10;
    let top = rect.top;
    if (left + tRect.width > window.innerWidth - 10) left = rect.left - tRect.width - 10;
    if (top + tRect.height > window.innerHeight - 10) top = window.innerHeight - tRect.height - 10;
    if (top < 10) top = 10;
    if (gen !== tooltipGen) { tooltipEl.remove(); tooltipEl = null; return; }
    tooltipEl.style.left = left + "px";
    tooltipEl.style.top = top + "px";
    tooltipEl.style.opacity = "1";
  }, 0);
}

// ---- Settings & Tooltip global handlers ----

function hideTooltip() {
  clearTimeout(tooltipTimer);
  ++tooltipGen;
  if (tooltipEl) { tooltipEl.remove(); tooltipEl = null; }
}

// Hide tooltip on any click outside tooltip/pin
document.addEventListener("click", () => hideTooltip());
// Hide tooltip when tab becomes hidden
document.addEventListener("visibilitychange", () => {
  if (document.hidden) hideTooltip();
});

function buildTooltipHtml(data, type) {
  if (type === "clip") {
    const img = data.thumbnail_url
      ? `<img class="pin-tooltip-thumb" src="${escapeAttr(data.thumbnail_url)}" alt="" />`
      : `<div class="pin-tooltip-ph">🖼</div>`;
    const tags = (data.tags || []).map((t) =>
      `<span class="pin-tag">${escapeHtml(t.name)}</span>`
    ).join("");
    return `
      ${img}
      <div class="pin-tooltip-title">${escapeHtml(data.title || "(無題)")}</div>
      ${data.comment ? `<div class="pin-tooltip-line">${escapeHtml(data.comment)}</div>` : ""}
      <div class="pin-tooltip-tags">${tags}</div>`;
  }
  if (type === "note") {
    let extra = "";
    if (data.project_id) {
      extra += `<div class="pin-tooltip-line">📎 プロジェクト: ID ${data.project_id}</div>`;
    }
    if (data.task) {
      extra += `<div class="pin-tooltip-line">📋 タスク: ${escapeHtml(data.task.title)}</div>`;
    }
    if (data.clips && data.clips.length) {
      extra += `<div class="pin-tooltip-line">🔗 クリップ: ${data.clips.length}件</div>`;
    }
    const bodyPreview = data.body
      ? data.body.slice(0, 120) + (data.body.length > 120 ? "…" : "")
      : "";
    return `
      <div class="pin-tooltip-icon">📝</div>
      <div class="pin-tooltip-title">${escapeHtml(data.title || "(無題)")}</div>
      ${bodyPreview ? `<div class="pin-tooltip-body">${escapeHtml(bodyPreview)}</div>` : ""}
      ${extra}`;
  }
  if (type === "project") {
    const clips = data._clips || [];
    const tasks = data._tasks || [];
    const notes = data._notes || [];
    const total = clips.length + tasks.length + notes.length;
    let previewItems = "";
    let count = 0;
    for (const c of clips) {
      if (count >= 3) break;
      previewItems += `<div class="pin-tooltip-preview-item">🔗 ${escapeHtml(c.title || c.url || "(クリップ)")}</div>`;
      count++;
    }
    for (const n of notes) {
      if (count >= 3) break;
      previewItems += `<div class="pin-tooltip-preview-item">📝 ${escapeHtml(n.title || "(メモ)")}</div>`;
      count++;
    }
    for (const t of tasks) {
      if (count >= 3) break;
      previewItems += `<div class="pin-tooltip-preview-item">📋 ${escapeHtml(t.title)}</div>`;
      count++;
    }
    return `
      <div class="pin-tooltip-icon">📊</div>
      <div class="pin-tooltip-title">${escapeHtml(data.name || "(無題)")}</div>
      ${data.description ? `<div class="pin-tooltip-line">${escapeHtml(data.description)}</div>` : ""}
      <div class="pin-tooltip-counts">クリップ ${clips.length} / タスク ${tasks.length} / メモ ${notes.length}</div>
      <div class="pin-tooltip-previews">${previewItems}</div>`;
  }
  return "";
}

// ---- Context menu ----

let ctxMenuEl = null;

function hideCtxMenu() {
  if (ctxMenuEl) { ctxMenuEl.remove(); ctxMenuEl = null; }
}

function showPinContextMenu(x, y, id, type) {
  hideCtxMenu();
  ctxMenuEl = document.createElement("div");
  ctxMenuEl.className = "pin-ctx-menu";
  ctxMenuEl.innerHTML = `<button class="pin-ctx-item" data-id="${id}" data-type="${type}">ピン止めを解除</button>`;
  document.body.appendChild(ctxMenuEl);
  // Position
  const rect = ctxMenuEl.getBoundingClientRect();
  let left = x, top = y;
  if (left + rect.width > window.innerWidth - 4) left = window.innerWidth - rect.width - 4;
  if (top + rect.height > window.innerHeight - 4) top = window.innerHeight - rect.height - 4;
  ctxMenuEl.style.left = left + "px";
  ctxMenuEl.style.top = top + "px";
  ctxMenuEl.style.opacity = "1";
  // Remove action
  ctxMenuEl.querySelector(".pin-ctx-item").addEventListener("click", () => {
    removePin(id, type);
    syncPinButtonStates();
    hideCtxMenu();
    renderSidebarPins();
    notifyPinChange();
  });
  // Close on outside click
  setTimeout(() => document.addEventListener("click", hideCtxMenu, { once: true }), 0);
}

async function openPinClip(id) {
  try {
    const data = await fetchPinData(id, "clip");
    if (!data) { location.href = "/Home"; return; }
    const url = data.url || "";
    if (url.startsWith("local://")) {
      await fetch(`${API}/clips/${id}/open`, { method: "POST" });
    } else if (url) {
      window.open(url, "_blank", "noopener");
    } else {
      location.href = "/Home";
    }
  } catch {
    location.href = "/Home";
  }
}

function renderSidebarPins() {
  hideTooltip();
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;
  let section = sidebar.querySelector(".pins-section");
  if (!section) {
    section = document.createElement("div");
    section.className = "pins-section";
    const spacer = sidebar.querySelector(".side-spacer");
    if (spacer) spacer.before(section);
    else sidebar.appendChild(section);
  }
  const pins = getPins();
  if (!pins.length) {
    section.innerHTML = "";
    section.style.display = "none";
    return;
  }
  section.style.display = "";
  section.innerHTML = pins.map((p, i) =>
    `<div class="pin-item${i === 0 ? " pin-first" : ""}" draggable="true"
       data-id="${p.id}" data-type="${p.type}" data-order="${i}"
       title="${getPinLabel(p.type)} #${p.id}">
      <img class="icon icon-pin" src="${getPinIcon(p.type)}" alt="${getPinLabel(p.type)}" />
      <span class="pin-item-name">${getPinLabel(p.type)}</span>
      <span class="pin-item-counts" hidden></span>
    </div>`
  ).join("");
  // Attach events
  let dragJustStarted = false;
  section.querySelectorAll(".pin-item").forEach((el) => {
    const pin = { id: Number(el.dataset.id), type: el.dataset.type };
    void hydratePinItem(el, pin);
    el.addEventListener("dragstart", (e) => { dragJustStarted = true; onPinDragStart.call(el, e); });
    el.addEventListener("dragenter", onPinDragEnter);
    el.addEventListener("dragover", onPinDragOver);
    el.addEventListener("drop", onPinDrop);
    el.addEventListener("dragend", (e) => { dragJustStarted = false; onPinDragEnd.call(el, e); });
    el.addEventListener("mouseenter", () => {
      const id = Number(el.dataset.id);
      const type = el.dataset.type;
      showTooltip(el, id, type);
    });
    el.addEventListener("mouseleave", hideTooltip);
    el.addEventListener("click", (e) => {
      if (dragJustStarted) { dragJustStarted = false; return; }
      const id = Number(el.dataset.id);
      const type = el.dataset.type;
      hideTooltip();
      if (type === "clip") openPinClip(id);
      else if (type === "note") location.href = `/Note?id=${id}`;
      else if (type === "project") location.href = `/Projects?id=${id}`;
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      hideTooltip();
      showPinContextMenu(e.clientX, e.clientY, Number(el.dataset.id), el.dataset.type);
    });
  });
}

// ---- Drag Reorder ----

let dragSrcEl = null;
let pinDropTargetEl = null;
let pinDropBefore = false;

function clearPinDropPosition() {
  document.querySelectorAll(".pin-drop-before, .pin-drop-after, .pin-over").forEach((el) => {
    el.classList.remove("pin-drop-before", "pin-drop-after", "pin-over");
  });
  pinDropTargetEl = null;
  pinDropBefore = false;
}

function setPinDropPosition(target, event) {
  if (target === dragSrcEl) {
    clearPinDropPosition();
    return;
  }
  const rect = target.getBoundingClientRect();
  const before = event.clientY < rect.top + rect.height / 2;
  if (pinDropTargetEl === target && pinDropBefore === before) return;
  clearPinDropPosition();
  target.classList.add(before ? "pin-drop-before" : "pin-drop-after");
  pinDropTargetEl = target;
  pinDropBefore = before;
}

function onPinDragStart(e) {
  clearPinDropPosition();
  dragSrcEl = this;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", "");
  this.classList.add("pin-dragging");
}

function onPinDragEnter(e) {
  e.preventDefault();
  setPinDropPosition(this, e);
}

function onPinDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  setPinDropPosition(this, e);
}

function onPinDrop(e) {
  e.preventDefault();
  const target = pinDropTargetEl === this ? pinDropTargetEl : this;
  const before = pinDropTargetEl === this
    ? pinDropBefore
    : e.clientY < this.getBoundingClientRect().top + this.getBoundingClientRect().height / 2;
  clearPinDropPosition();
  if (target === dragSrcEl || !dragSrcEl) return;
  const pins = getPins();
  const fromIdx = pins.findIndex((p) =>
    p.id === Number(dragSrcEl.dataset.id) && p.type === dragSrcEl.dataset.type
  );
  const toIdx = pins.findIndex((p) =>
    p.id === Number(target.dataset.id) && p.type === target.dataset.type
  );
  if (fromIdx === -1 || toIdx === -1) return;
  const [moved] = pins.splice(fromIdx, 1);
  const insertIdx = toIdx + (before ? 0 : 1);
  pins.splice(fromIdx < insertIdx ? insertIdx - 1 : insertIdx, 0, moved);
  pins.forEach((p, i) => (p.order = i));
  savePins(pins);
  renderSidebarPins();
  notifyPinChange();
}

function onPinDragEnd() {
  this.classList.remove("pin-dragging");
  clearPinDropPosition();
  dragSrcEl = null;
}

// ---- Cross-page sync ----

function notifyPinChange() {
  // Bump a timestamp to trigger storage event in other tabs
  localStorage.setItem("pins_ts", Date.now().toString());
}

window.addEventListener("storage", (e) => {
  if (e.key === "pins" || e.key === "pins_ts") {
    renderSidebarPins();
  }
});

// ---- Shared Settings ----

function loadSettingsValues() {
  const acn = document.getElementById("autoCreateNote");
  if (acn) acn.checked = localStorage.getItem("autoCreateNoteOnTask") === "true";
  const htp = document.getElementById("highlightTopPriority");
  if (htp) htp.checked = localStorage.getItem("highlightTopPriority") === "true";
  const tad = document.getElementById("taskAutoDelete");
  if (tad && !tad.dataset.loaded) {
    tad.dataset.loaded = "1";
    fetch(`${API_ROOT}/settings/task_auto_delete`)
      .then((r) => r.ok ? r.json() : { value: "1w" })
      .then((d) => { tad.value = d.value || "1w"; })
      .catch(() => { tad.value = "1w"; });
  }
  const fsm = document.getElementById("fileSaveMethod");
  if (fsm && !fsm.dataset.loaded) {
    fsm.dataset.loaded = "1";
    fetch(`${API_ROOT}/settings/file_save_method`)
      .then((r) => r.ok ? r.json() : { value: "copy" })
      .then((d) => { fsm.value = d.value || "copy"; updateFileSaveDesc?.(fsm.value); })
      .catch(() => {});
  }
  loadAIExportSettings();
}

function updateFileSaveDesc(v) {
  const desc = document.getElementById("fileSaveMethodDesc");
  if (!desc) return;
  desc.textContent = v === "copy"
    ? "リンク切れの心配はありませんが、その分データ容量が増えます。"
    : "アップロードしたファイルの場所をそのまま参照します。";
}
function updateAIExportStatus(data) {
  const pathEl = document.getElementById("aiExportDesc");
  const statusEl = document.getElementById("aiExportStatus");
  if (pathEl) pathEl.textContent = data?.path
    ? `保存先: ${data.path}`
    : "保存先を確認できません。";
  if (!statusEl) return;
  if (data?.last_error) statusEl.textContent = "更新に失敗しました。次回保存時に再試行します。";
  else if (data?.enabled === false) statusEl.textContent = "自動更新はオフです。";
  else if (data?.last_exported_at) statusEl.textContent = `最終更新: ${data.last_exported_at}`;
  else statusEl.textContent = "まだ生成されていません。";
}

async function loadAIExportSettings() {
  const toggle = document.getElementById("aiExportEnabled");
  if (!toggle) return;
  try {
    const [settingRes, statusRes] = await Promise.all([
      fetch(`${API_ROOT}/settings/ai_export_enabled`),
      fetch(`${API_ROOT}/data/ai-export/status`),
    ]);
    if (settingRes.ok) {
      const setting = await settingRes.json();
      toggle.checked = setting.value !== "0";
    }
    if (statusRes.ok) updateAIExportStatus(await statusRes.json());
  } catch {
    const statusEl = document.getElementById("aiExportStatus");
    if (statusEl) statusEl.textContent = "状態を確認できません。";
  }
}

function initSettings() {
  // autoCreateNote
  const acn = document.getElementById("autoCreateNote");
  if (acn) acn.addEventListener("change", () => {
    localStorage.setItem("autoCreateNoteOnTask", acn.checked ? "true" : "false");
  });
  // highlightTopPriority
  const htp = document.getElementById("highlightTopPriority");
  if (htp) htp.addEventListener("change", () => {
    localStorage.setItem("highlightTopPriority", htp.checked ? "true" : "false");
    // Notify page-specific code to re-render
    document.dispatchEvent(new Event("highlightSettingChanged"));
  });
  // taskAutoDelete
  const tad = document.getElementById("taskAutoDelete");
  if (tad) tad.addEventListener("change", () => {
    fetch(`${API_ROOT}/settings/task_auto_delete`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: tad.value }),
    }).then((r) => {
      if (r.ok) fetch(`${API_ROOT}/maintenance/cleanup`, { method: "POST" });
    }).catch(() => alert("自動削除設定の保存に失敗しました。"));
  });
  // fileSaveMethod
  const fsm = document.getElementById("fileSaveMethod");
  if (fsm) fsm.addEventListener("change", () => {
    fetch(`${API_ROOT}/settings/file_save_method`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: fsm.value }),
    });
    if (typeof updateFileSaveDesc === "function") updateFileSaveDesc(fsm.value);
  });
// AI-friendly Markdown export
  const aiToggle = document.getElementById("aiExportEnabled");
  const aiNow = document.getElementById("aiExportNow");
  const aiOpen = document.getElementById("aiExportOpen");
  const aiApi = API_ROOT;
  if (aiToggle) aiToggle.addEventListener("change", async () => {
    const next = aiToggle.checked;
    try {
      const res = await fetch(`${aiApi}/settings/ai_export_enabled`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: next ? "1" : "0" }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      loadAIExportSettings();
    } catch {
      aiToggle.checked = !next;
      alert("AI向けMarkdownの設定を保存できませんでした。");
    }
  });
  if (aiNow) aiNow.addEventListener("click", async () => {
    const original = aiNow.textContent;
    aiNow.disabled = true;
    aiNow.textContent = "更新中…";
    try {
      const res = await fetch(`${aiApi}/data/ai-export`, { method: "POST", headers: { Accept: "application/json" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      updateAIExportStatus(data);
    } catch (e) {
      const statusEl = document.getElementById("aiExportStatus");
      if (statusEl) statusEl.textContent = "更新に失敗しました。";
      alert(`AI向けMarkdownを更新できませんでした。${e.message ? `\n${e.message}` : ""}`);
    } finally {
      aiNow.disabled = false;
      aiNow.textContent = original;
    }
  });
  if (aiOpen) aiOpen.addEventListener("click", async () => {
    try {
      const res = await fetch(`${aiApi}/data/ai-export/open`, { method: "POST", headers: { Accept: "application/json" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      updateAIExportStatus(data);
    } catch (e) {
      alert(`エクスポートフォルダを開けませんでした。${e.message ? `\n${e.message}` : ""}`);
    }
  });
  // clearSearchHistory
  const csh = document.getElementById("clearSearchHistory");
  if (csh) csh.addEventListener("click", () => {
    if (!confirm("検索履歴をすべて削除しますか？")) return;
    if (typeof SearchHistory !== "undefined") SearchHistory.clear();
  });
  // settings reset button
  const sr = document.getElementById("settingsReset");
  if (sr) sr.addEventListener("click", () => {
    if (!confirm("設定をすべてデフォルトに戻しますか？\n保存したクリップ、検索履歴は保持されます。")) return;
    // localStorage settings
    localStorage.setItem("autoCreateNoteOnTask", "false");
    localStorage.setItem("highlightTopPriority", "false");
    localStorage.removeItem("hideAutoCheatsheet");
    // UI update
    const acn = document.getElementById("autoCreateNote");
    if (acn) acn.checked = false;
    const htp = document.getElementById("highlightTopPriority");
    if (htp) htp.checked = false;
    // backend settings
    const tad = document.getElementById("taskAutoDelete");
    if (tad) { tad.value = "1w";
      fetch(`${API_ROOT}/settings/task_auto_delete`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "1w" }),
      }).then((r) => { if (r.ok) fetch(`${API_ROOT}/maintenance/cleanup`, { method: "POST" }); }).catch(() => {});
    }
    const fsm = document.getElementById("fileSaveMethod");
    if (fsm) {
      fsm.value = "copy";
      fetch(`${API_ROOT}/settings/file_save_method`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "copy" }),
      });
      if (typeof updateFileSaveDesc === "function") updateFileSaveDesc("copy");
    }
const aiToggleReset = document.getElementById("aiExportEnabled");
    if (aiToggleReset) {
      aiToggleReset.checked = true;
      fetch(`${API_ROOT}/settings/ai_export_enabled`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "1" }),
      }).then(() => loadAIExportSettings()).catch(() => {});
    }
    document.dispatchEvent(new Event("highlightSettingChanged"));
  });
  // ZIP backup export / import
  const dbExport = document.getElementById("dbExportBtn");
  const dbImport = document.getElementById("dbImportBtn");
  const dbImportFile = document.getElementById("dbImportFile");
  const dbApi = API_ROOT;

  if (dbExport) dbExport.addEventListener("click", async () => {
    const original = dbExport.textContent;
    dbExport.disabled = true;
    dbExport.textContent = "保存先を選択中…";
    try {
      const res = await fetch(`${dbApi}/data/export-backup`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      let data = {};
      try { data = await res.json(); } catch {}
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      if (!data.cancelled) {
        alert(`バックアップを保存しました。\n${data.filename || "AIClipSaveApp-backup.zip"}`);
      }
    } catch (e) {
      alert(`バックアップのエクスポートに失敗しました。${e.message ? `\n${e.message}` : ""}`);
    } finally {
      dbExport.disabled = false;
      dbExport.textContent = original;
    }
  });

  if (dbImport && dbImportFile) {
    dbImport.addEventListener("click", () => dbImportFile.click());
    dbImportFile.addEventListener("change", async () => {
      const file = dbImportFile.files?.[0];
      dbImportFile.value = "";
      if (!file) return;
      if (!confirm("このZIPに含まれるclips.dbを既存データへ結合し、uploadsをアプリ内へ展開します。続行しますか？")) return;

      const original = dbImport.textContent;
      dbImport.disabled = true;
      dbImport.textContent = "展開中…";
      try {
        const form = new FormData();
        form.append("file", file, file.name || "AIClipSaveApp-backup.zip");
        const res = await fetch(`${dbApi}/data/import-backup`, {
          method: "POST",
          body: form,
          headers: { Accept: "application/json" },
        });
        let detail = "";
        try {
          const data = await res.json();
          detail = data.detail || data.message || "";
        } catch {}
        if (!res.ok) throw new Error(detail || `HTTP ${res.status}`);
        alert("バックアップをインポートしました。画面を更新します。");
        location.reload();
      } catch (e) {
        alert(`バックアップのインポートに失敗しました。${e.message ? `\n${e.message}` : ""}`);
      } finally {
        dbImport.disabled = false;
        dbImport.textContent = original;
      }
    });
  }
  // settings close button
  const sc = document.getElementById("settingsClose");
  if (sc) sc.addEventListener("click", () => {
    const m = document.getElementById("settingsModal");
    if (m) m.hidden = true;
  });
  // settings backdrop click
  const sm = document.getElementById("settingsModal");
  if (sm) sm.addEventListener("click", (e) => {
    if (e.target === sm) sm.hidden = true;
  });
}

window.openSettings = function () {
  loadSettingsValues();
  const m = document.getElementById("settingsModal");
  if (m) m.hidden = false;
};

function initPinSettings() {
  renderSidebarPins();
  initSettings();
}

// ---- Dark Theme ----

// Force the single supported appearance.
(function initTheme() {
  document.documentElement.setAttribute("data-theme", "dark");
  // 初回読み込み時のトランジションを抑止
  requestAnimationFrame(() => {
    document.documentElement.classList.add("theme-ready");
  });
})();

// ---- Init ----
document.addEventListener("DOMContentLoaded", initPinSettings);
