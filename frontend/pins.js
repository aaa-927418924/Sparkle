const API_ROOT = window.location.origin;
const PIN_KEY = "pins";
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
const tooltipDataRevisions = new Map();
let tooltipGen = 0;
let activeTooltipPin = null;

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

function getStoredPinName(pin) {
  return typeof pin?.name === "string" ? pin.name.trim() : "";
}

function rememberPinMetadata(id, type, { name = "", counts = null } = {}) {
  if (!Number.isInteger(Number(id)) || !type) return;
  const pins = getPins();
  const pin = pins.find((item) => Number(item.id) === Number(id) && item.type === type);
  if (!pin) return;
  let changed = false;
  if (name && pin.name !== name) {
    pin.name = name;
    changed = true;
  }
  if (counts && (
    pin.counts?.clips !== counts.clips ||
    pin.counts?.tasks !== counts.tasks ||
    pin.counts?.notes !== counts.notes
  )) {
    pin.counts = { clips: counts.clips, tasks: counts.tasks, notes: counts.notes };
    changed = true;
  }
  if (!changed) return;
  savePins(pins);
}

function rememberPinName(pinItem, name) {
  if (!pinItem || !name) return;
  rememberPinMetadata(Number(pinItem.dataset.id), pinItem.dataset.type, { name });
}

function rememberPinCounts(pinItem, counts) {
  if (!pinItem || !counts) return;
  rememberPinMetadata(Number(pinItem.dataset.id), pinItem.dataset.type, { counts });
}

function getProjectPinCountValues(data) {
  return {
    clips: Array.isArray(data?._clips) ? data._clips.length : 0,
    tasks: Array.isArray(data?._tasks) ? data._tasks.length : 0,
    notes: Array.isArray(data?._notes) ? data._notes.length : 0,
  };
}

function getStoredPinCounts(pin) {
  if (pin?.type !== "project" || !pin.counts) return null;
  const counts = {
    clips: Number(pin.counts.clips),
    tasks: Number(pin.counts.tasks),
    notes: Number(pin.counts.notes),
  };
  if (Object.values(counts).every((value) => Number.isInteger(value) && value >= 0)) return counts;
  return null;
}

function buildProjectPinCountsFromValues(values) {
  const counts = [
    { icon: "icons/clip.svg", label: "クリップ", value: values.clips },
    { icon: "icons/checkbox.svg", label: "タスク", value: values.tasks },
    { icon: "icons/clipboard.svg", label: "メモ", value: values.notes },
  ];
  return counts.map((item) => {
    const label = `${item.label} ${item.value}件`;
    return `<span class="pin-count" aria-label="${escapeAttr(label)}">
      <img class="icon icon-inline icon-pin-count" src="${item.icon}" alt="" />${item.value}
    </span>`;
  }).join("");
}

function buildProjectPinCounts(data) {
  return buildProjectPinCountsFromValues(getProjectPinCountValues(data));
}

function applyPinData(pinItem, data, type) {
  const nameEl = pinItem.querySelector(".pin-item-name");
  const countsEl = pinItem.querySelector(".pin-item-counts");
  const name = getPinName(data, type);
  if (name && nameEl) {
    nameEl.textContent = name;
    pinItem.setAttribute("aria-label", name);
    pinItem.removeAttribute("title");
    rememberPinName(pinItem, name);
  }
  if (!countsEl) return;
  if (type === "project" && data) {
    const countValues = getProjectPinCountValues(data);
    countsEl.innerHTML = buildProjectPinCountsFromValues(countValues);
    countsEl.hidden = false;
    rememberPinCounts(pinItem, countValues);
  } else {
    countsEl.replaceChildren();
    countsEl.hidden = true;
  }
}

async function hydratePinItem(pinItem, pin) {
  const key = `${pin.type}_${Number(pin.id)}`;
  const revision = tooltipDataRevisions.get(key) || 0;
  const data = await fetchPinData(Number(pin.id), pin.type);
  if (!data || !pinItem.isConnected) return;
  if ((tooltipDataRevisions.get(key) || 0) !== revision) return;
  if (pinItem.dataset.id !== String(pin.id) || pinItem.dataset.type !== pin.type) return;
  applyPinData(pinItem, data, pin.type);
}

