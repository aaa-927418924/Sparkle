const API = window.location.origin;

const state = {
  noteId: null, // null = 新規作成
  title: "", // タイトルは一覧画面から管理し、編集画面では内部状態だけ保持する
  pickedClips: [], // 既存の関連付けを保存時に維持するためのデータ
  history: [], // undo/redo stack: [{value, start, end}]
  historyIdx: -1,
  autoSaveTimer: null,
  autoSaveInFlight: false,
  autoSaveVersion: 0,
  dirty: false,
  serverUpdatedAt: "",
  saveBlockedByConflict: false,
  conflictAlertShown: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  bodyRaw: $("noteBodyRaw"),
  editorCanvas: $("noteEditorCanvas"),
  bodyHighlight: $("noteBodyHighlight"),
  bodyHighlightCode: $("noteBodyHighlightCode"),
  lineNumbers: $("noteLineNumbers"),
  lineNumbersContent: $("noteLineNumbersContent"),
};

// The textarea remains the single source of truth for editing. This renderer
// only paints a safe, non-interactive copy behind it so keyboard input, IME,
// selection, undo/redo, and assistive technology keep native textarea
// behaviour. Highlight.js is bundled locally so note editing never needs a
// runtime CDN request.
const MARKDOWN_HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => MARKDOWN_HTML_ESCAPES[character]);
}

function highlightMarkdown(source) {
  source = String(source ?? "");
  try {
    const hljs = window.hljs;
    if (hljs && typeof hljs.highlight === "function" && typeof hljs.getLanguage === "function" && hljs.getLanguage("markdown")) {
      return hljs.highlight(source, { language: "markdown", ignoreIllegals: true }).value;
    }
  } catch (error) {
    console.warn("Markdown highlight failed; showing plain text", error);
  }
  return escapeHtml(source);
}

function updateMarkdownEditor(value = els.bodyRaw?.value || "") {
  if (!els.bodyHighlightCode || !els.lineNumbersContent || !els.lineNumbers) return;
  const source = String(value ?? "");
  els.bodyHighlightCode.innerHTML = highlightMarkdown(source);

  const lineCount = Math.max(1, source.split("\n").length);
  els.lineNumbersContent.textContent = Array.from(
    { length: lineCount },
    (_, index) => String(index + 1),
  ).join("\n");
  els.lineNumbers.style.setProperty("--editor-gutter-width", `${Math.max(2, String(lineCount).length)}ch`);
  syncMarkdownEditorScroll();
}

function syncMarkdownEditorScroll() {
  if (!els.bodyRaw || !els.bodyHighlight || !els.lineNumbersContent) return;
  const x = Number(els.bodyRaw.scrollLeft) || 0;
  const y = Number(els.bodyRaw.scrollTop) || 0;
  els.bodyHighlight.style.transform = `translate(${-x}px, ${-y}px)`;
  els.lineNumbersContent.style.transform = `translateY(${-y}px)`;
}

window.highlightMarkdown = highlightMarkdown;
window.updateMarkdownEditor = updateMarkdownEditor;

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    const error = new Error(`HTTP ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

function snapshot() {
  return JSON.stringify({
    title: state.title,
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
      serverUpdatedAt: typeof draft.serverUpdatedAt === "string" ? draft.serverUpdatedAt : "",
    };
  } catch {
    return null;
  }
}

function saveNoteDraft() {
  try {
    const title = state.title;
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
      serverUpdatedAt: state.serverUpdatedAt,
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
  // Existing-note drafts are safe to restore only when they were created from
  // the same server revision. Legacy drafts without a revision are ignored so
  // an Android/PC edit cannot be rolled back by an old localStorage value.
  if (state.noteId != null && (
    !state.serverUpdatedAt || !draft.serverUpdatedAt || draft.serverUpdatedAt !== state.serverUpdatedAt
  )) return false;
  const currentClipIds = state.pickedClips.map((c) => c.id).sort((a, b) => a - b);
  const draftClipIds = draft.clipIds ? draft.clipIds.slice().sort((a, b) => a - b) : null;
  const clipsDiffer = draftClipIds !== null && JSON.stringify(draftClipIds) !== JSON.stringify(currentClipIds);
  const differs = draft.title !== state.title || draft.body !== els.bodyRaw.value || clipsDiffer;
  if (!differs) return false;

  state.title = draft.title;
  els.bodyRaw.value = draft.body;
  if (draftClipIds !== null) state.pickedClips = draft.clips;
  state.dirty = true;
  state.autoSaveVersion++;
  return true;
}

function notePayload() {
  const title = String(state.title || "").trim();
  return {
    title: title || (state.noteId == null ? "無題のメモ" : ""),
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
  if (!state.dirty || state.autoSaveInFlight || state.saveBlockedByConflict) return;
  const payload = notePayload();

  const version = state.autoSaveVersion;
  const draftKeyBeforeSave = noteDraftKey();
  state.autoSaveInFlight = true;
  try {
    let savedNoteId = state.noteId;
    if (state.noteId == null) {
      const saved = await api("/notes", { method: "POST", body: JSON.stringify(payload) });
      state.noteId = Number(saved.id);
      state.title = String(saved.title || payload.title || "無題のメモ");
      state.serverUpdatedAt = String(saved.updated_at || "");
      savedNoteId = state.noteId;
      history.replaceState(null, "", "?id=" + state.noteId);
    } else {
      const saved = await api(`/notes/${state.noteId}`, {
        method: "PUT",
        body: JSON.stringify({ ...payload, expected_updated_at: state.serverUpdatedAt }),
      });
      state.serverUpdatedAt = String(saved?.updated_at || state.serverUpdatedAt);
    }
    // The note is already persisted at this point. Pin/tooltip refreshes are
    // visual follow-up work and must not keep the editor in a saving state on
    // a remote connection with many pinned projects.
    window.refreshPinnedDataInBackground?.("note", savedNoteId);
    window.refreshAllPinnedProjectsInBackground?.();
    if (version === state.autoSaveVersion) {
      state.dirty = false;
      removeNoteDraft(draftKeyBeforeSave);
      clearNoteDraft();
      initialSnapshot = snapshot();
    }
  } catch (e) {
    if (e?.status === 409) {
      state.saveBlockedByConflict = true;
      if (!state.conflictAlertShown) {
        state.conflictAlertShown = true;
        alert("このメモは別の端末で先に更新されています。PC側の編集は保存していません。最新内容を確認するため、この画面を再読み込みしてから編集してください。");
      }
    }
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
els.bodyRaw.addEventListener("input", () => {
  updateMarkdownEditor();
  pushHistory();
  markNoteDirty();
});
els.bodyRaw.addEventListener("scroll", syncMarkdownEditorScroll, { passive: true });
window.addEventListener("resize", syncMarkdownEditorScroll);

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
});

// --- 初期化 ---
async function init() {
  const params = new URLSearchParams(location.search);
  const id = params.get("id");

  if (id) {
    state.noteId = Number(id);
    try {
      const note = await api(`/notes/${id}`);
      state.serverUpdatedAt = String(note.updated_at || "");
      state.title = String(note.title || "");
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
    state.title = "";
    state.serverUpdatedAt = "";
    els.bodyRaw.value = "";
    state.pickedClips = [];
  }
  const restored = restoreNoteDraft();
  updateMarkdownEditor();
  initialSnapshot = snapshot();
  pushHistory();
  if (restored) scheduleNoteAutoSave();
}

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
  updateMarkdownEditor();
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
  updateMarkdownEditor();
  ta.focus();
}

// サイドバー設定
document.querySelectorAll(".side-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.nav === "settings") window.openSettings();
  });
});

init();
