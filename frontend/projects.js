const API = window.location.origin;
const TASK_PROJECT_ONLY_KEY = "taskProjectOnly";

const state = {
  projects: [],
  clips: [],
  tasks: [],
  notes: [],
  categories: [],
  tags: [],
  catMap: new Map(),
  currentProjectId: null,
  editingId: null,
  doneFilter: "0",
  selectedIds: new Set(),
  dragOccurred: false,
  routeRequestId: 0,
};
let projectListHasRendered = false;

const $ = (id) => document.getElementById(id);
const els = {
  listView: $("listView"),
  detailView: $("detailView"),
  projectGrid: $("projectGrid"),
  projectEmpty: $("projectEmpty"),
  detailTitle: $("detailTitle"),
  detailDesc: $("detailDesc"),
  detailClips: $("detailClips"),
  detailClipsEmpty: $("detailClipsEmpty"),
  detailTasks: $("detailTasks"),
  detailTasksEmpty: $("detailTasksEmpty"),
  detailMemos: $("detailMemos"),
  detailMemosEmpty: $("detailMemosEmpty"),
  projectModal: $("projectModal"),
  projectModalTitle: $("projectModalTitle"),
  projectName: $("projectName"),
  projectDesc: $("projectDesc"),
  clipModal: $("clipModal"),
  clipLinked: $("clipLinked"),
  clipLinkedEmpty: $("clipLinkedEmpty"),
  clipSearch: $("clipSearch"),
  clipCatFilter: $("clipCatFilter"),
  clipTagFilter: $("clipTagFilter"),
  clipPickerList: $("clipPickerList"),
  taskModal: $("taskModal"),
  taskLinked: $("taskLinked"),
  taskLinkedEmpty: $("taskLinkedEmpty"),
  taskUnlinkedSelect: $("taskUnlinkedSelect"),
  taskTitle: $("taskTitle"),
  taskDue: $("taskDue"),
  taskStars: $("taskStars"),
  taskProjectOnly: $("taskProjectOnly"),
  noteModal: $("noteModal"),
  noteLinked: $("noteLinked"),
  noteLinkedEmpty: $("noteLinkedEmpty"),
  noteUnlinkedSelect: $("noteUnlinkedSelect"),
  noteTitle: $("noteTitle"),
  noteBody: $("noteBody"),
  batchBar: $("batchBar"),
  batchCount: $("batchCount"),
  batchDelBtn: $("batchDelBtn"),
};

let taskPriority = null;

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
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[m]));
}

function fileIconHtml(url) {
  return "";
}

function linkedToProject(item, projectId) {
  const ids = Array.isArray(item.project_ids)
    ? item.project_ids
    : (item.project_id != null ? [item.project_id] : []);
  return ids.includes(Number(projectId));
}

// ==================== Data Loading ====================

function clipImageUrl(c) {
  if (c.thumbnail_url) {
    if (c.thumbnail_url.startsWith("http://") || c.thumbnail_url.startsWith("https://") || c.thumbnail_url.startsWith("data:")) {
      return c.thumbnail_url;
    }
    return API + c.thumbnail_url;
  }
  if (c.clip_type === "local" && c.url && /\.(png|jpe?g|gif|webp|bmp|svg|ico)$/i.test(c.url)) {
    return API + "/clips/" + c.id + "/file";
  }
  return null;
}

function projectAlbumHtml(projectId) {
  const clips = state.clips.filter((clip) => linkedToProject(clip, projectId));
  if (clips.length === 0) return "";

  const visible = clips.slice(0, 4);
  const countClass = Math.min(visible.length, 4);
  const cells = visible.map((clip) => {
    const src = clipImageUrl(clip);
    return src
      ? '<img class="project-card-album-img" src="' + escapeHtml(src) + '" alt="" loading="lazy" />'
      : '<div class="project-card-album-placeholder">No Image</div>';
  }).join("");
  const more = clips.length > 4
    ? '<span class="project-card-album-more">+' + (clips.length - 4) + '</span>'
    : "";

  return '<div class="project-card-album count-' + countClass + '" aria-label="紐づいたクリップのサムネイル">' + cells + more + '</div>';
}

async function loadAll() {
  const doneParam = state.doneFilter !== "" ? `?done=${state.doneFilter}` : "";
  const [projects, clips, tasks, notes, categories, tags] = await Promise.all([
    api(`/projects${doneParam}`), api("/clips"), api("/tasks"), api("/notes"),
    api("/categories"), api("/tags"),
  ]);
  state.projects = projects;
  state.clips = clips;
  state.tasks = tasks;
  state.notes = notes;
  state.categories = categories;
  state.tags = tags;
  state.catMap = new Map(categories.map((c) => [c.id, c.name]));
  renderProjectList();
}

