const API = "http://127.0.0.1:8000";

const state = {
  noteId: null, // null = 新規作成
  pickedClips: [], // [{id,title,url}]
  mode: "edit", // "edit" | "view"
  history: [], // undo/redo stack: [{value, start, end}]
  historyIdx: -1,
  autoSaveTimer: null,
  autoSaveInFlight: false,
  autoSaveVersion: 0,
  dirty: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  title: $("noteTitle"),
  bodyRaw: $("noteBodyRaw"),
  bodyPreview: $("noteBodyPreview"),
  modeEdit: $("modeEdit"),
  modeView: $("modeView"),
  clipPickerOpen: $("clipPickerOpen"),
  clipPicker: $("clipPicker"),
  clipSearch: $("clipSearch"),
  clipPickList: $("clipPickList"),
  clipPicked: $("clipPicked"),
  noteDelete: $("noteDelete"),
  backLink: $("backLink"),
};

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function snapshot() {
  return JSON.stringify({
    title: els.title.value,
    body: els.bodyRaw.value,
    clipIds: state.pickedClips.map((c) => c.id).slice().sort((a, b) => a - b),
  });
}
let initialSnapshot = "";

// Keep an instant local draft so an accidental tab close does not discard work.
const NOTE_DRAFT_PREFIX = "note-editor-draft:";

function noteDraftKey() {
  const id = new URLSearchParams(location.search).get("id");
  return `${NOTE_DRAFT_PREFIX}${id || "new"}`;
}

function removeNoteDraft(key) {
  try { localStorage.removeItem(key); } catch {}
}

function readNoteDraft() {
  try {
    const raw = localStorage.getItem(noteDraftKey());
    if (!raw) return null;
    const draft = JSON.parse(raw);
    if (!draft || typeof draft !== "object") return null;
    return {
      title: String(draft.title || ""),
      body: String(draft.body || ""),
      clipIds: Array.isArray(draft.clipIds) ? draft.clipIds.map(Number).filter(Number.isFinite) : null,
      clips: Array.isArray(draft.clips) ? draft.clips : [],
    };
  } catch {
    return null;
  }
}

function saveNoteDraft() {
  try {
    const title = els.title.value;
    const body = els.bodyRaw.value;
    const clips = state.pickedClips.map((c) => ({
      id: c.id,
      title: c.title,
      url: c.url,
      thumbnail_url: c.thumbnail_url,
      comment: c.comment,
      tags: c.tags || [],
    }));
    if (!title && !body && clips.length === 0) {
      removeNoteDraft(noteDraftKey());
      return;
    }
    localStorage.setItem(noteDraftKey(), JSON.stringify({
      title,
      body,
      clipIds: clips.map((c) => c.id),
      clips,
      updatedAt: Date.now(),
    }));
  } catch {
    // localStorage may be unavailable in a restricted browser context.
  }
}

function clearNoteDraft() {
  removeNoteDraft(noteDraftKey());
}

function restoreNoteDraft() {
  const draft = readNoteDraft();
  if (!draft) return false;
  const currentClipIds = state.pickedClips.map((c) => c.id).sort((a, b) => a - b);
  const draftClipIds = draft.clipIds ? draft.clipIds.slice().sort((a, b) => a - b) : null;
  const clipsDiffer = draftClipIds !== null && JSON.stringify(draftClipIds) !== JSON.stringify(currentClipIds);
  const differs = draft.title !== els.title.value || draft.body !== els.bodyRaw.value || clipsDiffer;
  if (!differs) return false;

  els.title.value = draft.title;
  els.bodyRaw.value = draft.body;
  if (draftClipIds !== null) state.pickedClips = draft.clips;
  state.dirty = true;
  state.autoSaveVersion++;
  return true;
}

function notePayload() {
  return {
    title: els.title.value.trim(),
    body: els.bodyRaw.value || null,
    clip_ids: state.pickedClips.map((c) => c.id),
  };
}

function scheduleNoteAutoSave() {
  if (state.autoSaveTimer !== null) clearTimeout(state.autoSaveTimer);
  if (!state.dirty) return;
  state.autoSaveTimer = window.setTimeout(() => {
    state.autoSaveTimer = null;
    autoSaveNote();
  }, 650);
}