async function fetchPinData(id, type) {
  const key = `${type}_${id}`;
  if (tooltipDataCache[key]) return tooltipDataCache[key];
  const revision = tooltipDataRevisions.get(key) || 0;
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
    if ((tooltipDataRevisions.get(key) || 0) === revision) {
      tooltipDataCache[key] = data;
    }
    return data;
  } catch { return null; }
}

function showTooltip(pinItem, id, type) {
  hideTooltip();
  const tooltipPin = { pinItem, id: Number(id), type };
  activeTooltipPin = tooltipPin;
  const gen = ++tooltipGen;
  tooltipTimer = setTimeout(async () => {
    const data = await fetchPinData(id, type);
    if (!data || gen !== tooltipGen || activeTooltipPin !== tooltipPin) return;
    const rect = pinItem.getBoundingClientRect();
    tooltipEl = document.createElement("div");
    tooltipEl.className = `pin-tooltip pin-tooltip-${type}`;
    tooltipEl.dataset.pinId = String(id);
    tooltipEl.dataset.pinType = type;
    tooltipEl.innerHTML = buildTooltipHtml(data, type);
    document.body.appendChild(tooltipEl);
    const tRect = tooltipEl.getBoundingClientRect();
    let left = rect.right + 10;
    let top = rect.top;
    if (left + tRect.width > window.innerWidth - 10) left = rect.left - tRect.width - 10;
    if (top + tRect.height > window.innerHeight - 10) top = window.innerHeight - tRect.height - 10;
    if (top < 10) top = 10;
    if (gen !== tooltipGen || activeTooltipPin !== tooltipPin) { tooltipEl.remove(); tooltipEl = null; return; }
    tooltipEl.style.left = left + "px";
    tooltipEl.style.top = top + "px";
    tooltipEl.style.opacity = "1";
  }, 0);
}

// ---- Settings & Tooltip global handlers ----

function hideTooltip() {
  clearTimeout(tooltipTimer);
  ++tooltipGen;
  activeTooltipPin = null;
  if (tooltipEl) { tooltipEl.remove(); tooltipEl = null; }
}

function invalidatePinData(type, id) {
  const key = `${type}_${Number(id)}`;
  const revision = (tooltipDataRevisions.get(key) || 0) + 1;
  tooltipDataRevisions.set(key, revision);
  delete tooltipDataCache[key];
  return revision;
}

// 編集・紐づけ後に、表示中のピンとホバー内容を同じページ内で即時同期する。
async function refreshPinnedData(type, id) {
  const numericId = Number(id);
  if (!type || !Number.isInteger(numericId)) return null;

  const pinItems = [...document.querySelectorAll(".pin-item")].filter((item) =>
    Number(item.dataset.id) === numericId && item.dataset.type === type
  );
  const activePin = activeTooltipPin &&
    activeTooltipPin.id === numericId && activeTooltipPin.type === type
    ? activeTooltipPin.pinItem
    : null;
  if (!pinItems.length && !activePin) return null;

  const revision = invalidatePinData(type, numericId);
  if (activePin) hideTooltip();
  const data = await fetchPinData(numericId, type);
  if (!data || (tooltipDataRevisions.get(`${type}_${numericId}`) || 0) !== revision) return data;

  pinItems.forEach((item) => {
    if (item.isConnected) applyPinData(item, data, type);
  });
  if (activePin && activePin.isConnected && activePin.matches(":hover")) {
    showTooltip(activePin, numericId, type);
  }
  return data;
}

async function refreshAllPinned(type) {
  const pins = getPins().filter((pin) => pin.type === type);
  await Promise.all(pins.map((pin) => refreshPinnedData(type, pin.id)));
}

window.refreshPinnedData = refreshPinnedData;
window.refreshAllPinned = refreshAllPinned;
window.refreshAllPinnedProjects = () => refreshAllPinned("project");

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