// ==================== Project List ====================

function renderProjectList() {
  const projs = state.projects;
  const animateInitial = !projectListHasRendered;
  els.projectEmpty.hidden = projs.length > 0;
  els.projectGrid.hidden = projs.length === 0;
  els.projectGrid.innerHTML = projs.map((p, index) => {
    const clipCount = state.clips.filter((c) => linkedToProject(c, p.id)).length;
    const taskCount = state.tasks.filter((t) => t.project_id === p.id).length;
    const noteCount = state.notes.filter((n) => linkedToProject(n, p.id)).length;
    const entryClass = animateInitial ? " page-enter-card" : "";
    const entryStyle = animateInitial ? ` style="--page-enter-index:${index}"` : "";
    return `
      <div class="project-card${p.is_done ? " done" : ""}${entryClass}"${entryStyle} data-id="${p.id}">
        <div class="project-card-check">
          <input type="checkbox" class="proj-done-cb" data-id="${p.id}" aria-label="${escapeHtml(p.name)}の完了状態を切り替え" ${p.is_done ? "checked" : ""} />
        </div>
        ${projectAlbumHtml(p.id)}
        <h3 class="project-card-title${p.is_done ? " done-text" : ""}">${escapeHtml(p.name)}</h3>
        ${p.description ? `<p class="project-card-desc">${escapeHtml(p.description)}</p>` : ""}
        <div class="project-card-counts">
          <span><img class="icon icon-inline" src="icons/clip.svg" alt="" /> ${clipCount}</span>
          <span><img class="icon icon-inline" src="icons/checkbox.svg" alt="" /> ${taskCount}</span>
          <span><img class="icon icon-inline" src="icons/clipboard.svg" alt="" /> ${noteCount}</span>
        </div>
        <div class="project-card-actions">
          <button class="act-btn pin-btn${typeof isPinned === 'function' && isPinned(p.id, 'project') ? ' on' : ''}" data-pin="${p.id}" data-pin-type="project" title="ピン止め"><img class="icon icon-btn" src="icons/pin.svg" alt="ピン" /></button>
          <button class="act-btn proj-edit-btn" data-id="${p.id}" title="編集"><img class="icon icon-btn" src="icons/pencil.svg" alt="編集" /></button>
          <button class="act-btn proj-del-btn" data-id="${p.id}" title="削除"><img class="icon icon-btn" src="icons/trash.svg" alt="削除" /></button>
        </div>
      </div>
    `;
  }).join("");
  if (animateInitial) {
    bindPageEntryAnimation(els.projectGrid);
    projectListHasRendered = true;
  }

  els.projectGrid.querySelectorAll(".project-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".proj-edit-btn") || e.target.closest(".proj-del-btn") || e.target.closest(".proj-done-cb")) return;
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        toggleSelection(Number(card.dataset.id));
        return;
      }
      openDetail(Number(card.dataset.id));
    });
  });
  els.projectGrid.querySelectorAll("[data-pin]").forEach((btn) => {
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
  els.projectGrid.querySelectorAll(".proj-edit-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation(); openEditModal(Number(btn.dataset.id)); });
  });
  els.projectGrid.querySelectorAll(".proj-del-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteProject(Number(btn.dataset.id), {
        anchor: btn.closest(".project-card"),
        immediate: e.shiftKey,
      });
    });
  });
  els.projectGrid.querySelectorAll(".proj-done-cb").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      e.stopPropagation();
      toggleProject(Number(cb.dataset.id));
    });
  });
}

function bindPageEntryAnimation(container) {
  container.querySelectorAll(".page-enter-card").forEach((card) => {
    card.addEventListener("animationend", () => {
      card.classList.remove("page-enter-card");
      card.style.removeProperty("--page-enter-index");
    }, { once: true });
  });
}

// ==================== Project Detail ====================

async function openDetail(projectId, { pushHistory = true } = {}) {
  const requestId = ++state.routeRequestId;
  state.currentProjectId = projectId;
  const proj = state.projects.find((p) => p.id === projectId);
  if (!proj) {
    await showProjectList({ syncUrl: true });
    return;
  }
  els.detailTitle.textContent = proj.name;
  els.detailDesc.textContent = proj.description || "";
  els.detailDesc.hidden = !proj.description;
  $("detailDoneCb").checked = proj.is_done;
  await reloadDetail();
  if (requestId !== state.routeRequestId || state.currentProjectId !== projectId) return;
  els.listView.hidden = true;
  els.detailView.hidden = false;
  if (pushHistory) history.pushState(null, "", `?id=${projectId}`);
}

