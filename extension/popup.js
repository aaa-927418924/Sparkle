const API_BASE = "http://127.0.0.1:8000";
const MAX_TEMPLATES = 4;
const DEFAULT_TEMPLATE_OPTIONS = {
  includeComment: false,
  autoSave: false,
};

const $ = (id) => document.getElementById(id);

const els = {
  pageTitle: $("pageTitle"),
  pageUrl: $("pageUrl"),
  templateSlots: $("templateSlots"),
  comment: $("comment"),
  category: $("category"),
  categorySuggest: $("categorySuggest"),
  tagBox: $("tagBox"),
  tagInput: $("tagInput"),
  tagSuggest: $("tagSuggest"),
  favorite: $("favorite"),
  addTemplate: $("addTemplate"),
  templateEditor: $("templateEditor"),
  templateTitle: $("templateTitle"),
  templateSummary: $("templateSummary"),
  templateCommentSummary: $("templateCommentSummary"),
  templateCancel: $("templateCancel"),
  templateCreate: $("templateCreate"),
  templateEditorStatus: $("templateEditorStatus"),
  save: $("save"),
  status: $("status"),
  pickThumb: $("pickThumb"),
  thumbPreviewWrap: $("thumbPreviewWrap"),
  thumbPreview: $("thumbPreview"),
  thumbReset: $("thumbReset"),
};

let pageInfo = null;
let tags = [];
let tagHistory = []; // 保存成功したタグ履歴(新しい順、chrome.storage.localに永続化)
let tagNames = []; // APIから取得した既存タグ一覧
let categoryNames = []; // APIから取得した既存カテゴリ
let categoryHistory = []; // 保存済みカテゴリ履歴(新しい順、chrome.storage.localに永続化)
let tagSuggestIndex = -1; // キーボードでハイライト中の候補index
let categorySuggestIndex = -1; // キーボードでハイライト中のカテゴリ候補index
let pendingThumbnail = null; // スクショで選んだ data URL (未選択なら null)
let sourceTabId = null;
let templates = [];
let templateOptions = { ...DEFAULT_TEMPLATE_OPTIONS };