async function autoSaveNote() {
  if (!state.dirty || state.autoSaveInFlight) return;
  const payload = notePayload();
  // A new note needs a title before it can become a database record.
  // Until then, the local draft still preserves its body and clip choices.
  if (state.noteId == null && !payload.title) return;

  const version = state.autoSaveVersion;
  const draftKeyBeforeSave = noteDraftKey();
  state.autoSaveInFlight = true;
  try {
    if (state.noteId == null) {
      const saved = await api("/notes", { method: "POST", body: JSON.stringify(payload) });
      state.noteId = Number(saved.id);
      history.replaceState(null, "", "?id=" + state.noteId);
    } else {
      await api(`/notes/${state.noteId}`, { method: "PUT", body: JSON.stringify(payload) });
    }
    if (version === state.autoSaveVersion) {
      state.dirty = false;
      removeNoteDraft(draftKeyBeforeSave);
      clearNoteDraft();
      initialSnapshot = snapshot();
    }
  } catch (e) {
    console.warn("Note auto-save failed", e);
  } finally {
    state.autoSaveInFlight = false;
    if (state.dirty && version !== state.autoSaveVersion) scheduleNoteAutoSave();
  }
}

function markNoteDirty() {
  state.dirty = true;
  state.autoSaveVersion++;
  saveNoteDraft();
  scheduleNoteAutoSave();
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

if (typeof marked !== "undefined") {
  marked.setOptions({ gfm: true, breaks: true });
}

// --- モード切り替え ---
function setMode(mode) {
  state.mode = mode;
  const isEdit = mode === "edit";
  els.bodyRaw.hidden = !isEdit;
  els.bodyPreview.hidden = isEdit;
  els.modeEdit.classList.toggle("active", isEdit);
  els.modeView.classList.toggle("active", !isEdit);
  const tb = document.getElementById("mdToolbar");
  if (tb) tb.classList.toggle("hidden", !isEdit);
  if (!isEdit) {
    const raw = els.bodyRaw.value;
    // 既存のmarkdownリンク記法([text](url))はそのまま活かし、
    // 素のURLだけを <url> 形式に変換してmarkedにautolinkさせる
    const autoLinked = raw.replace(
      /(^|[\s(])(https?:\/\/[^\s<>()]+)/g,
      (m, pre, url) => `${pre}<${url}>`
    );
    let html = marked ? marked.parse(autoLinked) : escapeHtml(raw);
    // すべてのリンクを新しいタブで開くようにする
    html = html.replace(/<a /g, '<a target="_blank" rel="noopener" ');
    els.bodyPreview.innerHTML = html;
  }
}

els.modeEdit.addEventListener("click", () => setMode("edit"));
els.modeView.addEventListener("click", () => setMode("view"));

els.title.addEventListener("input", markNoteDirty);
els.bodyRaw.addEventListener("input", () => {
  pushHistory();
  markNoteDirty();
});

window.addEventListener("beforeunload", saveNoteDraft);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") saveNoteDraft();
});

// Ctrl+Z / Ctrl+Shift+Z で undo/redo
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && (e.key === "z" || e.key === "Z")) {
    if (e.shiftKey) {
      e.preventDefault();
      redo();
      markNoteDirty();
    } else {
      e.preventDefault();
      undo();
      markNoteDirty();
    }
    return;
  }
  // Ctrl+E でモードトグル
  if (e.ctrlKey && (e.key === "e" || e.key === "E")) {
    e.preventDefault();
    setMode(state.mode === "edit" ? "view" : "edit");
  }
});

// --- クリップ選択 ---
function renderPickedClips() {
  els.clipPicked.innerHTML = state.pickedClips
    .map((c) => {
      const thumb = c.thumbnail_url
        ? `<img class="picked-clip-thumb" src="${escapeAttr(c.thumbnail_url)}" alt="" />`
        : `<div class="picked-clip-thumb ph">🖼</div>`;
      const tags = (c.tags || [])
        .map((t) => `<span class="picked-clip-tag">${escapeHtml(t.name)}</span>`)
        .join("");
      return `
        <div class="picked-clip-card" data-url="${escapeAttr(c.url || "")}">
          ${thumb}
          <div class="picked-clip-info">
            <div class="picked-clip-title">${escapeHtml(c.title || "(無題)")}</div>
            ${c.comment ? `<div class="picked-clip-comment">${escapeHtml(c.comment)}</div>` : ""}
            ${tags ? `<div class="picked-clip-tags">${tags}</div>` : ""}
          </div>
          <button class="picked-clip-remove" data-rm="${c.id}" title="外す">×</button>
        </div>`;
    })
    .join("");
  els.clipPicked.querySelectorAll(".picked-clip-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("[data-rm]")) return;
      const url = card.dataset.url;
      if (url) window.open(url, "_blank", "noopener");
    });
  });
  els.clipPicked.querySelectorAll("[data-rm]").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(b.dataset.rm);
      state.pickedClips = state.pickedClips.filter((c) => c.id !== id);
      renderPickedClips();
      markNoteDirty();
    });
  });
}

