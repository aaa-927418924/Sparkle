const API = window.location.origin;
const AUTO_KEY = "autoCreateNoteOnTask";
const HIGHLIGHT_KEY = "highlightTopPriority";

const state = {
  tasks: [],
  notes: [],
  status: "active", // "all" | "active" | "done"
  selected: new Map(), // Map<id, "task" | "note">
  dragOccurred: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  taskList: $("taskList"),
  taskEmpty: $("taskEmpty"),
  taskAdd: $("taskAdd"),
  taskInput: $("taskInput"),
  memoGrid: $("memoGrid"),
  memoEmpty: $("memoEmpty"),
  newNote: $("newNote"),
  statusTabs: $("statusTabs"),
  linkModal: $("linkModal"),
  linkSearch: $("linkSearch"),
  linkList: $("linkList"),
  linkCancel: $("linkCancel"),
  linkSave: $("linkSave"),
  taskEditModal: $("taskEditModal"),
  taskEditTitle: $("taskEditTitle"),
  taskEditDue: $("taskEditDue"),
  taskEditStars: $("taskEditStars"),
  taskEditCancel: $("taskEditCancel"),
  taskEditSave: $("taskEditSave"),
  batchBar: $("batchBar"),
  batchCount: $("batchCount"),
  batchDelBtn: $("batchDelBtn"),
};

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[m]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}

function truncate(str, max) {
  if (!str) return "";
  return str.length > max ? str.slice(0, max) + "窶ｦ" : str;
}

function linkifyText(raw) {
  if (!raw) return "";
  const urlRe = /(https?:\/\/[^\s<>"']+)/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = urlRe.exec(raw))) {
    out += escapeHtml(raw.slice(last, m.index));
    const url = m[0];
    out += `<a href="${escapeAttr(url)}" target="_blank" rel="noopener" class="body-link">${escapeHtml(url)}</a>`;
    last = m.index + url.length;
  }
  out += escapeHtml(raw.slice(last));
  return out;
}

// --- 繝倥Ν繝代・: 邏舌▼縺榊愛螳・---
function noteTaskIds(note) {
  const ids = Array.isArray(note.task_ids) && note.task_ids.length
    ? note.task_ids
    : (note.task_id != null ? [note.task_id] : []);
  return [...new Set(ids.map(Number).filter(Number.isInteger))];
}

function noteTask(note) {
  const taskId = noteTaskIds(note)[0];
  if (taskId == null) return null;
  return state.tasks.find((t) => t.id === taskId) || null;
}
function taskNotes(taskId) {
  return state.notes.filter((n) => noteTaskIds(n).includes(Number(taskId)));
}

// --- 繝倥Ν繝代・: 譛滄剞繝ｻ蜆ｪ蜈亥ｺｦ ---
function formatDue(dateStr) {
  // "YYYY-MM-DD" -> "M/D"
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr || "");
  if (!m) return dateStr || "";
  return `${Number(m[2])}/${Number(m[3])}`;
}

function isOverdue(dateStr) {
  if (!dateStr) return false;
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return dateStr < todayStr;
}

function priorityStars(priority) {
  // priority: 1縲・ -> "笘・・笘・・笘・
  const p = Math.max(0, Math.min(5, priority || 0));
  return "★".repeat(p) + "☆".repeat(5 - p);
}

// 騾ｲ陦御ｸｭ繧ｿ繧ｹ繧ｯ縺ｮ荳ｭ縺ｧ priority 縺梧怙螟ｧ縺ｮ繧ゅ・縺ｮ id 髮・粋繧定ｿ斐☆(蜷檎紫縺ｯ蜈ｨ縺ｦ)
function topPriorityIds() {
  let max = null;
  for (const t of state.tasks) {
    if (t.is_done || t.priority == null) continue;
    if (max === null || t.priority > max) max = t.priority;
  }
  if (max === null) return new Set();
  return new Set(
    state.tasks
      .filter((t) => !t.is_done && t.priority === max)
      .map((t) => t.id)
  );
}