async function showProjectList({ syncUrl = true, reload = true } = {}) {
  ++state.routeRequestId;
  state.currentProjectId = null;
  els.listView.hidden = false;
  els.detailView.hidden = true;
  if (syncUrl) history.replaceState(null, "", window.location.pathname);
  if (reload) await loadAll();
}

async function syncRouteFromLocation({ reloadList = true } = {}) {
  const rawId = new URLSearchParams(location.search).get("id");
  if (rawId) {
    const projectId = Number(rawId);
    const proj = state.projects.find((p) => p.id === projectId);
    if (Number.isInteger(projectId) && proj) {
      await openDetail(projectId, { pushHistory: false });
      return;
    }
    history.replaceState(null, "", window.location.pathname);
  }
  await showProjectList({ syncUrl: false, reload: reloadList });
}
async function reloadDetail() {
  if (!state.currentProjectId) return;
  const pid = state.currentProjectId;
  const [clips, tasks, notes] = await Promise.all([
    api(`/clips?project_id=${pid}`),
    api(`/tasks?project_id=${pid}`),
    api(`/notes?project_id=${pid}`),
  ]);
  if (state.currentProjectId !== pid) return;
  renderDetailClips(clips);
  renderDetailTasks(tasks);
  renderDetailMemos(notes);
}
function renderDetailClips(clips) {
  els.detailClips.replaceChildren();
  els.detailClipsEmpty.hidden = clips.length > 0;
  els.detailClips.hidden = clips.length === 0;
  if (clips.length === 0) return;
  els.detailClips.innerHTML = clips.map((c) => {
    const isLocal = c.url && c.url.startsWith("local://");
    const isText = isLocal && /\.(txt|md|log|csv|json|js|ts|py|html|css|xml|yaml|yml|toml|ini|cfg|conf|sh|bash|bat|ps1|rb|java|c|cpp|h|hpp|rs|go|swift|kt)$/i.test(c.url);
    let phContent;
    const imgUrl = clipImageUrl(c);
    if (imgUrl) {
      phContent = `<img class="card-img" src="${escapeHtml(imgUrl)}" alt="" />`;
    } else if (isText) {
      phContent = `<div class="card-ph card-ph-text" data-clip-id="${c.id}"><span class="card-text-loading">読み込み中…</span></div>`;
    } else {
      phContent = `<div class="card-ph">${fileIconHtml(c.url)}</div>`;
    }
    return `
      <div class="card" data-clip-id="${c.id}" data-url="${escapeHtml(c.url || "")}">
        ${phContent}
        <div class="card-actions">
          ${isLocal ? `<button class="act-btn" data-explorer="${c.id}" title="エクスプローラーで表示"><img class="icon icon-btn" src="icons/folder.svg" alt="表示" /></button>` : ""}
          <button class="act-btn unlink-clip-btn" data-id="${c.id}" title="紐づけ解除">✕</button>
        </div>
        <div class="card-caption">
          <div class="card-title">${escapeHtml(c.title || "（無題）")}</div>
          ${c.comment ? `<div class="card-comment">${escapeHtml(c.comment)}</div>` : ""}
        </div>
        ${c.tags && c.tags.length ? `<div class="tags">${c.tags.map((t) => `<span class="tag-chip">${escapeHtml(t.name)}</span>`).join("")}</div>` : ""}
      </div>
    `;
  }).join("");

  els.detailClips.querySelectorAll(".card-ph-text[data-clip-id]").forEach(loadTextPreview);
  els.detailClips.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".unlink-clip-btn")) return;
      const clipId = Number(card.dataset.clipId);
      const url = card.dataset.url;
      if (url && url.startsWith("local://")) {
        fetch(`${API}/clips/${clipId}/open`, { method: "POST" });
      } else if (url) {
        window.open(url);
      }
    });
  });
  els.detailClips.querySelectorAll(".unlink-clip-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      unlinkClip(Number(btn.dataset.id));
    });
  });
  els.detailClips.querySelectorAll("[data-explorer]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      fetch(`${API}/clips/${btn.dataset.explorer}/explorer`, { method: "POST" }).catch(() => {});
    });
  });
}

async function loadTextPreview(el) {
  try {
    const res = await fetch(`${API}/clips/${el.dataset.clipId}/text-preview`);
    const data = await res.json();
    el.innerHTML = escapeHtml(data.text || "");
    el.classList.add("loaded");
  } catch {
    el.innerHTML = "<span class='card-text-loading'>プレビュー取得失敗</span>";
  }
}