async function openClipPicker() {
  try {
    state.clips = await api("/clips");
  } catch (e) {
    state.clips = [];
  }
  els.clipPicker.hidden = false;
  renderClipPickList("");
}

function closeClipPicker() {
  els.clipPicker.hidden = true;
}

function renderClipPickList(q) {
  const query = q.trim().toLowerCase();
  const pickedIds = new Set(state.pickedClips.map((c) => c.id));
  const list = state.clips.filter((c) =>
    (c.title || c.url || "").toLowerCase().includes(query)
  );
  els.clipPickList.innerHTML = list
    .map((c) => {
      const checked = pickedIds.has(c.id) ? " checked" : "";
      return `<li>
        <label class="clip-pick-item">
          <input type="checkbox" data-pick="${c.id}" data-title="${escapeAttr(c.title || "")}" data-url="${escapeAttr(c.url || "")}"${checked} />
          <span>${escapeHtml(c.title || c.url || "(無題)")}</span>
        </label>
      </li>`;
    })
    .join("");

  els.clipPickList.querySelectorAll("input[data-pick]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = Number(cb.dataset.pick);
      if (cb.checked) {
        const clip = state.clips.find((c) => c.id === id);
        if (clip && !state.pickedClips.some((c) => c.id === id)) {
          state.pickedClips.push({ ...clip });
        }
      } else {
        state.pickedClips = state.pickedClips.filter((c) => c.id !== id);
      }
      renderPickedClips();
      markNoteDirty();
    });
  });
}

els.clipPickerOpen.addEventListener("click", openClipPicker);
els.clipSearch.addEventListener("input", (e) => renderClipPickList(e.target.value));

// --- 関連タスク ---
// --- 保存 / 削除 ---
els.noteDelete.addEventListener("click", async () => {
  if (state.noteId == null) return;
  if (!confirm("このメモを削除しますか？")) return;
  try {
    await api(`/notes/${state.noteId}`, { method: "DELETE" });
    clearNoteDraft();
    location.href = "notes.html";
  } catch (e) {
    alert("削除に失敗しました。");
  }
});

// --- 初期化 ---
async function init() {
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  setMode("edit");

  if (id) {
    state.noteId = Number(id);
    try {
      const note = await api(`/notes/${id}`);
      els.title.value = note.title || "";
      els.bodyRaw.value = note.body || "";
      state.pickedClips = (note.clips || []).map((c) => ({
        id: c.id,
        title: c.title,
        url: c.url,
        thumbnail_url: c.thumbnail_url,
        comment: c.comment,
        tags: c.tags || [],
      }));
    } catch (e) {
      alert("メモの読み込みに失敗しました。");
    }
  } else {
    state.noteId = null;
    els.title.value = "";
    els.bodyRaw.value = "";
    state.pickedClips = [];
  }
  const restored = restoreNoteDraft();
  renderPickedClips();
  initialSnapshot = snapshot();
  pushHistory();
  setupMdToolbar();
  if (restored) scheduleNoteAutoSave();
}

els.backLink.addEventListener("click", async (e) => {
  e.preventDefault();
  if (state.autoSaveTimer !== null) {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
  }
  if (state.dirty) await autoSaveNote();
  location.href = "notes.html";
});
// ==================== Markdown ツールバー ====================

function mdWrap(prefix, suffix, placeholder) {
  const ta = els.bodyRaw;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.slice(start, end);
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  const wrapped = prefix + (sel || placeholder) + suffix;
  ta.value = before + wrapped + after;
  const newPos = start + prefix.length + (sel ? sel.length : (placeholder || "").length);
  ta.selectionStart = ta.selectionEnd = newPos;
  ta.focus();
}

function mdLine(prefix) {
  const ta = els.bodyRaw;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  let sel = ta.value.slice(start, end);
  if (!sel) {
    const lineStart = ta.value.lastIndexOf("\n", start - 1) + 1;
    sel = ta.value.slice(lineStart, end) || "text";
    const before = ta.value.slice(0, lineStart);
    const after = ta.value.slice(end);
    ta.value = before + prefix + sel + after;
    ta.selectionStart = ta.selectionEnd = end + prefix.length;
  } else {
    const lines = sel.split("\n");
    const wrapped = lines.map((l) => prefix + l).join("\n");
    const before = ta.value.slice(0, start);
    const after = ta.value.slice(end);
    ta.value = before + wrapped + after;
    ta.selectionStart = ta.selectionEnd = end + prefix.length * lines.length;
  }
  ta.focus();
}