async function primeMissingPinMetadata(pins) {
  await Promise.all(pins.map(async (pin) => {
    const data = await fetchPinData(Number(pin.id), pin.type);
    if (!data) return;
    const name = getPinName(data, pin.type);
    const counts = pin.type === "project" ? getProjectPinCountValues(data) : null;
    rememberPinMetadata(Number(pin.id), pin.type, { name, counts });
  }));
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
  section.innerHTML = pins.map((p, i) => {
    const name = getStoredPinName(p);
    const counts = getStoredPinCounts(p);
    const countsMarkup = counts ? buildProjectPinCountsFromValues(counts) : "";
    const accessibleName = name || getPinLabel(p.type);
    return `<div class="pin-item${i === 0 ? " pin-first" : ""}" draggable="true"
       data-id="${p.id}" data-type="${p.type}" data-order="${i}"
       aria-label="${escapeAttr(accessibleName)}">
      <img class="icon icon-pin" src="${getPinIcon(p.type)}" alt="" />
      <span class="pin-item-name">${escapeHtml(name)}</span>
      <span class="pin-item-counts"${counts ? "" : " hidden"}>${countsMarkup}</span>
    </div>`;
  }).join("");
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
  const acnp = document.getElementById("autoCreateNoteOnProject");
  if (acnp) acnp.checked = localStorage.getItem("autoCreateNoteOnProject") === "true";
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
      .then((r) => r.ok ? r.json() : { value: "reference" })
      .then((d) => { fsm.value = d.value || "reference"; updateFileSaveDesc?.(fsm.value); })
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
  const enabledEl = document.getElementById("aiExportEnabled");
  if (enabledEl && typeof data?.enabled === "boolean") {
    enabledEl.checked = data.enabled;
    enabledEl.disabled = false;
  }
  if (pathEl) pathEl.textContent = data?.path
    ? `保存先: ${data.path}`
    : "保存先を確認できません。";
  if (!statusEl) return;
  if (data?.enabled === false) statusEl.textContent = "無効です。Markdownは自動生成されません。";
  else if (data?.last_error) statusEl.textContent = "更新に失敗しました。次回保存時に再試行します。";
  else if (data?.last_exported_at) statusEl.textContent = `最終更新: ${data.last_exported_at}`;
  else statusEl.textContent = "まだ生成されていません。";
}

async function loadAIExportSettings() {
  const enabledEl = document.getElementById("aiExportEnabled");
  if (enabledEl) enabledEl.disabled = true;
  try {
    const statusRes = await fetch(`${API_ROOT}/data/ai-export/status`);
    if (!statusRes.ok) throw new Error(`HTTP ${statusRes.status}`);
    updateAIExportStatus(await statusRes.json());
  } catch {
    const statusEl = document.getElementById("aiExportStatus");
    if (statusEl) statusEl.textContent = "状態を確認できません。";
    if (enabledEl) enabledEl.disabled = false;
  }
}

let settingsOperationActive = false;
let settingsOperationReturnFocus = null;
let settingsOperationGuardInstalled = false;

function getSettingsOperationLock() {
  return document.getElementById("settingsOperationLock");
}

function setSettingsOperationLockMessage(message) {
  const messageEl = document.getElementById("settingsOperationLockMessage");
  if (messageEl && message) messageEl.textContent = message;
}