function renderDetailTasks(tasks) {
  els.detailTasks.replaceChildren();
  els.detailTasksEmpty.hidden = tasks.length > 0;
  els.detailTasks.hidden = tasks.length === 0;
  if (tasks.length === 0) return;
  els.detailTasks.innerHTML = tasks.map((t) => {
    const due = t.due_date ? t.due_date.slice(5, 10) : "";
    const isOverdue = t.due_date && !t.is_done && new Date(t.due_date) < new Date(new Date().toISOString().slice(0, 10));
    return `
      <li class="task-item${t.is_done ? " done" : ""}">
        <div class="task-lead">
          <div class="task-check"><input type="checkbox" ${t.is_done ? "checked" : ""} data-id="${t.id}" aria-label="${escapeHtml(t.title)}の完了状態を切り替え" /></div>
          ${t.priority ? `<span class="task-priority">${"★".repeat(t.priority)}</span>` : ""}
        </div>
        <div class="task-body">
          <div class="task-title">${escapeHtml(t.title)}</div>
          ${due ? `<span class="task-due${isOverdue ? " overdue" : ""}"><img class="icon icon-inline" src="icons/calendar.svg" alt="" /> ${due}</span>` : ""}
        </div>
        <button class="act-btn unlink-task-btn" data-id="${t.id}" title="紐づけ解除" style="opacity:1">✕</button>
      </li>
    `;
  }).join("");
  els.detailTasks.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      await api(`/tasks/${cb.dataset.id}/toggle`, { method: "PATCH" });
      await reloadDetail();
    });
  });
  els.detailTasks.querySelectorAll(".unlink-task-btn").forEach((btn) => {
    btn.addEventListener("click", () => unlinkTask(Number(btn.dataset.id)));
  });
}

function renderDetailMemos(notes) {
  els.detailMemos.replaceChildren();
  els.detailMemosEmpty.hidden = notes.length > 0;
  els.detailMemos.hidden = notes.length === 0;
  if (notes.length === 0) return;
  els.detailMemos.innerHTML = notes.map((n) => {
    const preview = (n.body || "").replace(/[#*`>\-\[\]]/g, "").slice(0, 120);
    return `
      <div class="memo-card" data-note-id="${n.id}" role="link" tabindex="0" aria-label="${escapeHtml(n.title)}を開く">
        <button class="act-btn unlink-note-btn" data-id="${n.id}" title="紐づけ解除" style="position:absolute;top:8px;right:8px;opacity:0">✕</button>
        <h3 class="memo-title">${escapeHtml(n.title)}</h3>
        ${preview ? `<p class="memo-preview">${escapeHtml(preview)}</p>` : ""}
      </div>
    `;
  }).join("");
  els.detailMemos.querySelectorAll(".unlink-note-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      unlinkNote(Number(btn.dataset.id));
    });
  });
  els.detailMemos.querySelectorAll(".memo-card").forEach((card) => {
    const openNote = () => {
      window.location.assign(`/Note?id=${card.dataset.noteId}`);
    };
    card.addEventListener("click", (e) => {
      if (e.target.closest(".unlink-note-btn")) return;
      openNote();
    });
    card.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      openNote();
    });
    card.addEventListener("mouseenter", () => { card.querySelector(".unlink-note-btn").style.opacity = "1"; });
    card.addEventListener("mouseleave", () => { card.querySelector(".unlink-note-btn").style.opacity = "0"; });
  });
}

// ==================== State Refresh ====================

async function refreshState() {
  const [clips, tasks, notes] = await Promise.all([
    api("/clips"), api("/tasks"), api("/notes"),
  ]);
  state.clips = clips;
  state.tasks = tasks;
  state.notes = notes;
}

// ==================== Unlink ====================

async function unlinkClip(clipId) {
  await api(`/projects/${state.currentProjectId}/clips/${clipId}`, { method: "DELETE" });
  await refreshState();
  await reloadDetail();
}

async function unlinkTask(taskId) {
  await api(`/tasks/${taskId}`, { method: "PUT", body: JSON.stringify({ project_id: null }) });
  await refreshState();
  await reloadDetail();
}

async function unlinkNote(noteId) {
  await api(`/projects/${state.currentProjectId}/notes/${noteId}`, { method: "DELETE" });
  await refreshState();
  await reloadDetail();
}

// ==================== Project CRUD ====================

function openCreateModal() {
  state.editingId = null;
  els.projectModalTitle.textContent = "新規プロジェクト";
  els.projectName.value = "";
  els.projectDesc.value = "";
  els.projectModal.hidden = false;
  els.projectName.focus();
}

function openEditModal(id) {
  const proj = state.projects.find((p) => p.id === id);
  if (!proj) return;
  state.editingId = id;
  els.projectModalTitle.textContent = "プロジェクトを編集";
  els.projectName.value = proj.name;
  els.projectDesc.value = proj.description || "";
  els.projectModal.hidden = false;
  els.projectName.focus();
}