// --- 繧ｹ繝・・繧ｿ繧ｹ繧ｿ繝・---
const STATUS_TABS = [
  { key: "all", label: "すべて" },
  { key: "active", label: "進行中" },
  { key: "done", label: "完了済み" },
];

function renderStatusTabs() {
  els.statusTabs.innerHTML = STATUS_TABS.map(
    (t) =>
      `<button class="cat-btn${state.status === t.key ? " active" : ""}" data-status="${t.key}">${t.label}</button>`
  ).join("");
  els.statusTabs.querySelectorAll(".cat-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.status = btn.dataset.status;
      renderStatusTabs();
      renderTasks();
      renderNotes();
    });
  });
}

function taskMatchesStatus(t) {
  if (state.status === "all") return true;
  if (state.status === "active") return !t.is_done;
  return t.is_done; // done
}
function noteMatchesStatus(n) {
  if (state.status === "all") return true;
  const task = noteTask(n);
  if (state.status === "active") return !task || !task.is_done;
  return !!(task && task.is_done); // done
}

// --- 繝・・繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ ---
async function loadAll() {
  const [tasks, notes] = await Promise.all([api("/tasks"), api("/notes")]);
  state.tasks = tasks;
  state.notes = notes;
  renderStatusTabs();
  renderTasks();
  renderNotes();
}

// --- 繧ｿ繧ｹ繧ｯ ---
function renderTasks() {
  const list = state.tasks
    .filter(taskMatchesStatus)
    .sort((a, b) => {
      const aPriority = a.priority == null ? -1 : Number(a.priority) || 0;
      const bPriority = b.priority == null ? -1 : Number(b.priority) || 0;
      return bPriority - aPriority;
    });
  els.taskEmpty.hidden = list.length > 0;

  const highlightOn = localStorage.getItem(HIGHLIGHT_KEY) === "true";
  const topIds = highlightOn ? topPriorityIds() : new Set();

  els.taskList.innerHTML = list
    .map((t) => {
      const done = t.is_done ? " done" : "";
      const top = topIds.has(t.id) ? " top-priority" : "";
      const clip = t.clip
          ? `<div class="task-clip" data-url="${escapeAttr(t.clip.url)}" title="クリップを開く"><img class="icon icon-inline" src="icons/clip.svg" alt="" /> ${escapeHtml(t.clip.title || "")}</div>`
        : "";
      const linked = taskNotes(t.id)
        .map(
          (n) =>
            `<div class="task-note" data-note="${n.id}" title="メモを開く"><img class="icon icon-inline" src="icons/memo.svg" alt="" /> ${escapeHtml(n.title)}</div>`
        )
        .join("");
      const prio =
        t.priority != null
          ? `<div class="task-priority" title="優先度 ${t.priority}">${priorityStars(t.priority)}</div>`
          : "";
      const due =
        t.due_date
          ? `<div class="task-due${isOverdue(t.due_date) && !t.is_done ? " overdue" : ""}"><img class="icon icon-inline" src="icons/calendar.svg" alt="" /> ${escapeHtml(formatDue(t.due_date))}</div>`
          : "";
      return `
        <li class="task-item${done}${top}" data-id="${t.id}">
          <div class="task-lead">
            <label class="task-check">
              <input type="checkbox" data-toggle="${t.id}" aria-label="${escapeHtml(t.title)}の完了状態を切り替え" ${t.is_done ? "checked" : ""} />
            </label>
          </div>
          <div class="task-body">
            <div class="task-title">${escapeHtml(t.title)}</div>
            ${prio}
            ${due}
            ${clip}
            ${linked ? `<div class="task-notes">${linked}</div>` : ""}
          </div>
          <div class="task-actions">
            <button class="task-link" data-link="${t.id}" title="メモを紐付け"><img class="icon icon-btn" src="icons/clip.svg" alt="紐付け" /></button>
            <button class="task-edit" data-edit="${t.id}" title="編集"><img class="icon icon-btn" src="icons/pencil.svg" alt="編集" /></button>
            <button class="task-del" data-del="${t.id}" title="削除"><img class="icon icon-btn" src="icons/trash.svg" alt="削除" /></button>
          </div>
        </li>`;
    })
    .join("");

  els.taskList.querySelectorAll("[data-toggle]").forEach((cb) => {
    cb.addEventListener("change", () => toggleTask(Number(cb.dataset.toggle), cb));
  });
  els.taskList.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openTaskEditModal(Number(btn.dataset.edit));
    });
  });
  els.taskList.querySelectorAll(".task-clip").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const url = el.dataset.url;
      if (url) window.open(url, "_blank", "noopener");
    });
  });
  els.taskList.querySelectorAll(".task-note").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      location.href = `/Note?id=${el.dataset.note}`;
    });
  });
  els.taskList.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteTask(Number(btn.dataset.del));
    });
  });
  els.taskList.querySelectorAll("[data-link]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openLinkModal(Number(btn.dataset.link));
    });
  });
}