function installSettingsOperationGuard() {
  if (settingsOperationGuardInstalled) return;
  settingsOperationGuardInstalled = true;

  document.addEventListener("keydown", (event) => {
    if (!settingsOperationActive) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);

  document.addEventListener("pointerdown", (event) => {
    if (!settingsOperationActive) return;
    const lock = getSettingsOperationLock();
    if (lock?.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);

  document.addEventListener("focusin", (event) => {
    if (!settingsOperationActive) return;
    const lock = getSettingsOperationLock();
    if (lock?.contains(event.target)) return;
    event.preventDefault();
    lock?.querySelector(".settings-operation-lock-card")?.focus({ preventScroll: true });
  }, true);

  window.addEventListener("beforeunload", (event) => {
    if (!settingsOperationActive) return;
    event.preventDefault();
    event.returnValue = "バックアップ処理中です。";
  });
}

function setSettingsOperationLock(active, message = "処理を実行しています…") {
  const lock = getSettingsOperationLock();
  if (!lock) return;
  installSettingsOperationGuard();

  if (active) {
    if (!settingsOperationActive) settingsOperationReturnFocus = document.activeElement;
    settingsOperationActive = true;
    setSettingsOperationLockMessage(message);
    lock.hidden = false;
    lock.setAttribute("aria-hidden", "false");
    document.body.classList.add("settings-operation-active");
    const layout = document.querySelector(".settings-page .layout");
    if (layout) layout.inert = true;
    requestAnimationFrame(() => {
      lock.querySelector(".settings-operation-lock-card")?.focus({ preventScroll: true });
    });
    return;
  }

  settingsOperationActive = false;
  document.body.classList.remove("settings-operation-active");
  const layout = document.querySelector(".settings-page .layout");
  if (layout) layout.inert = false;
  lock.hidden = true;
  lock.setAttribute("aria-hidden", "true");
  const previous = settingsOperationReturnFocus;
  settingsOperationReturnFocus = null;
  if (previous?.isConnected && typeof previous.focus === "function") {
    previous.focus({ preventScroll: true });
  }
}

function waitForSettingsOperationNotice(message, duration = 650) {
  setSettingsOperationLockMessage(message);
  return new Promise((resolve) => window.setTimeout(resolve, duration));
}

function initSettings() {
  if (getSettingsOperationLock()) installSettingsOperationGuard();
  // autoCreateNote
  const acn = document.getElementById("autoCreateNote");
  if (acn) acn.addEventListener("change", () => {
    localStorage.setItem("autoCreateNoteOnTask", acn.checked ? "true" : "false");
  });
  // autoCreateNoteOnProject
  const acnp = document.getElementById("autoCreateNoteOnProject");
  if (acnp) acnp.addEventListener("change", () => {
    localStorage.setItem("autoCreateNoteOnProject", acnp.checked ? "true" : "false");
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
  const aiEnabled = document.getElementById("aiExportEnabled");
  if (aiEnabled) aiEnabled.addEventListener("change", async () => {
    const nextValue = aiEnabled.checked;
    if (!nextValue) {
      aiEnabled.disabled = true;
      const message = "エクスポートした内容が全て削除されますが、続行しますか？\nデータ自体は保持されます。";
      const confirmed = typeof window.confirmDeletion === "function"
        ? await window.confirmDeletion(message, {
          anchor: aiEnabled,
          title: "AI向けエクスポートを無効にしますか？",
          confirmLabel: "無効にする",
        })
        : window.confirm(message);
      if (!confirmed) {
        aiEnabled.checked = true;
        aiEnabled.disabled = false;
        return;
      }
    } else {
      aiEnabled.disabled = true;
    }
    try {
      const res = await fetch(`${API_ROOT}/settings/ai_export_enabled`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ value: nextValue ? "true" : "false" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      await loadAIExportSettings();
    } catch {
      aiEnabled.checked = !nextValue;
      const statusEl = document.getElementById("aiExportStatus");
      if (statusEl) statusEl.textContent = "設定を保存できませんでした。";
    } finally {
      aiEnabled.disabled = false;
    }
  });
  const aiOpen = document.getElementById("aiExportOpen");
  const aiApi = API_ROOT;
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
  if (csh) csh.addEventListener("click", async () => {
    const message = "検索履歴をすべて削除しますか？";
    const confirmed = typeof window.confirmDeletion === "function"
      ? await window.confirmDeletion(message, {
        anchor: csh,
        title: "検索履歴を削除しますか？",
        confirmLabel: "すべて削除",
      })
      : window.confirm(message);
    if (!confirmed) return;
    if (typeof SearchHistory !== "undefined") SearchHistory.clear();
  });
  // reset profile stats
  const rps = document.getElementById("resetProfileStats");
  if (rps) rps.addEventListener("click", async () => {
    const message = "累計保存クリップ数を0にリセットしますか？\n保存済みのクリップ自体は削除されません。";
    const confirmed = typeof window.confirmDeletion === "function"
      ? await window.confirmDeletion(message, {
        anchor: rps,
        title: "統計をリセットしますか？",
        confirmLabel: "リセットする",
      })
      : window.confirm(message);
    if (!confirmed) return;
    try {
      const res = await fetch(`${API_ROOT}/profile/stats/reset`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      rps.textContent = "リセットしました";
      setTimeout(() => { rps.textContent = "リセット"; }, 1500);
    } catch {
      alert("統計のリセットに失敗しました。");
    }
  });
  // settings reset button
  const sr = document.getElementById("settingsReset");
  if (sr) sr.addEventListener("click", async () => {
    const message = "設定をすべてデフォルトに戻しますか？\n保存したクリップ、検索履歴は保持されます。";
    const confirmed = typeof window.confirmDeletion === "function"
      ? await window.confirmDeletion(message, {
        anchor: sr,
        title: "設定をリセットしますか？",
        confirmLabel: "リセットする",
      })
      : window.confirm(message);
    if (!confirmed) return;
    // localStorage settings
    localStorage.setItem("autoCreateNoteOnTask", "false");
    localStorage.setItem("autoCreateNoteOnProject", "false");
    localStorage.removeItem("hideAutoCheatsheet");
    // UI update
    const acn = document.getElementById("autoCreateNote");
    if (acn) acn.checked = false;
    const acnp = document.getElementById("autoCreateNoteOnProject");
    if (acnp) acnp.checked = false;
    const aiEnabled = document.getElementById("aiExportEnabled");
    if (aiEnabled) {
      aiEnabled.checked = true;
      aiEnabled.disabled = true;
      fetch(`${API_ROOT}/settings/ai_export_enabled`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ value: "true" }),
      }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return loadAIExportSettings();
      }).catch(() => {
        aiEnabled.disabled = false;
      });
    }
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
      fsm.value = "reference";
      fetch(`${API_ROOT}/settings/file_save_method`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "reference" }),
      });
      if (typeof updateFileSaveDesc === "function") updateFileSaveDesc("reference");
    }
  });
  // ZIP backup export / import
  const dbExport = document.getElementById("dbExportBtn");
  const dbImport = document.getElementById("dbImportBtn");
  const dbImportFile = document.getElementById("dbImportFile");
  const dbApi = API_ROOT;
  const BROWSER_SETTINGS_KEYS = [
    "clipSortMode",
    "autoCreateNoteOnTask",
    "autoCreateNoteOnProject",
    "hideAutoCheatsheet",
    "clipSearchHistory",
    "pins",
  ];

  function collectBrowserSettings() {
    const out = {};
    for (const key of BROWSER_SETTINGS_KEYS) {
      try {
        const value = localStorage.getItem(key);
        if (value !== null) out[key] = value;
      } catch (e) {}
    }
    return out;
  }

  function applyBrowserSettings(settings) {
    const browser = settings && typeof settings === "object" ? settings.browser : null;
    if (!browser) return;
    for (const [key, value] of Object.entries(browser)) {
      try {
        localStorage.setItem(key, value);
      } catch (e) {}
    }
  }

  if (dbExport) dbExport.addEventListener("click", async () => {
    if (settingsOperationActive) return;
    const original = dbExport.textContent;
    const originalImport = dbImport?.textContent;
    setSettingsOperationLock(true, "保存先を選択しています…");
    dbExport.disabled = true;
    if (dbImport) dbImport.disabled = true;
    if (dbImportFile) dbImportFile.disabled = true;
    dbExport.textContent = "エクスポート中…";
    try {
      const res = await fetch(`${dbApi}/data/export-backup`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ browser_settings: collectBrowserSettings() }),
      });
      let data = {};
      try { data = await res.json(); } catch {}
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      if (data.cancelled) {
        await waitForSettingsOperationNotice("保存先の選択をキャンセルしました。", 350);
      } else {
        await waitForSettingsOperationNotice(`バックアップを保存しました。${data.filename || "Sparkle-backup.zip"}`, 750);
      }
    } catch (e) {
      await waitForSettingsOperationNotice(`エクスポートに失敗しました。${e.message || "もう一度お試しください。"}`, 1200);
    } finally {
      setSettingsOperationLock(false);
      dbExport.disabled = false;
      if (dbImport) {
        dbImport.disabled = false;
        if (originalImport) dbImport.textContent = originalImport;
      }
      if (dbImportFile) dbImportFile.disabled = false;
      dbExport.textContent = original;
    }
  });

  if (dbImport && dbImportFile) {
    dbImport.addEventListener("click", () => {
      if (settingsOperationActive) return;
      dbImportFile.click();
    });
    dbImportFile.addEventListener("change", async () => {
      const file = dbImportFile.files?.[0];
      dbImportFile.value = "";
      if (!file) return;
      const importMessage = "このZIPのclips.dbを既存データへ結合し、uploadsと設定・プロフィール情報を復元します。";
      const confirmed = typeof window.confirmDeletion === "function"
        ? await window.confirmDeletion(importMessage, {
          anchor: dbImport,
          title: "バックアップをインポートしますか？",
          confirmLabel: "インポートする",
        })
        : window.confirm(`${importMessage}\n続行しますか？`);
      if (!confirmed) return;

      const original = dbImport.textContent;
      const originalExport = dbExport?.textContent;
      setSettingsOperationLock(true, "バックアップをインポートしています…");
      dbImport.disabled = true;
      if (dbExport) dbExport.disabled = true;
      dbImportFile.disabled = true;
      dbImport.textContent = "展開中…";
      try {
        const form = new FormData();
        form.append("file", file, file.name || "Sparkle-backup.zip");
        const res = await fetch(`${dbApi}/data/import-backup`, {
          method: "POST",
          body: form,
          headers: { Accept: "application/json" },
        });
        let detail = "";
        let data = null;
        try {
          data = await res.json();
          detail = data.detail || data.message || "";
        } catch {}
        if (!res.ok) throw new Error(detail || `HTTP ${res.status}`);
        if (data) applyBrowserSettings(data.settings);
        await waitForSettingsOperationNotice("バックアップをインポートしました。画面を更新します…", 350);
        setSettingsOperationLock(false);
        location.reload();
      } catch (e) {
        await waitForSettingsOperationNotice(`インポートに失敗しました。${e.message || "もう一度お試しください。"}`, 1200);
      } finally {
        setSettingsOperationLock(false);
        dbImport.disabled = false;
        if (dbExport) {
          dbExport.disabled = false;
          if (originalExport) dbExport.textContent = originalExport;
        }
        dbImportFile.disabled = false;
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
  if (/\/settings\/?$/i.test(window.location.pathname)) return;
  window.location.href = "/Settings";
};

async function initPinSettings() {
  const pins = getPins();
  const missingMetadata = pins.filter((pin) =>
    !getStoredPinName(pin) || (pin.type === "project" && !getStoredPinCounts(pin))
  );
  if (missingMetadata.length) await primeMissingPinMetadata(missingMetadata);
  renderSidebarPins();
  initSettings();
  initProfileSidebar();
  if (document.body?.classList.contains("settings-page")) loadSettingsValues();
}

function initProfileSidebar() {
  const avatar = document.getElementById("profileAvatar");
  if (!avatar) return;
  fetch(`${API_ROOT}/profile`)
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (!data || !avatar.isConnected) return;
      if (data.icon_url) avatar.src = data.icon_url;
      const name = (data.username || "ユーザー").trim();
      const span = document.getElementById("sidebarUsername");
      if (span) span.textContent = name.length > 15 ? name.slice(0, 15) + "…" : name;
    })
    .catch(() => {});
}
window.initProfileSidebar = initProfileSidebar;

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