async function saveProject() {
  const name = els.projectName.value.trim();
  if (!name) return;
  const body = { name, description: els.projectDesc.value.trim() || null };
  if (state.editingId) {
    await api(`/projects/${state.editingId}`, { method: "PUT", body: JSON.stringify(body) });
  } else {
    await api("/projects", { method: "POST", body: JSON.stringify(body) });
  }
  els.projectModal.hidden = true;
  await loadAll();
}

async function deleteProject(id, options = {}) {
  const proj = state.projects.find((p) => p.id === id);
  if (!proj) return;
  if (!(await window.confirmDeletion(
    `「${proj.name}」を削除します。\nプロジェクト内のクリップ・タスク・メモは削除されません。`,
    options,
  ))) return;
  await api(`/projects/${id}`, { method: "DELETE" });
  if (state.currentProjectId === id) {
    await showProjectList();
    return;
  }
  await loadAll();
}

async function toggleProject(id) {
  await api(`/projects/${id}/toggle`, { method: "PATCH" });
  if (state.currentProjectId === id) {
    const [clips, tasks, notes] = await Promise.all([
      api(`/clips?project_id=${id}`),
      api(`/tasks?project_id=${id}`),
      api(`/notes?project_id=${id}`),
    ]);
    const proj = state.projects.find((p) => p.id === id);
    if (proj) {
      proj.is_done = !proj.is_done;
      els.detailTitle.textContent = proj.name;
    }
    // Re-sort: refresh tasks (they may have been cascaded)
    renderDetailClips(clips);
    renderDetailTasks(tasks);
    renderDetailMemos(notes);
  }
  await loadAll();
}

// ==================== Task Modal ====================

async function openTaskModal() {
  taskPriority = null;
  els.taskTitle.value = "";
  els.taskDue.value = "";
  renderStarPicker();
  await refreshState();
  renderTaskLinked();
  renderTaskUnlinked();
  els.taskModal.hidden = false;
}

function renderStarPicker() {
  els.taskStars.innerHTML = "";
  for (let i = 1; i <= 5; i++) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "star";
    btn.textContent = i <= (taskPriority || 0) ? "★" : "☆";
    btn.addEventListener("click", () => { taskPriority = taskPriority === i ? null : i; renderStarPicker(); });
    els.taskStars.appendChild(btn);
  }
  if (taskPriority) {
    const clr = document.createElement("button");
    clr.type = "button";
    clr.className = "star-clear";
    clr.textContent = "クリア";
    clr.addEventListener("click", () => { taskPriority = null; renderStarPicker(); });
    els.taskStars.appendChild(clr);
  }
}

function renderTaskLinked() {
  const linked = state.tasks.filter((t) => t.project_id === state.currentProjectId);
  els.taskLinkedEmpty.hidden = linked.length > 0;
  els.taskLinked.hidden = linked.length === 0;
  els.taskLinked.innerHTML = linked.map((t) => {
    const due = t.due_date ? ` <img class="icon icon-inline" src="icons/calendar.svg" alt="" />${t.due_date.slice(5, 10)}` : "";
    const pri = t.priority ? ` ${"★".repeat(t.priority)}` : "";
    return `
      <div class="pm-linked-item">
        <span class="item-title">${escapeHtml(t.title)}${pri}${due}</span>
        <button class="item-unlink" data-id="${t.id}" title="解除">✕</button>
      </div>
    `;
  }).join("");
  els.taskLinked.querySelectorAll(".item-unlink").forEach((btn) => {
    btn.addEventListener("click", () => unlinkTask(Number(btn.dataset.id)).then(() => { renderTaskLinked(); renderTaskUnlinked(); }));
  });
}

async function renderTaskUnlinked() {
  const unlinked = await api(`/tasks?exclude_project=${state.currentProjectId}`);
  els.taskUnlinkedSelect.innerHTML = unlinked.length === 0
    ? '<option value="">（紐づけ可能なタスクがありません）</option>'
    : '<option value="">選択してください…</option>' +
      unlinked.map((t) => {
        const due = t.due_date ? ` (${t.due_date.slice(5, 10)})` : "";
        const pri = t.priority ? ` ${"★".repeat(t.priority)}` : "";
        return `<option value="${t.id}">${escapeHtml(t.title)}${pri}${due}</option>`;
      }).join("");
}

async function linkTask() {
  const taskId = Number(els.taskUnlinkedSelect.value);
  if (!taskId) return;
  await api(`/tasks/${taskId}`, { method: "PUT", body: JSON.stringify({ project_id: state.currentProjectId }) });
  await refreshState();
  renderTaskLinked();
  renderTaskUnlinked();
  els.taskUnlinkedSelect.value = "";
  await reloadDetail();
}