function mdMultiLine(prefix, suffix) {
  const ta = els.bodyRaw;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.slice(start, end) || "text";
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  ta.value = before + prefix + "\n" + sel + "\n" + suffix + after;
  const newPos = start + prefix.length + 1 + sel.length + 1 + suffix.length;
  ta.selectionStart = ta.selectionEnd = newPos;
  ta.focus();
}

function mdPrompt(prefix, suffix, q, placeholder) {
  const ta = els.bodyRaw;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.slice(start, end);
  const input = prompt(q);
  if (!input) return;
  const wrapped = prefix + (sel || placeholder) + input + suffix;
  ta.value = ta.value.slice(0, start) + wrapped + ta.value.slice(end);
  const newPos = start + wrapped.length;
  ta.selectionStart = ta.selectionEnd = newPos;
  ta.focus();
}

const MD_ACTIONS = {
  bold() { mdWrap("**", "**", "テキスト"); },
  italic() { mdWrap("*", "*", "テキスト"); },
  strike() { mdWrap("~~", "~~", "テキスト"); },
  mark() { mdWrap("<mark>", "</mark>", "テキスト"); },
  h1() { mdLine("# "); },
  h2() { mdLine("## "); },
  h3() { mdLine("### "); },
  ul() { mdLine("- "); },
  ol() { mdLine("1. "); },
  link() { mdPrompt("[", "](url)", "URLを入力してください：", "テキスト"); },
  image() { mdPrompt("![", "](url)", "画像URLを入力してください：", "代替テキスト"); },
  code() { mdWrap("`", "`", "コード"); },
  codeblock() { mdMultiLine("```", "```"); },
  quote() { mdLine("> "); },
  hr() {
    const ta = els.bodyRaw;
    const start = ta.selectionStart;
    const before = ta.value.slice(0, start);
    const after = ta.value.slice(start);
    ta.value = before + "\n---\n" + after;
    ta.selectionStart = ta.selectionEnd = start + 5;
    ta.focus();
  },
};

// ---------- undo / redo ----------

function pushHistory() {
  const ta = els.bodyRaw;
  const entry = { value: ta.value, start: ta.selectionStart, end: ta.selectionEnd };
  state.history = state.history.slice(0, state.historyIdx + 1);
  state.history.push(entry);
  if (state.history.length > 100) state.history.shift();
  state.historyIdx = state.history.length - 1;
}

function undo() {
  if (state.historyIdx <= 0) return;
  state.historyIdx--;
  const entry = state.history[state.historyIdx];
  const ta = els.bodyRaw;
  ta.value = entry.value;
  ta.selectionStart = entry.start;
  ta.selectionEnd = entry.end;
  ta.focus();
}

function redo() {
  if (state.historyIdx >= state.history.length - 1) return;
  state.historyIdx++;
  const entry = state.history[state.historyIdx];
  const ta = els.bodyRaw;
  ta.value = entry.value;
  ta.selectionStart = entry.start;
  ta.selectionEnd = entry.end;
  ta.focus();
}

function setupMdToolbar() {
  document.querySelectorAll("[data-md]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.md;
      if (MD_ACTIONS[action]) {
        MD_ACTIONS[action]();
        pushHistory();
        markNoteDirty();
      }
    });
  });
  // チートシート
  const cheatBtn = document.getElementById("mdCheatsheetBtn");
  const cheatModal = document.getElementById("mdCheatsheet");
  const cheatClose = document.getElementById("mdCheatsheetClose");
  const cheatHide = document.getElementById("mdCheatsheetHide");
  const cheatHideLabel = document.querySelector(".cheatsheet-hide-label");
  if (cheatBtn && cheatModal && cheatClose && cheatHide && cheatHideLabel) {
    // ? ボタン → 常に開く、「次回から表示しない」を非表示
    cheatBtn.addEventListener("click", () => {
      cheatHideLabel.hidden = true;
      cheatModal.hidden = false;
    });
    cheatClose.addEventListener("click", () => {
      if (!cheatHideLabel.hidden && cheatHide.checked) localStorage.setItem("hideAutoCheatsheet", "1");
      cheatModal.hidden = true;
    });
    cheatModal.addEventListener("click", (e) => {
      if (e.target === cheatModal) cheatModal.hidden = true;
    });
    // 初期表示（初回のみ）
    if (localStorage.getItem("hideAutoCheatsheet") !== "1") {
      cheatHideLabel.hidden = false;
      cheatHide.checked = false;
      cheatModal.hidden = false;
    }
  }
}

// サイドバー設定
document.querySelectorAll(".side-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.nav === "settings") window.openSettings();
  });
});

init();
