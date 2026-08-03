const API_BASE = "http://127.0.0.1:8000";

const $ = (id) => document.getElementById(id);

const els = {
  pageTitle: $("pageTitle"),
  pageUrl: $("pageUrl"),
  comment: $("comment"),
  category: $("category"),
  categorySuggest: $("categorySuggest"),
  tagBox: $("tagBox"),
  tagInput: $("tagInput"),
  tagSuggest: $("tagSuggest"),
  favorite: $("favorite"),
  save: $("save"),
  status: $("status"),
  pickThumb: $("pickThumb"),
  thumbPreviewWrap: $("thumbPreviewWrap"),
  thumbPreview: $("thumbPreview"),
  thumbReset: $("thumbReset"),
};

let pageInfo = null;
let tags = [];
let tagHistory = []; // 使用済みタグ履歴(新しい順、chrome.storage.localに永続化)
let categoryNames = []; // APIから取得した既存カテゴリ
let categoryHistory = []; // 保存済みカテゴリ履歴(新しい順、chrome.storage.localに永続化)
let tagSuggestIndex = -1; // キーボードでハイライト中の候補index
let categorySuggestIndex = -1; // キーボードでハイライト中のカテゴリ候補index
let pendingThumbnail = null; // スクショで選んだ data URL (未選択なら null)

async function api(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

async function loadSuggestions() {
  try {
    const categories = await api("/categories");
    categoryNames = Array.isArray(categories)
      ? categories
          .map((c) => (c && c.name ? String(c.name).trim() : ""))
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
}

function addTag(value) {
  const name = value.trim();
  if (name && !tags.includes(name)) {
    tags.push(name);
    renderTags();
    recordTagHistory(name);
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
  // ポップアップ内の残りスペースに合わせて表示件数を制限（最大7）
  const inputBottom = els.tagInput.getBoundingClientRect().bottom;
  const availHeight = window.innerHeight - inputBottom - 8;
  const itemHeight = 38;
  const maxCount = Math.max(1, Math.min(7, Math.floor(availHeight / itemHeight)));

  const list = tagHistory
    .filter((name) => !tags.includes(name))
    .filter((name) => !q || name.toLowerCase().includes(q))
    .slice(0, maxCount);
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
  els.tagSuggest.style.maxHeight = (list.length * itemHeight + 4) + "px";
  els.tagSuggest.hidden = false;
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
  return [...categoryHistory, ...categoryNames].filter(
    (name, index, list) => list.indexOf(name) === index
  );
}

function renderCategorySuggest(filterText) {
  const q = filterText.trim().toLowerCase();
  // 入力欄の上側に表示するため、上に残っている高さで件数を制限（最大7）
  const inputTop = els.category.getBoundingClientRect().top;
  const availHeight = inputTop - 8;
  const itemHeight = 38;
  const maxCount = Math.max(1, Math.min(7, Math.floor(availHeight / itemHeight)));

  const list = getCategorySuggestions()
    .filter((name) => !q || name.toLowerCase().includes(q))
    .slice(0, maxCount);
  if (!list.length) {
    closeCategorySuggest();
    return;
  }
  categorySuggestIndex = Math.min(categorySuggestIndex, list.length - 1);

  els.categorySuggest.innerHTML = list
    .map(
      (name, i) =>
        `<div id="categorySuggestOption${i}" class="suggest-item${i === categorySuggestIndex ? " active" : ""}" role="option" aria-selected="${i === categorySuggestIndex}" data-name="${escapeHtml(name)}">${escapeHtml(name)}</div>`
    )
    .join("");
  els.categorySuggest.style.maxHeight = list.length * itemHeight + 4 + "px";
  els.categorySuggest.hidden = false;
  els.category.setAttribute("aria-expanded", "true");
  if (categorySuggestIndex >= 0) {
    els.category.setAttribute("aria-activedescendant", `categorySuggestOption${categorySuggestIndex}`);
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
els.favorite.addEventListener("change", saveDraft);

function setStatus(msg, kind) {
  els.status.textContent = msg;
  els.status.className = "status " + kind;
  els.status.hidden = false;
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
      tags = Array.isArray(draft.tags) ? draft.tags : [];
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
    }

    const created = await api("/clips", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    // カテゴリ履歴は入力中や下書き保存では更新せず、クリップ保存成功時だけ追加する
    recordCategoryHistory(payload.category || "");

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
    try { return new URL(url, location.href).href; } catch (e) { return null; }
  }
  function getOgImage() {
    // 複数のOGP形式を順に試す
    return (
      getMetaContent('meta[property="og:image"]') ||
      getMetaContent('meta[name="og:image"]') ||
      getMetaContent('meta[name="twitter:image"]') ||
      getMetaContent('meta[itemprop="image"]')
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
        return resolveUrl(el.getAttribute("href"));
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