async function toggleTask(id, cb) {
  const task = state.tasks.find((t) => t.id === id);
  const optimistic = !task.is_done;
  task.is_done = optimistic; // 讌ｽ隕ｳ逧・峩譁ｰ
  try {
    const updated = await api(`/tasks/${id}/toggle`, { method: "PATCH" });
    task.is_done = updated.is_done;
    // 繝輔ぅ繝ｫ繧ｿ蜀埼←逕ｨ(螳御ｺ・ｸ医∩縺ｫ遘ｻ蜍輔☆繧狗ｭ・
    renderTasks();
    renderNotes();
  } catch (e) {
    task.is_done = !optimistic;
    alert("更新に失敗しました。");
  }
}

async function deleteTask(id) {
  if (!confirm("このタスクを削除しますか？")) return;
  try {
    await api(`/tasks/${id}`, { method: "DELETE" });
    state.tasks = state.tasks.filter((t) => t.id !== id);
    renderTasks();
    renderNotes();
  } catch (e) {
    alert("削除に失敗しました。");
  }
}

// --- 繧ｿ繧ｹ繧ｯ邱ｨ髮・Δ繝ｼ繝繝ｫ ---
let taskEditTargetId = null;
let taskEditPriority = null; // null = 譛ｪ險ｭ螳・ 1縲・

function renderStarPicker() {
  const stars = [1, 2, 3, 4, 5]
    .map((n) => {
      const on = taskEditPriority != null && n <= taskEditPriority;
      return `<button type="button" class="star ${on ? " on" : ""}" data-star="${n}">${on ? "★" : "☆"}</button>`;
    })
    .join("");
  const clear =
    taskEditPriority != null
      ? `<button type="button" class="star-clear" data-star="0" title="優先度をクリア">クリア</button>`
      : "";
  els.taskEditStars.innerHTML = stars + clear;
  els.taskEditStars.querySelectorAll("[data-star]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = Number(btn.dataset.star);
      if (v === 0) {
        taskEditPriority = null;
      } else if (taskEditPriority === v) {
        // 蜷後§譏溘ｒ蜀阪け繝ｪ繝・け縺ｧ譛ｪ險ｭ螳壹↓謌ｻ縺・        taskEditPriority = null;
      } else {
        taskEditPriority = v;
      }
      renderStarPicker();
    });
  });
}

function openTaskEditModal(id) {
  const task = state.tasks.find((t) => t.id === id);
  if (!task) return;
  taskEditTargetId = id;
  els.taskEditTitle.value = task.title || "";
  els.taskEditDue.value = task.due_date || "";
  taskEditPriority = task.priority != null ? task.priority : null;
  renderStarPicker();
  els.taskEditModal.hidden = false;
}

function closeTaskEditModal() {
  els.taskEditModal.hidden = true;
  taskEditTargetId = null;
}

els.taskEditCancel.addEventListener("click", closeTaskEditModal);
els.taskEditModal.addEventListener("click", (e) => {
  if (e.target === els.taskEditModal) closeTaskEditModal();
});