async function createAndAddTask() {
  const title = els.taskTitle.value.trim();
  if (!title) { alert("タイトルを入力してください。"); return; }
  const body = {
    title,
    due_date: els.taskDue.value || null,
    priority: taskPriority,
    project_id: els.taskProjectOnly.checked ? state.currentProjectId : null,
  };
  await api("/tasks", { method: "POST", body: JSON.stringify(body) });
  els.taskTitle.value = "";
  els.taskDue.value = "";
  taskPriority = null;
  renderStarPicker();
  await refreshState();
  renderTaskLinked();
  renderTaskUnlinked();
  await reloadDetail();
}

// ==================== Note Modal ====================

async function openNoteModal() {
  els.noteTitle.value = "";
  els.noteBody.value = "";
  await refreshState();
  renderNoteLinked();
  renderNoteUnlinked();
  els.noteModal.hidden = false;
}

function renderNoteLinked() {
  const linked = state.notes.filter((n) => linkedToProject(n, state.currentProjectId));
  els.noteLinkedEmpty.hidden = linked.length > 0;
  els.noteLinked.hidden = linked.length === 0;
  els.noteLinked.innerHTML = linked.map((n) => `
    <div class="pm-linked-item">
      <span class="item-title">${escapeHtml(n.title)}</span>
      <a href="/Note?id=${n.id}" class="item-meta" style="text-decoration:none">編集</a>
      <button class="item-unlink" data-id="${n.id}" title="解除">✕</button>
    </div>
  `).join("");
  els.noteLinked.querySelectorAll(".item-unlink").forEach((btn) => {
    btn.addEventListener("click", () => unlinkNote(Number(btn.dataset.id)).then(() => { renderNoteLinked(); renderNoteUnlinked(); }));
  });
}

async function renderNoteUnlinked() {
  const unlinked = await api(`/notes?exclude_project=${state.currentProjectId}`);
  els.noteUnlinkedSelect.innerHTML = unlinked.length === 0
    ? '<option value="">（紐づけ可能なメモがありません）</option>'
    : '<option value="">選択してください…</option>' +
      unlinked.map((n) => `<option value="${n.id}">${escapeHtml(n.title)}</option>`).join("");
}

async function linkNote() {
  const noteId = Number(els.noteUnlinkedSelect.value);
  if (!noteId) return;
  await api(`/projects/${state.currentProjectId}/notes/${noteId}`, { method: "POST" });
  await refreshState();
  renderNoteLinked();
  renderNoteUnlinked();
  els.noteUnlinkedSelect.value = "";
  await reloadDetail();
}

async function createAndAddNote() {
  const title = els.noteTitle.value.trim();
  if (!title) { alert("タイトルを入力してください。"); return; }
  const body = {
    title,
    body: els.noteBody.value.trim() || null,
    project_id: state.currentProjectId,
  };
  await api("/notes", { method: "POST", body: JSON.stringify(body) });
  els.noteTitle.value = "";
  els.noteBody.value = "";
  await refreshState();
  renderNoteLinked();
  renderNoteUnlinked();
  await reloadDetail();
}

// ==================== Clip Modal ====================