async function api(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function normalizeTagKey(value) {
  return String(value || "")
    .trim()
    .normalize("NFKC")
    .toLocaleLowerCase();
}

function cleanTagValue(value) {
  return String(value || "").trim();
}

function uniqueTagValues(values) {
  const seen = new Set();
  const result = [];
  for (const value of Array.isArray(values) ? values : []) {
    const tag = cleanTagValue(value);
    const key = normalizeTagKey(tag);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(tag);
  }
  return result;
}

function createTemplateId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `template-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalizeTemplate(value) {
  if (!value || typeof value !== "object") return null;

  const title = String(value.title || "").trim().slice(0, 40);
  const category = String(value.category || "").trim();
  const tags = uniqueTagValues(value.tags);
  const comment = String(value.comment || "").trim();
  if (!title || (!category && !tags.length)) return null;

  return {
    id: String(value.id || createTemplateId()),
    title,
    category,
    tags,
    comment,
    createdAt: Number(value.createdAt) || Date.now(),
    updatedAt: Number(value.updatedAt) || Date.now(),
  };
}

async function loadTemplateState() {
  try {
    const data = await chrome.storage.local.get(["clipTemplates", "templateOptions"]);
    templates = Array.isArray(data.clipTemplates)
      ? data.clipTemplates
          .map(normalizeTemplate)
          .filter(Boolean)
          .slice(0, MAX_TEMPLATES)
      : [];

    const savedOptions = data.templateOptions;
    templateOptions = {
      ...DEFAULT_TEMPLATE_OPTIONS,
      ...(savedOptions && typeof savedOptions === "object" ? savedOptions : {}),
      includeComment: !!(savedOptions && savedOptions.includeComment),
      autoSave: !!(savedOptions && savedOptions.autoSave),
    };
  } catch (e) {
    templates = [];
    templateOptions = { ...DEFAULT_TEMPLATE_OPTIONS };
  }
  renderTemplateSlots();
  updateTemplateEditorSummary();
  els.addTemplate.disabled = false;
}

function renderTemplateSlots() {
  els.templateSlots.innerHTML = "";
  templates.slice(0, MAX_TEMPLATES).forEach((template, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "template-slot";
    button.textContent = String(index + 1);
    button.title = template.title;
    button.setAttribute("aria-label", `テンプレート${index + 1}: ${template.title}`);
    button.addEventListener("click", () => applyTemplate(template));
    els.templateSlots.appendChild(button);
  });
  els.templateSlots.hidden = templates.length === 0;
}

function setTemplateEditorStatus(message) {
  els.templateEditorStatus.textContent = message || "";
  els.templateEditorStatus.hidden = !message;
}

function updateTemplateEditorSummary() {
  if (!els.templateEditor || els.templateEditor.hidden) return;

  const category = els.category.value.trim();
  const currentTags = uniqueTagValues(tags);
  const categoryText = category || "なし";
  const tagText = currentTags.length ? currentTags.join(", ") : "なし";
  els.templateSummary.textContent = `カテゴリ：${categoryText}　タグ：${tagText}`;
  els.templateCommentSummary.textContent = templateOptions.includeComment
    ? `コメント：保存する${els.comment.value.trim() ? "（入力済み）" : "（空欄）"}`
    : "コメント：保存しない（オプションで変更できます）";
}

function openTemplateEditor() {
  if (templates.length >= MAX_TEMPLATES) {
    setStatus("テンプレートは最大4個までです。オプションから削除できます。", "err");
    return;
  }
  els.templateTitle.value = "";
  setTemplateEditorStatus("");
  els.templateEditor.hidden = false;
  updateTemplateEditorSummary();
  els.templateTitle.focus();
}

function closeTemplateEditor() {
  els.templateEditor.hidden = true;
  els.templateTitle.value = "";
  setTemplateEditorStatus("");
}

async function createTemplate() {
  const title = els.templateTitle.value.trim().slice(0, 40);
  const category = els.category.value.trim();
  const templateTags = uniqueTagValues(tags);
  const comment = templateOptions.includeComment ? els.comment.value.trim() : "";

  if (!title) {
    setTemplateEditorStatus("テンプレートの表示タイトルを入力してください。");
    els.templateTitle.focus();
    return;
  }
  if (!category && !templateTags.length) {
    setTemplateEditorStatus("カテゴリまたはタグを1つ以上設定してください。");
    return;
  }
  if (templates.length >= MAX_TEMPLATES) {
    closeTemplateEditor();
    setStatus("テンプレートは最大4個までです。", "err");
    return;
  }

  const now = Date.now();
  const template = {
    id: createTemplateId(),
    title,
    category,
    tags: templateTags,
    comment,
    createdAt: now,
    updatedAt: now,
  };
  const nextTemplates = [...templates, template].slice(0, MAX_TEMPLATES);

  try {
    await chrome.storage.local.set({ clipTemplates: nextTemplates });
    templates = nextTemplates;
    renderTemplateSlots();
    closeTemplateEditor();
    setStatus(`テンプレート「${title}」を作成しました`, "ok");
  } catch (e) {
    setTemplateEditorStatus("テンプレートを保存できませんでした。もう一度お試しください。");
  }
}

function appendTemplateComment(templateComment) {
  const comment = String(templateComment || "").trim();
  if (!comment) return;

  const current = els.comment.value.trim();
  if (!current) {
    els.comment.value = comment;
  } else if (current !== comment) {
    els.comment.value = `${current}\n${comment}`;
  }
}

async function applyTemplate(template) {
  const normalized = normalizeTemplate(template);
  if (!normalized) {
    setStatus("テンプレートの内容が不正です", "err");
    return;
  }

  tags = uniqueTagValues([...tags, ...normalized.tags]);
  renderTags();
  if (normalized.category) {
    els.category.value = normalized.category;
  }
  appendTemplateComment(normalized.comment);
  updateTemplateEditorSummary();
  await saveDraft();

  if (templateOptions.autoSave) {
    await save();
  } else {
    setStatus(`テンプレート「${normalized.title}」を適用しました`, "ok");
  }
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;

  if (changes.clipTemplates) {
    templates = Array.isArray(changes.clipTemplates.newValue)
      ? changes.clipTemplates.newValue
          .map(normalizeTemplate)
          .filter(Boolean)
          .slice(0, MAX_TEMPLATES)
      : [];
    renderTemplateSlots();
  }
  if (changes.templateOptions) {
    const next = changes.templateOptions.newValue;
    templateOptions = {
      ...DEFAULT_TEMPLATE_OPTIONS,
      ...(next && typeof next === "object" ? next : {}),
      includeComment: !!(next && next.includeComment),
      autoSave: !!(next && next.autoSave),
    };
    updateTemplateEditorSummary();
  }
});

async function loadSuggestions() {
  let categoriesOk = false;
  let tagsOk = false;
  try {
    const categories = await api("/categories");
    categoriesOk = true;
    categoryNames = Array.isArray(categories)
      ? categories
          .map((c) => (c && c.name ? String(c.name).trim() : ""))
          .filter(Boolean)
      : [];
  } catch (e) {
    // 候補の取得失敗は保存には影響しないため無視
  }
  try {
    const data = await api("/tags");
    tagsOk = true;
    tagNames = Array.isArray(data)
      ? data
          .map((t) => (t && t.name ? String(t.name).trim() : ""))
          .filter(Boolean)
      : [];
  } catch (e) {
    // 候補の取得失敗は保存には影響しないため無視
  }
  try {
    const data = await chrome.storage.local.get(["tagHistory", "categoryHistory"]);
    if (Array.isArray(data.tagHistory)) {
      tagHistory = data.tagHistory;
    }
    if (Array.isArray(data.categoryHistory)) {
      categoryHistory = data.categoryHistory
        .map((name) => (typeof name === "string" ? name.trim() : ""))
        .filter(Boolean);
    }
  } catch (e) {
    // 履歴の読み込み失敗は保存には影響しないため無視
  }

  // アプリ側で削除済みのタグ/カテゴリは履歴からも取り除く（サーバー取得成功時のみ）
  const save = {};
  if (tagsOk) {
    const filtered = tagHistory.filter((name) => tagNames.includes(name));
    if (filtered.length !== tagHistory.length) {
      tagHistory = filtered;
      save.tagHistory = tagHistory;
    }
  }
  if (categoriesOk) {
    const filtered = categoryHistory.filter((name) => categoryNames.includes(name));
    if (filtered.length !== categoryHistory.length) {
      categoryHistory = filtered;
      save.categoryHistory = categoryHistory;
    }
  }
  if (Object.keys(save).length) {
    try {
      await chrome.storage.local.set(save);
    } catch (e) {
      // ストレージエラーは無視
    }
  }
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

function renderTags() {
  els.tagBox.innerHTML = tags
    .map(
      (t, i) =>
        `<span class="tag">${escapeHtml(t)}<button data-i="${i}" title="削除">×</button></span>`
    )
    .join("");
  els.tagBox.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      tags.splice(Number(b.dataset.i), 1);
      renderTags();
      saveDraft();
    });
  });
  updateTemplateEditorSummary();
}

function addTag(value) {
  const name = cleanTagValue(value);
  if (name && !tags.some((tag) => normalizeTagKey(tag) === normalizeTagKey(name))) {
    tags.push(name);
    renderTags();
  }
  els.tagInput.value = "";
  saveDraft();
}

function recordTagHistory(name) {
  // 既存履歴から削除して先頭に追加(新しい順)
  const idx = tagHistory.indexOf(name);
  if (idx >= 0) tagHistory.splice(idx, 1);
  tagHistory.unshift(name);
  if (tagHistory.length > 50) tagHistory.length = 50;
  try {
    chrome.storage.local.set({ tagHistory });
  } catch (e) { /* ストレージエラーは無視 */ }
}

function recordCategoryHistory(name) {
  const value = name.trim();
  if (!value) return;

  // 既存履歴から削除して先頭に追加(新しい順)
  const idx = categoryHistory.indexOf(value);
  if (idx >= 0) categoryHistory.splice(idx, 1);
  categoryHistory.unshift(value);
  if (categoryHistory.length > 50) categoryHistory.length = 50;
  try {
    chrome.storage.local.set({ categoryHistory });
  } catch (e) { /* ストレージエラーは無視 */ }
}

function renderTagSuggest(filterText) {
  const q = filterText.trim().toLowerCase();
  // ポップアップ内の残りスペースに合わせてリストの高さを制限し、超えた分はスクロールで表示
  const inputBottom = els.tagInput.getBoundingClientRect().bottom;
  const availHeight = Math.max(40, window.innerHeight - inputBottom - 8);
  const itemHeight = 38;

  const combined = [...tagHistory, ...tagNames];
  const list = combined
    .filter((name, index) => combined.indexOf(name) === index)
    .filter((name) => !tags.includes(name))
    .filter((name) => !q || name.toLowerCase().includes(q));
  if (!list.length) {
    closeTagSuggest();
    return;
  }
  els.tagSuggest.innerHTML = list
    .map(
      (name, i) =>
        `<div class="suggest-item${i === tagSuggestIndex ? " active" : ""}" data-name="${escapeHtml(name)}">${escapeHtml(name)}</div>`
    )
    .join("");
  els.tagSuggest.style.maxHeight = Math.min(list.length * itemHeight + 4, availHeight) + "px";
  els.tagSuggest.hidden = false;
  if (tagSuggestIndex >= 0 && els.tagSuggest.children[tagSuggestIndex]) {
    els.tagSuggest.children[tagSuggestIndex].scrollIntoView({ block: "nearest" });
  }
  els.tagSuggest.querySelectorAll(".suggest-item").forEach((el) => {
    el.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      addTag(el.dataset.name);
      closeTagSuggest();
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      els.tagInput.blur();
      closeTagSuggest();
    });
  });
}

function closeTagSuggest() {
  els.tagSuggest.hidden = true;
  els.tagSuggest.innerHTML = "";
  els.tagSuggest.style.maxHeight = "";
  tagSuggestIndex = -1;
}

function getCategorySuggestions() {
  // 履歴は新しい順で格納されているため反転し、最近使ったカテゴリを一番下に表示
  return [...categoryHistory, ...categoryNames].filter(
    (name, index, list) => list.indexOf(name) === index
  ).reverse();
}

function renderCategorySuggest(filterText) {
  const q = filterText.trim().toLowerCase();
  // 入力欄の上側に表示するため、上に残っている高さまでリストを広げ、超えた分はスクロール
  const inputTop = els.category.getBoundingClientRect().top;
  const availHeight = Math.max(40, inputTop - 8);
  const itemHeight = 38;

  const list = getCategorySuggestions().filter(
    (name) => !q || name.toLowerCase().includes(q)
  );
  if (!list.length) {
    closeCategorySuggest();
    return;
  }
  // 表示直後は一番下（最近使ったカテゴリ）を表示し、そこから上へ辿る形式にする
  if (categorySuggestIndex === -1) {
    categorySuggestIndex = list.length - 1;
  }
  categorySuggestIndex = Math.min(categorySuggestIndex, list.length - 1);

  els.categorySuggest.innerHTML = list
    .map(
      (name, i) =>
        `<div id="categorySuggestOption${i}" class="suggest-item${i === categorySuggestIndex ? " active" : ""}" role="option" aria-selected="${i === categorySuggestIndex}" data-name="${escapeHtml(name)}">${escapeHtml(name)}</div>`
    )
    .join("");
  els.categorySuggest.style.maxHeight = Math.min(list.length * itemHeight + 4, availHeight) + "px";
  els.categorySuggest.hidden = false;
  els.category.setAttribute("aria-expanded", "true");
  if (categorySuggestIndex >= 0) {
    els.category.setAttribute("aria-activedescendant", `categorySuggestOption${categorySuggestIndex}`);
    els.categorySuggest.children[categorySuggestIndex].scrollIntoView({ block: "nearest" });
  } else {
    els.category.removeAttribute("aria-activedescendant");
  }
  els.categorySuggest.querySelectorAll(".suggest-item").forEach((el) => {
    el.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      els.category.value = el.dataset.name;
      saveDraft();
      closeCategorySuggest();
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      els.category.blur();
      closeCategorySuggest();
    });
  });
}

function closeCategorySuggest() {
  els.categorySuggest.hidden = true;
  els.categorySuggest.innerHTML = "";
  els.categorySuggest.style.maxHeight = "";
  els.category.setAttribute("aria-expanded", "false");
  els.category.removeAttribute("aria-activedescendant");
  categorySuggestIndex = -1;
}

els.tagInput.addEventListener("input", () => {
  tagSuggestIndex = -1;
  renderTagSuggest(els.tagInput.value);
});

els.tagInput.addEventListener("focus", () => {
  renderTagSuggest(els.tagInput.value);
});

// 既にフォーカスがある状態で空欄クリック → 履歴再表示
els.tagInput.addEventListener("click", () => {
  if (els.tagSuggest.hidden) {
    tagSuggestIndex = -1;
    renderTagSuggest(els.tagInput.value);
  }
});

els.category.addEventListener("input", () => {
  categorySuggestIndex = -1;
  renderCategorySuggest(els.category.value);
  updateTemplateEditorSummary();
  saveDraft();
});

els.category.addEventListener("focus", () => {
  renderCategorySuggest(els.category.value);
});

// 既にフォーカスがある状態で空欄クリック → 履歴再表示
els.category.addEventListener("click", () => {
  if (els.categorySuggest.hidden) {
    categorySuggestIndex = -1;
    renderCategorySuggest(els.category.value);
  }
});

// 候補リスト内のクリックでは入力欄からフォーカスを奪わない
els.tagSuggest.addEventListener("mousedown", (e) => {
  e.preventDefault();
});

// 候補リスト内のクリックでは入力欄からフォーカスを奪わない
els.categorySuggest.addEventListener("mousedown", (e) => {
  e.preventDefault();
});

// 枠外クリックで候補を閉じる
document.addEventListener("mousedown", (e) => {
  const tagWrap = els.tagInput.closest(".suggest-wrap");
  if (!els.tagSuggest.hidden && tagWrap && !tagWrap.contains(e.target)) {
    closeTagSuggest();
  }
  const categoryWrap = els.category.closest(".suggest-wrap");
  if (!els.categorySuggest.hidden && categoryWrap && !categoryWrap.contains(e.target)) {
    closeCategorySuggest();
  }
});

els.tagInput.addEventListener("keydown", (e) => {
  const items = els.tagSuggest.querySelectorAll(".suggest-item");

  if (e.key === "ArrowDown" && items.length) {
    e.preventDefault();
    tagSuggestIndex = Math.min(tagSuggestIndex + 1, items.length - 1);
    renderTagSuggest(els.tagInput.value);
    return;
  }
  if (e.key === "ArrowUp" && items.length) {
    e.preventDefault();
    tagSuggestIndex = Math.max(tagSuggestIndex - 1, 0);
    renderTagSuggest(els.tagInput.value);
    return;
  }
  if (e.key === "Tab" && items.length) {
    e.preventDefault();
    tagSuggestIndex = Math.min(tagSuggestIndex + 1, items.length - 1);
    renderTagSuggest(els.tagInput.value);
    return;
  }
  if (e.key === "Escape") {
    closeTagSuggest();
    return;
  }
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    if (tagSuggestIndex >= 0 && items[tagSuggestIndex]) {
      addTag(items[tagSuggestIndex].dataset.name);
    } else {
      addTag(els.tagInput.value);
    }
    closeTagSuggest();
  } else if (e.key === "Backspace" && els.tagInput.value === "" && tags.length) {
    tags.pop();
    renderTags();
    saveDraft();
  }
});

els.category.addEventListener("keydown", (e) => {
  const items = els.categorySuggest.querySelectorAll(".suggest-item");

  if (e.key === "ArrowDown" && items.length) {
    e.preventDefault();
    categorySuggestIndex = Math.min(categorySuggestIndex + 1, items.length - 1);
    renderCategorySuggest(els.category.value);
    return;
  }
  if (e.key === "ArrowUp" && items.length) {
    e.preventDefault();
    categorySuggestIndex = Math.max(categorySuggestIndex - 1, 0);
    renderCategorySuggest(els.category.value);
    return;
  }
  if (e.key === "Tab" && items.length) {
    e.preventDefault();
    categorySuggestIndex = Math.min(categorySuggestIndex + 1, items.length - 1);
    renderCategorySuggest(els.category.value);
    return;
  }
  if (e.key === "Escape") {
    closeCategorySuggest();
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    if (categorySuggestIndex >= 0 && items[categorySuggestIndex]) {
      els.category.value = items[categorySuggestIndex].dataset.name;
      saveDraft();
    }
    closeCategorySuggest();
  }
});

els.comment.addEventListener("input", saveDraft);
els.comment.addEventListener("input", updateTemplateEditorSummary);
els.addTemplate.addEventListener("click", openTemplateEditor);
els.templateCancel.addEventListener("click", closeTemplateEditor);
els.templateCreate.addEventListener("click", createTemplate);
els.templateTitle.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    closeTemplateEditor();
  } else if (e.key === "Enter") {
    e.preventDefault();
    createTemplate();
  }
});
els.favorite.addEventListener("change", saveDraft);

function setStatus(msg, kind) {
  els.status.textContent = msg;
  els.status.className = "status " + kind;
  els.status.hidden = false;
  els.status.style.animation = "none";
  void els.status.offsetWidth; // アニメーションを毎回再生するための再flow
  els.status.style.animation = "";
}

function renderThumbPreview() {
  const src = pendingThumbnail || (pageInfo && pageInfo.thumbnail_url) || "";
  if (src) {
    els.thumbPreview.src = src;
    els.thumbPreviewWrap.hidden = false;
  } else {
    els.thumbPreview.removeAttribute("src");
    els.thumbPreviewWrap.hidden = true;
  }
  // pickThumbは常に表示。選択済みの時だけ「デフォルトに戻す」を表示
  els.pickThumb.hidden = false;
  els.thumbReset.hidden = !pendingThumbnail;
}

async function saveDraft() {
  try {
    await chrome.storage.session.set({
      pendingDraft: {
        url: pageInfo ? pageInfo.url : null,
        comment: els.comment.value,
        category: els.category.value,
        tags: tags,
        favorite: els.favorite.checked,
      },
    });
  } catch (e) {}
}

async function loadDraft() {
  try {
    const data = await chrome.storage.session.get("pendingDraft");
    const draft = data && data.pendingDraft;
    if (draft && (!pageInfo || draft.url === pageInfo.url)) {
      els.comment.value = draft.comment || "";
      els.category.value = draft.category || "";
      tags = uniqueTagValues(draft.tags);
      els.favorite.checked = !!draft.favorite;
      renderTags();
    }
  } catch (e) {}
}

async function clearDraft() {
  try {
    await chrome.storage.session.remove("pendingDraft");
  } catch (e) {}
}

async function startThumbnailSelection() {
  await saveDraft();
  chrome.runtime.sendMessage({ type: "start-thumbnail-selection" });
  window.close();
}

els.pickThumb.addEventListener("click", startThumbnailSelection);
els.thumbReset.addEventListener("click", async () => {
  await clearPendingThumbnail();
  renderThumbPreview();
});

async function save() {
  if (!pageInfo) {
    setStatus("ページ情報を取得できませんでした", "err");
    return;
  }
  // タグ入力欄に未確定のテキストがある場合、確認ダイアログを表示
  if (els.tagInput.value.trim()) {
    if (!confirm("タグが確定されていませんが、そのまま続行しますか？\nEnterで確定出来ます。")) {
      return;
    }
  }
  // 重複URLチェック: 同じURLが既に保存されているか確認
  try {
    const duplicates = await api(`/clips?url=${encodeURIComponent(pageInfo.url)}`);
    if (Array.isArray(duplicates) && duplicates.length > 0) {
      if (!confirm(`このURLは既に保存されています（${duplicates.length}件）。追加で保存しますか？`)) {
        return;
      }
    }
  } catch (e) {
    // 重複チェック失敗は保存をブロックしない
  }
  els.save.disabled = true;

  const payload = {
    url: pageInfo.url,
    title: pageInfo.title,
    thumbnail_url: pageInfo.thumbnail_url,
    comment: els.comment.value.trim() || null,
    category: els.category.value.trim() || null,
    tags: tags,
  };

  try {
    // スクショを選んでいれば、アップロードして thumbnail_url を上書き
    if (pendingThumbnail) {
      const uploaded = await api("/uploads/thumbnail", {
        method: "POST",
        body: JSON.stringify({ data_url: pendingThumbnail }),
      });
      payload.thumbnail_url = uploaded.url;
    } else if (sourceTabId && pageInfo.thumbnail_url) {
      // ページ側で取得できる画像はローカル保存し、認証/CORS/ホットリンク制限を回避する。
      const imageDataUrl = await fetchPageThumbnailDataUrl(sourceTabId, pageInfo.thumbnail_url);
      if (imageDataUrl) {
        try {
          const uploaded = await api("/uploads/thumbnail", {
            method: "POST",
            body: JSON.stringify({ data_url: imageDataUrl }),
          });
          payload.thumbnail_url = uploaded.url;
        } catch (e) {
          // ローカル化に失敗した場合は元のURLで保存し、保存自体は継続する
        }
      }
    }

    const created = await api("/clips", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    // カテゴリ履歴は入力中や下書き保存では更新せず、クリップ保存成功時だけ追加する
    recordCategoryHistory(payload.category || "");
    // タグ履歴も同様に、実際に保存が成功したタグだけ記録する
    tags.forEach((name) => recordTagHistory(name));

    if (els.favorite.checked) {
      await api(`/clips/${created.id}/favorite`, { method: "PATCH" });
    }

    await clearPendingThumbnail();
    await clearDraft();

    setStatus("保存しました", "ok");
    setTimeout(() => window.close(), 1500);
  } catch (e) {
    setStatus("バックエンドに接続できません。アプリを起動してください。", "err");
    els.save.disabled = false;
  }
}

els.save.addEventListener("click", save);

// ページ内で直接実行する抽出ロジック (inject されるため自己完結させる)
function extractPageInfo() {
  function getMetaContent(selector) {
    const el = document.querySelector(selector);
    return el ? el.getAttribute("content") : null;
  }
  function resolveUrl(url) {
    if (typeof url !== "string" || !url.trim()) return null;
    try {
      const resolved = new URL(url.trim(), location.href);
      if (!["http:", "https:", "data:"].includes(resolved.protocol)) return null;
      return resolved.href;
    } catch (e) { return null; }
  }
  function getOgImage() {
    // 複数のOGP形式を順に試す
    return (
      getMetaContent('meta[property="og:image"]') ||
      getMetaContent('meta[property="og:image:url"]') ||
      getMetaContent('meta[property="og:image:secure_url"]') ||
      getMetaContent('meta[name="og:image"]') ||
      getMetaContent('meta[property="twitter:image"]') ||
      getMetaContent('meta[name="twitter:image"]') ||
      getMetaContent('meta[name="twitter:image:src"]') ||
      getMetaContent('meta[itemprop="image"]') ||
      getMetaContent('link[rel="image_src"][href]')
    );
  }
  function getYouTubeThumbnail(url) {
    // YouTube の動画IDをURLから抽出し、確実にサムネイルURLを生成する
    var match = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
    return match ? "https://img.youtube.com/vi/" + match[1] + "/maxresdefault.jpg" : null;
  }
  function getFavicon() {
    var cands = [
      'link[rel="icon"][href]',
      'link[rel="shortcut icon"][href]',
      'link[rel="apple-touch-icon"][href]',
    ];
    for (var i = 0; i < cands.length; i++) {
      var el = document.querySelector(cands[i]);
      if (el && el.getAttribute("href")) {
        var resolved = resolveUrl(el.getAttribute("href"));
        if (resolved) return resolved;
      }
    }
    return resolveUrl("/favicon.ico");
  }
  var url = location.href;
  return {
    title: document.title || null,
    url: url,
    thumbnail_url: getYouTubeThumbnail(url) || resolveUrl(getOgImage()) || getFavicon(),
  };
}

async function loadPageInfo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return null;
  sourceTabId = tab.id;

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPageInfo,
    });
    return results && results[0] ? results[0].result : null;
  } catch (e) {
    // chrome:// や拡張機能ページ等、スクリプトを実行できない場合
    return null;
  }
}

async function fetchPageThumbnailDataUrl(tabId, thumbnailUrl) {
  if (!tabId || !/^https?:\/\//i.test(String(thumbnailUrl || ""))) return null;
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [thumbnailUrl],
      func: async (imageUrl) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        try {
          const response = await fetch(imageUrl, {
            credentials: "include",
            signal: controller.signal,
          });
          if (!response.ok) return null;
          const blob = await response.blob();
          if (!blob.type.toLowerCase().startsWith("image/") || blob.size > 4 * 1024 * 1024) return null;
          return await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => resolve(null);
            reader.readAsDataURL(blob);
          });
        } catch {
          return null;
        } finally {
          clearTimeout(timeout);
        }
      },
    });
    return results?.[0]?.result || null;
  } catch {
    return null;
  }
}

async function clearPendingThumbnail() {
  pendingThumbnail = null;
  try {
    await chrome.storage.session.remove(["pendingThumbnail", "pendingThumbnailUrl"]);
    await chrome.action.setBadgeText({ text: "" });
  } catch (e) {
    // 無視
  }
}

async function loadPendingThumbnail() {
  try {
    const data = await chrome.storage.session.get([
      "pendingThumbnail",
      "pendingThumbnailUrl",
    ]);
    const sameTab =
      pageInfo && data.pendingThumbnailUrl === pageInfo.url;
    if (data.pendingThumbnail && sameTab) {
      pendingThumbnail = data.pendingThumbnail;
    } else {
      pendingThumbnail = null;
      if (data.pendingThumbnail) {
        // 別ページのスクショが残っていたので破棄する
        await chrome.storage.session.remove(["pendingThumbnail", "pendingThumbnailUrl"]);
        await chrome.action.setBadgeText({ text: "" });
      }
    }
  } catch (e) {
    pendingThumbnail = null;
  }
  renderThumbPreview();
}

async function init() {
  await loadTemplateState();
  pageInfo = await loadPageInfo();

  // YouTube サムネイルのフォールバック: maxresdefault が存在しない場合は hqdefault を使う
  if (pageInfo && pageInfo.thumbnail_url) {
    const m = pageInfo.thumbnail_url.match(/^(https:\/\/img\.youtube\.com\/vi\/[^/]+)\/maxresdefault\.jpg$/);
    if (m) {
      try {
        const img = new Image();
        img.src = pageInfo.thumbnail_url;
        await img.decode();
        if (img.naturalWidth <= 120) {
          pageInfo.thumbnail_url = m[1] + "/hqdefault.jpg";
        }
      } catch (e) {
        pageInfo.thumbnail_url = m[1] + "/hqdefault.jpg";
      }
    }
  }

  if (pageInfo) {
    els.pageTitle.textContent = pageInfo.title || "(タイトルなし)";
    els.pageUrl.textContent = pageInfo.url || "";
  } else {
    els.pageTitle.textContent = "ページ情報を取得できませんでした";
    els.pageUrl.textContent = "";
  }

  renderTags();
  await loadDraft();
  await loadPendingThumbnail();
  await loadSuggestions();
}

init();