els.taskEditSave.addEventListener("click", async () => {
  if (taskEditTargetId == null) return;
  const title = els.taskEditTitle.value.trim();
  if (!title) {
    alert("タイトルを入力してください。");
    return;
  }
  const payload = {
    title,
    due_date: els.taskEditDue.value || null,
    priority: taskEditPriority,
  };
  try {
    const updated = await api(`/tasks/${taskEditTargetId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const idx = state.tasks.findIndex((t) => t.id === updated.id);
    if (idx >= 0) state.tasks[idx] = updated;
    closeTaskEditModal();
    renderTasks();
    renderNotes();
  } catch (e) {
    alert("更新に失敗しました。");
  }
});

els.taskAdd.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = els.taskInput.value.trim();
  if (!title) return;
  try {
    const created = await api("/tasks", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    state.tasks.push(created);
    els.taskInput.value = "";

    // 險ｭ螳唹N縺ｪ繧牙酔蜷阪・遨ｺ繝｡繝｢繧定・蜍穂ｽ懈・縺励※邏蝉ｻ倥￠
    if (localStorage.getItem(AUTO_KEY) === "true") {
      try {
        const note = await api("/notes", {
          method: "POST",
          body: JSON.stringify({ title, body: null, task_id: created.id }),
        });
        state.notes.push(note);
      } catch (e) {
        // 自動作成に失敗してもタスク作成自体は成功扱い
      }
    }
    renderTasks();
    renderNotes();
  } catch (e) {
    alert("追加に失敗しました。");
  }
});

// --- 繝｡繝｢邏蝉ｻ倥￠繝昴ャ繝励い繝・・ ---
let linkTargetTaskId = null;
let linkSelection = new Set();

function openLinkModal(taskId) {
  linkTargetTaskId = taskId;
  linkSelection = new Set(
    state.notes
      .filter((n) => noteTaskIds(n).includes(taskId))
      .map((n) => n.id)
  );
  els.linkModal.hidden = false;
  renderLinkList("");
}
function closeLinkModal() {
  els.linkModal.hidden = true;
  linkTargetTaskId = null;
  linkSelection = new Set();
}
function renderLinkList(q) {
  const query = q.trim().toLowerCase();
  const list = state.notes
    .filter((n) => (n.title || "").toLowerCase().includes(query))
    .sort((a, b) => a.id - b.id);
  els.linkList.innerHTML = list
    .map((n) => {
      const linked = linkSelection.has(n.id) ? " checked" : "";
      return `<li>
        <label class="clip-pick-item">
          <input type="checkbox" data-id="${n.id}"${linked} />
          <span>${escapeHtml(n.title || "(辟｡鬘・")}</span>
        </label>
      </li>`;
    })
    .join("");
  els.linkList.querySelectorAll("input[data-id]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const noteId = Number(cb.dataset.id);
      if (cb.checked) linkSelection.add(noteId);
      else linkSelection.delete(noteId);
    });
  });
}

async function saveLinkModal() {
  const taskId = linkTargetTaskId;
  if (taskId == null) return;
  const changed = state.notes.filter((note) => {
    const currentlyLinked = noteTaskIds(note).includes(taskId);
    return currentlyLinked !== linkSelection.has(note.id);
  });

  try {
    const updatedNotes = await Promise.all(
      changed.map((note) => {
        const currentIds = noteTaskIds(note);
        const nextIds = linkSelection.has(note.id)
          ? [...new Set([...currentIds, taskId])]
          : currentIds.filter((id) => id !== taskId);
        return api(`/notes/${note.id}`, {
          method: "PUT",
          body: JSON.stringify({ task_ids: nextIds }),
        });
      })
    );
    updatedNotes.forEach((updated) => {
      const index = state.notes.findIndex((note) => note.id === updated.id);
      if (index >= 0) state.notes[index] = updated;
    });
    closeLinkModal();
    renderTasks();
    renderNotes();
  } catch (e) {
    alert("紐付けに失敗しました。");
  }
}

els.linkSearch.addEventListener("input", (e) => renderLinkList(e.target.value));
els.linkCancel.addEventListener("click", closeLinkModal);
els.linkSave.addEventListener("click", saveLinkModal);
els.linkModal.addEventListener("click", (e) => {
  if (e.target === els.linkModal) closeLinkModal();
});

// --- 繝｡繝｢ ---
function renderNotes() {
  const list = state.notes.filter(noteMatchesStatus);
  els.memoEmpty.hidden = list.length > 0;
  els.memoGrid.innerHTML = list
    .map((n) => {
      const first = (n.clips || [])[0];
      const extra = (n.clips || []).length - 1;
      const clips = first
        ? `<div class="memo-clips"><span class="clip-chip" data-url="${escapeAttr(first.url)}"><img class="icon icon-inline" src="icons/clip.svg" alt="" /> ${escapeHtml(truncate(first.title || first.url || "", 32))}</span>${extra > 0 ? `<span class="clip-more">+${extra}</span>` : ""}</div>`
        : "";
      const task = noteTask(n);
      const taskBadge = task
        ? `<div class="memo-task ${task.is_done ? "done" : ""}" data-task="${task.id}"><img class="icon icon-inline" src="icons/${task.is_done ? "checkbox" : "box"}.svg" alt="" /> ${escapeHtml(task.title)}</div>`
        : "";
      const pinned = typeof isPinned === "function" && isPinned(n.id, "note");
      return `
        <article class="memo-card" data-id="${n.id}">
          <button class="pin-btn${pinned ? ' on' : ''}" data-pin="${n.id}" data-pin-type="note" title="ピン止め"><img class="icon icon-btn" src="icons/pin.svg" alt="" /></button>
          ${clips ? `<div class="memo-clips">${clips}</div>` : ""}
          <h3 class="memo-title">${escapeHtml(n.title)}</h3>
          ${taskBadge}
          <div class="memo-preview">${escapeHtml(n.body || "")}</div>
        </article>`;
    })
    .join("");

  els.memoGrid.querySelectorAll(".memo-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("a.body-link")) return;
      if (e.ctrlKey || e.metaKey) {
        toggleSelection(Number(card.dataset.id), "note", card);
        return;
      }
      location.href = `/Note?id=${card.dataset.id}`;
    });
  });
  els.memoGrid.querySelectorAll(".clip-chip").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const url = el.dataset.url;
      if (url) window.open(url, "_blank", "noopener");
    });
  });
  els.memoGrid.querySelectorAll("[data-pin]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.pin);
      const type = btn.dataset.pinType;
      togglePin(id, type);
      btn.classList.toggle("on");
      renderSidebarPins();
      notifyPinChange();
    });
  });
}

els.newNote.addEventListener("click", () => {
  location.href = "/Note";
});

// --- 險ｭ螳壹Δ繝ｼ繝繝ｫ ---

// pins.js縺九ｉ逋ｺ陦後＆繧後ｋ繧ｫ繧ｹ繧ｿ繝繧､繝吶Φ繝医〒繧ｿ繧ｹ繧ｯ蜀肴緒逕ｻ
document.addEventListener("highlightSettingChanged", () => renderTasks());

// サイドバー設定
document.querySelectorAll(".side-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.nav === "settings") window.openSettings();
  });
});

// ==================== 遽・峇驕ｸ謚橸ｼ医Λ繝舌・繝舌Φ繝会ｼ・====================

let rubberBandActive = false;
let rubberBandStartX = 0;
let rubberBandStartY = 0;
let rubberBandEl = null;

function rectsOverlap(a, b) {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
}

function cancelRubberBand() {
  rubberBandActive = false;
  if (rubberBandEl) {
    rubberBandEl.remove();
    rubberBandEl = null;
  }
}

function clearSelection() {
  state.selected.clear();
  updateBatchBar();
  document.querySelectorAll(".task-item.selected, .memo-card.selected").forEach((el) => el.classList.remove("selected"));
}

function toggleSelection(id, type, el) {
  if (state.selected.has(id) && state.selected.get(id) === type) {
    state.selected.delete(id);
    el.classList.remove("selected");
  } else {
    state.selected.set(id, type);
    el.classList.add("selected");
  }
  updateBatchBar();
}

function updateBatchBar() {
  const n = state.selected.size;
  els.batchBar.classList.toggle("visible", n > 0);
  if (n > 0) els.batchCount.textContent = `${n}件を選択`;
}

async function batchDeleteSelected() {
  const items = [...state.selected];
  if (!items.length) return;
  if (!confirm(`${items.length}件を削除しますか？`)) return;
  clearSelection();
  let ok = 0, fail = 0;
  for (const [id, type] of items) {
    try {
      const res = await fetch(`${API}/${type === "task" ? "tasks" : "notes"}/${id}`, { method: "DELETE" });
      if (res.ok) ok++; else fail++;
    } catch { fail++; }
  }
  await loadAll();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
}

const notesMainEl = document.querySelector(".main");

notesMainEl.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  cancelRubberBand();
  if (e.target.closest(".task-item") || e.target.closest(".memo-card") || e.target.closest("button") || e.target.closest("select") || e.target.closest("input") || e.target.closest("a")) return;
  state.dragOccurred = false;
  rubberBandActive = true;
  rubberBandStartX = e.clientX + window.scrollX;
  rubberBandStartY = e.clientY + window.scrollY;
  rubberBandEl = document.createElement("div");
  rubberBandEl.className = "rubber-band";
  rubberBandEl.style.left = e.clientX + "px";
  rubberBandEl.style.top = e.clientY + "px";
  rubberBandEl.style.width = "0px";
  rubberBandEl.style.height = "0px";
  document.body.appendChild(rubberBandEl);
  e.preventDefault();
});

document.addEventListener("mousemove", (e) => {
  if (!rubberBandActive || !rubberBandEl) return;
  state.dragOccurred = true;
  const cx = e.clientX + window.scrollX;
  const cy = e.clientY + window.scrollY;
  const dl = Math.min(rubberBandStartX, cx);
  const dt = Math.min(rubberBandStartY, cy);
  const dw = Math.abs(cx - rubberBandStartX);
  const dh = Math.abs(cy - rubberBandStartY);
  rubberBandEl.style.left = (dl - window.scrollX) + "px";
  rubberBandEl.style.top = (dt - window.scrollY) + "px";
  rubberBandEl.style.width = dw + "px";
  rubberBandEl.style.height = dh + "px";
  e.preventDefault();
});

document.addEventListener("mouseup", (e) => {
  if (rubberBandActive && rubberBandEl) {
    const bandRect = rubberBandEl.getBoundingClientRect();
    cancelRubberBand();
    if (!state.dragOccurred) {
      if (!e.target.closest(".task-item") && !e.target.closest(".memo-card") && !e.target.closest("button") && !e.target.closest("select") && !e.target.closest("input") && !e.target.closest("a")) {
        if (state.selected.size > 0) clearSelection();
      }
      return;
    }
    if (!(e.ctrlKey || e.metaKey)) clearSelection();
    document.querySelectorAll(".task-item, .memo-card").forEach((el) => {
      const cardRect = el.getBoundingClientRect();
      if (rectsOverlap(bandRect, cardRect)) {
        const id = Number(el.dataset.id);
        const type = el.classList.contains("task-item") ? "task" : "note";
        if (!state.selected.has(id) || state.selected.get(id) !== type) {
          state.selected.set(id, type);
          el.classList.add("selected");
        }
      }
    });
    updateBatchBar();
    return;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    cancelRubberBand();
    state.dragOccurred = false;
    if (state.selected.size > 0) clearSelection();
  }
});

// Events
els.batchDelBtn.addEventListener("click", batchDeleteSelected);

// Task Ctrl+click selection
els.taskList.addEventListener("click", (e) => {
  const item = e.target.closest(".task-item");
  if (!item) return;
  if (e.ctrlKey || e.metaKey) {
    toggleSelection(Number(item.dataset.id), "task", item);
  }
});

loadAll().catch((e) => {
  els.memoEmpty.hidden = false;
  els.memoEmpty.querySelector(".empty-msg").textContent = "バックエンドに接続できません";
  els.memoEmpty.querySelector(".empty-sub").textContent =
    `サーバー (${API}) を起動してください。`;
});