async function openClipModal() {
  await refreshState();
  renderClipLinked();
  els.clipSearch.value = "";
  els.clipCatFilter.innerHTML = '<option value="">すべて</option>' +
    state.categories.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
  els.clipTagFilter.innerHTML = '<option value="">すべて</option>' +
    state.tags.map((t) => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`).join("");
  els.clipModal.hidden = false;
  renderClipPicker();
}

function renderClipLinked() {
  const linked = state.clips.filter((c) => linkedToProject(c, state.currentProjectId));
  els.clipLinkedEmpty.hidden = linked.length > 0;
  els.clipLinked.hidden = linked.length === 0;
  els.clipLinked.innerHTML = linked.map((c) => {
    let thumb;
    const imgUrl = clipImageUrl(c);
    if (imgUrl) {
      thumb = `<img class="pm-clip-thumb" src="${escapeHtml(imgUrl)}" alt="" />`;
    } else {
      thumb = `<div class="pm-clip-thumb ph">${fileIconHtml(c.url)}</div>`;
    }
    const catName = c.category_id ? (state.catMap.get(c.category_id) || "") : "";
    return `
      <div class="pm-linked-item">
        ${thumb}
        <span class="item-title">${escapeHtml(c.title || c.url || "（無題）")}</span>
        ${catName ? `<span class="item-meta">${escapeHtml(catName)}</span>` : ""}
        <button class="item-unlink" data-id="${c.id}" title="解除">✕</button>
      </div>
    `;
  }).join("");
  els.clipLinked.querySelectorAll(".item-unlink").forEach((btn) => {
    btn.addEventListener("click", () => unlinkClip(Number(btn.dataset.id)).then(() => { renderClipLinked(); renderClipPicker(); }));
  });
}

async function renderClipPicker() {
  const q = els.clipSearch.value.trim();
  const cat = els.clipCatFilter.value;
  const tag = els.clipTagFilter.value;
  const pid = state.currentProjectId;

  let clips = state.clips.filter((c) => !linkedToProject(c, pid));

  if (q) {
    const ql = q.toLowerCase();
    clips = clips.filter((c) =>
      (c.title && c.title.toLowerCase().includes(ql)) ||
      (c.comment && c.comment.toLowerCase().includes(ql)) ||
      (c.url && c.url.toLowerCase().includes(ql))
    );
  }
  if (cat) {
    clips = clips.filter((c) => c.category_id && state.catMap.get(c.category_id) === cat);
  }
  if (tag) {
    clips = clips.filter((c) => c.tags && c.tags.some((t) => t.name === tag));
  }

  if (clips.length === 0) {
    els.clipPickerList.innerHTML = '<div class="pm-clip-empty">該当するクリップがありません</div>';
    return;
  }

  els.clipPickerList.innerHTML = clips.map((c) => {
    let thumb;
    const imgUrl = clipImageUrl(c);
    if (imgUrl) {
      thumb = `<img class="pm-clip-thumb" src="${escapeHtml(imgUrl)}" alt="" />`;
    } else {
      thumb = `<div class="pm-clip-thumb ph">${fileIconHtml(c.url)}</div>`;
    }
    const catName = c.category_id ? (state.catMap.get(c.category_id) || "") : "";
    const tags = (c.tags || []).map((t) => `<span class="pm-clip-tag">${escapeHtml(t.name)}</span>`).join("");
    return `
      <div class="pm-clip-item" data-id="${c.id}">
        ${thumb}
        <div class="pm-clip-info">
          <div class="pm-clip-title">${escapeHtml(c.title || c.url || "（無題）")}</div>
          ${c.comment ? `<div class="pm-clip-comment">${escapeHtml(c.comment)}</div>` : ""}
          <div class="pm-clip-tags">
            ${catName ? `<span class="pm-clip-cat">${escapeHtml(catName)}</span>` : ""}
            ${tags}
          </div>
        </div>
      </div>
    `;
  }).join("");

  els.clipPickerList.querySelectorAll(".pm-clip-item").forEach((item) => {
    item.addEventListener("click", () => linkClip(Number(item.dataset.id)));
  });
}

async function linkClip(clipId) {
  await api(`/projects/${state.currentProjectId}/clips/${clipId}`, { method: "POST" });
  await refreshState();
  renderClipLinked();
  renderClipPicker();
  await reloadDetail();
}

// ==================== Event Binding ====================

function bindEvents() {
  $("newProjectBtn").addEventListener("click", openCreateModal);
  $("projectModalCancel").addEventListener("click", () => { els.projectModal.hidden = true; });
  $("projectModalSave").addEventListener("click", saveProject);
  $("backToList").addEventListener("click", async (e) => {
    e.preventDefault();
    await showProjectList();
  });
  window.addEventListener("popstate", () => {
    syncRouteFromLocation().catch((e) => console.warn("プロジェクト画面の同期に失敗しました", e));
  });
  $("detailEditBtn").addEventListener("click", () => openEditModal(state.currentProjectId));
  $("detailDeleteBtn").addEventListener("click", (e) => deleteProject(state.currentProjectId, {
    anchor: e.currentTarget,
    immediate: e.shiftKey,
  }));
  $("detailDoneCb").addEventListener("change", () => toggleProject(state.currentProjectId));

  // Filter tabs
  $("projFilterTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".cat-btn");
    if (!btn) return;
    $("projFilterTabs").querySelectorAll(".cat-btn").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    state.doneFilter = btn.dataset.done;
    loadAll();
  });

  // Add buttons
  $("addClipBtn").addEventListener("click", openClipModal);
  $("addTaskBtn").addEventListener("click", openTaskModal);
  $("addNoteBtn").addEventListener("click", openNoteModal);

  // Task modal
  $("taskModalCancel").addEventListener("click", () => { els.taskModal.hidden = true; });
  els.taskUnlinkedSelect.addEventListener("change", () => { linkTask(); });
  $("taskModalSave").addEventListener("click", createAndAddTask);
  els.taskModal.addEventListener("click", (e) => { if (e.target === els.taskModal) els.taskModal.hidden = true; });

  // Note modal
  $("noteModalCancel").addEventListener("click", () => { els.noteModal.hidden = true; });
  els.noteUnlinkedSelect.addEventListener("change", () => { linkNote(); });
  $("noteModalSave").addEventListener("click", createAndAddNote);
  els.noteModal.addEventListener("click", (e) => { if (e.target === els.noteModal) els.noteModal.hidden = true; });

  // Clip modal
  $("clipModalCancel").addEventListener("click", () => { els.clipModal.hidden = true; });
  els.clipModal.addEventListener("click", (e) => { if (e.target === els.clipModal) els.clipModal.hidden = true; });
  els.clipSearch.addEventListener("input", () => renderClipPicker());
  els.clipCatFilter.addEventListener("change", () => renderClipPicker());
  els.clipTagFilter.addEventListener("change", () => renderClipPicker());

  // Project modal
  els.projectModal.addEventListener("click", (e) => { if (e.target === els.projectModal) els.projectModal.hidden = true; });
  els.projectName.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveProject(); } });

  // プロジェクト限定タスクの状態を localStorage で保持
  const saved = localStorage.getItem(TASK_PROJECT_ONLY_KEY);
  if (saved !== null) els.taskProjectOnly.checked = saved === "true";
  els.taskProjectOnly.addEventListener("change", () => {
    localStorage.setItem(TASK_PROJECT_ONLY_KEY, els.taskProjectOnly.checked);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (state.selectedIds.size > 0) {
        clearSelection();
        cancelRubberBand();
        state.dragOccurred = false;
        return;
      }
      [els.projectModal, els.clipModal, els.taskModal, els.noteModal].forEach((m) => { m.hidden = true; });
    }
  });
}

// ==================== 範囲選択（ラバーバンド） ====================

let rubberBandActive = false;
let rubberBandStartX = 0;
let rubberBandStartY = 0;
let rubberBandEl = null;
let rubberBandAdditive = false;

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
  state.selectedIds.clear();
  updateBatchBar();
  document.querySelectorAll(".project-card.selected").forEach((el) => el.classList.remove("selected"));
}

function toggleSelection(id) {
  if (state.selectedIds.has(id)) {
    state.selectedIds.delete(id);
  } else {
    state.selectedIds.add(id);
  }
  const card = els.projectGrid.querySelector(`.project-card[data-id="${id}"]`);
  if (card) card.classList.toggle("selected");
  updateBatchBar();
}

function updateBatchBar() {
  const n = state.selectedIds.size;
  els.batchBar.classList.toggle("visible", n > 0);
  if (n > 0) els.batchCount.textContent = `${n}件選択`;
}

async function batchDeleteSelected(event) {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  if (!(await window.confirmDeletion(`${ids.length}件のプロジェクトを削除します。`, {
    anchor: els.batchDelBtn,
    immediate: Boolean(event?.shiftKey),
  }))) return;
  clearSelection();
  let ok = 0, fail = 0;
  for (const id of ids) {
    try {
      const res = await fetch(`${API}/projects/${id}`, { method: "DELETE" });
      if (res.ok) ok++; else fail++;
    } catch { fail++; }
  }
  await loadAll();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
}

const projMainEl = document.querySelector(".main");

projMainEl.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  cancelRubberBand();
  if (e.target.closest(".project-card") || e.target.closest("button") || e.target.closest("select") || e.target.closest("input") || e.target.closest("a")) return;
  state.dragOccurred = false;
  rubberBandAdditive = e.shiftKey || e.ctrlKey || e.metaKey;
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
    const preserveSelection = rubberBandAdditive || e.shiftKey || e.ctrlKey || e.metaKey;
    cancelRubberBand();
    if (!state.dragOccurred) {
      if (!e.target.closest(".project-card") && !e.target.closest("button") && !e.target.closest("select") && !e.target.closest("input") && !e.target.closest("a")) {
        if (state.selectedIds.size > 0 && !preserveSelection) clearSelection();
      }
      return;
    }
    if (!preserveSelection) clearSelection();
    els.projectGrid.querySelectorAll(".project-card").forEach((card) => {
      const cardRect = card.getBoundingClientRect();
      if (rectsOverlap(bandRect, cardRect)) {
        const id = Number(card.dataset.id);
        if (!state.selectedIds.has(id)) {
          state.selectedIds.add(id);
          card.classList.add("selected");
        }
      }
    });
    updateBatchBar();
    return;
  }
});

// イベント
els.batchDelBtn.addEventListener("click", batchDeleteSelected);

// サイドバー設定
document.querySelectorAll(".side-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.nav === "settings") window.openSettings();
  });
});

async function init() {
  bindEvents();
  await loadAll();
  await syncRouteFromLocation({ reloadList: false });
}

init();
