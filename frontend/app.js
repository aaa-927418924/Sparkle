const API = window.location.origin;

const state = {
  clips: [],
  categories: [], // [{id, name}]
  tags: [],
  catMap: new Map(), // id -> name
  activeCategory: null, // name or null (= すべて)
  activeTags: [],
  favOnly: false,
  query: "",
  sortMode: localStorage.getItem("clipSortMode") || "date_desc",
  selectedIds: new Set(),
  dragOccurred: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  search: $("search"),
  searchSuggest: $("searchSuggest"),
  favOnly: $("favOnly"),
  sortSelect: $("sortSelect"),
  categories: $("categories"),
  grid: $("grid"),
  gridWrap: $("gridWrap"),
  empty: $("empty"),
  activeTag: $("activeTag"),
  activeTagName: $("activeTagName"),
  clearTag: $("clearTag"),
  addLocalBtn: $("addLocalBtn"),
  fileSaveMethod: $("fileSaveMethod"),
  fileSaveMethodDesc: $("fileSaveMethodDesc"),
  batchBar: $("batchBar"),
  batchCount: $("batchCount"),
  batchTagBtn: $("batchTagBtn"),
  batchCatBtn: $("batchCatBtn"),
  batchDelBtn: $("batchDelBtn"),
};

async function api(path) {
  const res = await fetch(API + path, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

let dataSignature = "";
let loadInFlight = false;
let clipGridHasRendered = false;

async function loadAll() {
  if (loadInFlight) return;
  loadInFlight = true;
  try {
    const [clips, categories, tags] = await Promise.all([
      api("/clips"),
      api("/categories"),
      api("/tags"),
    ]);

    // 拡張機能など別の画面から保存された場合も検知できるようにする。
    // 内容が変わっていないときは再描画せず、入力中の状態や選択を保つ。
    const nextSignature = JSON.stringify({ clips, categories, tags });
    if (nextSignature === dataSignature) return;
    dataSignature = nextSignature;

    const clipIds = new Set(clips.map((clip) => clip.id));
    state.selectedIds = new Set(
      [...state.selectedIds].filter((id) => clipIds.has(id))
    );
    state.clips = clips;
    state.categories = categories;
    state.tags = tags;
    // ランダム順用の固定シード(データ更新時に新しい順序になる)
    state.clips.forEach((c) => {
      c._rand = Math.random();
    });
    state.catMap = new Map(categories.map((c) => [c.id, c.name]));
    setSortValue(state.sortMode);
    renderCategories();
    render();
  } finally {
    loadInFlight = false;
  }
}

function renderCategories() {
  const all = [{ id: null, name: "すべて" }, ...state.categories];
  els.categories.innerHTML = all
    .map((c) => {
      const isAll = c.id === null;
      const active =
        (isAll && state.activeCategory === null) ||
        (!isAll && state.activeCategory === c.name)
          ? " active"
          : "";
      const label = isAll ? "すべて" : escapeHtml(c.name);
      return `<button class="cat-btn${active}" data-cat="${isAll ? "" : escapeHtml(c.name)}">${label}</button>`;
    })
    .join("");

  els.categories.querySelectorAll(".cat-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = btn.dataset.cat;
      state.activeCategory = v === "" ? null : v;
      renderCategories();
      render();
      const sel = els.categories.querySelector(".cat-btn.active");
      if (sel) sel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    btn.addEventListener("contextmenu", (e) => {
      const name = btn.dataset.cat;
      if (!name) return;
      e.preventDefault();
      e.stopPropagation();
      const cat = state.categories.find((c) => c.name === name);
      if (!cat) return;
      showContextMenu(e, [{ label: "カテゴリを削除", action: () => deleteManaged("category", cat.id, { anchor: btn }) }]);
    });
  });
}

function matches(clip) {
  if (state.activeCategory && state.catMap.get(clip.category_id) !== state.activeCategory) {
    return false;
  }
  if (state.activeTags.length) {
    const has = state.activeTags.every((tag) => (clip.tags || []).some((t) => t.name === tag));
    if (!has) return false;
  }
  if (state.favOnly && !clip.is_favorite) {
    return false;
  }
  const q = state.query.trim().toLowerCase();
  if (q) {
    const hay = [
      clip.title || "",
      clip.comment || "",
      ...(clip.tags || []).map((t) => t.name),
    ]
      .join(" ")
      .toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function isLocalClip(clip) {
  return clip.url && clip.url.startsWith("local://");
}

function localFileName(clip) {
  if (!isLocalClip(clip)) return "";
  const parts = clip.url.split("/");
  return parts[parts.length - 1];
}

function localFilePath(url) {
  if (url.startsWith("local://reference/")) return url.slice("local://reference/".length);
  if (url.startsWith("local://copy/")) return url.slice("local://copy/".length);
  return url;
}

async function resolveLocalFilePath(clip) {
  const url = clip.url || "";
  if (url.startsWith("local://reference/")) return localFilePath(url);

  const res = await fetch(`${API}/clips/${clip.id}/path`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!data.path) throw new Error("File path is missing");
  return data.path;
}

function localFileExt(clip) {
  const name = localFileName(clip);
  return (name.split(".").pop() || "").toLowerCase();
}

const TEXT_EXTS = new Set(["txt","md","json","csv","log","xml","yaml","yml","toml","ini","cfg","conf","py","js","ts","html","css","java","c","cpp","h","rs","go","rb","php","sh","bat","sql"]);
const IMAGE_EXTS = new Set(["png","jpg","jpeg","gif","webp","bmp","ico"]);
const VIDEO_EXTS = new Set(["mp4","webm","ogg","mov","avi","mkv"]);

function isTextExt(ext) { return TEXT_EXTS.has(ext); }
function isImageExt(ext) { return IMAGE_EXTS.has(ext); }
function isVideoExt(ext) { return VIDEO_EXTS.has(ext); }

function fileIconHtml(ext) {
  return '';
}

function cardThumbnailSrc(clip) {
  const src = clip.thumbnail_url;
  if (!src) return "";
  if (src.startsWith("/") || src.startsWith(API) || src.startsWith("data:")) return src;
  return `${API}/thumbnail-proxy?url=${encodeURIComponent(src)}`;
}

function cardHtml(clip, { animate = false, index = 0 } = {}) {
  const local = isLocalClip(clip);
  const ext = local ? localFileExt(clip) : "";

  let imgHtml;
  if (clip.thumbnail_url) {
    imgHtml = `<img class="card-img" src="${escapeAttr(cardThumbnailSrc(clip))}" alt="" loading="lazy" draggable="false"
         onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'card-ph',textContent:'🖼'}))" />`;
  } else if (local && isTextExt(ext)) {
    imgHtml = `<div class="card-ph card-ph-text" data-text-preview="${clip.id}"><div class="card-text-loading">読み込み中…</div></div>`;
  } else if (local) {
    imgHtml = `<div class="card-ph">${fileIconHtml(ext)}</div>`;
  } else {
    imgHtml = `<div class="card-ph">🖼</div>`;
  }

  const favOn = clip.is_favorite ? " on" : "";
  const favIcon = clip.is_favorite ? "★" : "☆";

  const tags = (clip.tags || [])
    .map((t) => `<button class="tag-chip" data-tag="${escapeAttr(t.name)}">${escapeHtml(t.name)}</button>`)
    .join("");

  const sel = state.selectedIds.has(clip.id) ? " selected" : "";
  const entryClass = animate ? " page-enter-card" : "";
  const entryStyle = animate ? ` style="--page-enter-index:${index}"` : "";
  return `
    <article class="card${local ? " local-clip" : ""}${sel}${entryClass}" data-id="${clip.id}" data-url="${escapeAttr(clip.url || "")}"${entryStyle} draggable="false">
      <div class="card-actions">
        <button class="act-btn pin-btn${isPinned(clip.id, 'clip') ? ' on' : ''}" data-pin="${clip.id}" data-pin-type="clip" title="ピン止め"><img class="icon icon-btn" src="icons/clip2.svg" alt="ピン" /></button>
        <button class="act-btn" data-copy="${clip.id}" title="${local ? "ファイルパスをコピー" : "リンクをコピー"}"><img class="icon icon-btn" src="icons/clipboard.svg" alt="コピー" /></button>
        ${local ? `<button class="act-btn" data-explorer="${clip.id}" title="エクスプローラーで表示"><img class="icon icon-btn" src="icons/folder.svg" alt="表示" /></button>` : ""}
        <button class="fav-btn${favOn}" data-fav="${clip.id}" title="お気に入り">${favIcon}</button>
        <button class="act-btn" data-edit="${clip.id}" title="編集"><img class="icon icon-btn" src="icons/pencil.svg" alt="編集" /></button>
        <button class="act-btn" data-del="${clip.id}" title="削除"><img class="icon icon-btn" src="icons/trash.svg" alt="削除" /></button>
      </div>
      ${imgHtml}
      <div class="card-caption">
        <div class="card-title">${escapeHtml(clip.title || "(無題)")}</div>
        ${clip.comment ? `<div class="card-comment">${escapeHtml(clip.comment)}</div>` : ""}
      </div>
      <div class="tags">${tags}</div>
    </article>`;
}

function recordOpened(id) {
  const raw = localStorage.getItem("clipOpenedAt");
  const map = raw ? JSON.parse(raw) : {};
  map[id] = Date.now();
  localStorage.setItem("clipOpenedAt", JSON.stringify(map));
  // 最近開いた順の場合はその場で並び替えを反映する(リロード不要)
  if (state.sortMode === "recent_opened") render();
}

function sortClips(list) {
  const arr = list.slice();
  if (state.sortMode === "title") {
    arr.sort((a, b) => (a.title || "").localeCompare(b.title || "", "ja"));
  } else if (state.sortMode === "recent_opened") {
    const raw = localStorage.getItem("clipOpenedAt");
    const opened = raw ? JSON.parse(raw) : {};
    arr.sort((a, b) => (opened[b.id] || 0) - (opened[a.id] || 0));
  } else if (state.sortMode === "random") {
    arr.sort((a, b) => (a._rand ?? 0) - (b._rand ?? 0));
  } else {
    arr.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  }
  return arr;
}

function gridColCount() {
  const w = document.documentElement.clientWidth;
  if (w <= 380) return 1;
  if (w <= 560) return 2;
  if (w <= 820) return 3;
  if (w <= 1180) return 4;
  return 5;
}

function render() {
  const list = sortClips(state.clips.filter(matches));
  const animateInitial = !clipGridHasRendered;
  // マルチカラム(縦方向に埋める)の見た目は維持しつつ、
  // 表示順は左上→右上(行優先)になるようカラムへ交互に配分する
  const colCount = gridColCount();
  const cols = [];
  for (let c = 0; c < colCount; c++) {
    const col = document.createElement("div");
    col.className = "grid-col";
    cols.push(col);
  }
  list.forEach((clip, index) => {
    cols[index % colCount].insertAdjacentHTML(
      "beforeend",
      cardHtml(clip, { animate: animateInitial, index })
    );
  });
  els.grid.replaceChildren(...cols);
  if (animateInitial) {
    bindPageEntryAnimation(els.grid);
    clipGridHasRendered = true;
  }

  if (state.activeTags.length) {
    els.activeTag.hidden = false;
    els.activeTagName.textContent = state.activeTags.join(", ");
  } else {
    els.activeTag.hidden = true;
  }

  els.empty.hidden = list.length > 0;

  // お気に入りボタン
  els.grid.querySelectorAll("[data-fav]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFav(Number(btn.dataset.fav), btn);
    });
  });

  // タグチップ
  els.grid.querySelectorAll(".tag-chip").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const tag = btn.dataset.tag;
      const idx = state.activeTags.indexOf(tag);
      if (idx >= 0) state.activeTags.splice(idx, 1);
      else state.activeTags.push(tag);
      render();
    });
    btn.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const name = btn.dataset.tag;
      const tag = state.tags.find((t) => t.name === name);
      if (!tag) return;
      showContextMenu(e, [{ label: "タグを削除", action: () => deleteManaged("tag", tag.id, { anchor: btn }) }]);
    });
  });

  // カード本体クリック
  els.grid.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      if (suppressNextCardClick) {
        suppressNextCardClick = false;
        return;
      }
      const id = Number(card.dataset.id);
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        toggleSelection(id);
        return;
      }
      if (state.selectedIds.size > 0) clearSelection();
      const url = card.dataset.url;
      if (!url) return;
      if (url.startsWith("local://")) {
        recordOpened(id);
        openLocalFile(id);
      } else {
        recordOpened(id);
        window.open(url, "_blank", "noopener");
      }
    });
  });

  // テキストファイルのプレビュー読み込み
  els.grid.querySelectorAll("[data-text-preview]").forEach((ph) => {
    const id = ph.dataset.textPreview;
    fetch(`${API}/clips/${id}/text-preview`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data && data.preview) {
          ph.textContent = data.preview;
          ph.classList.add("loaded");
        } else {
          ph.textContent = "（プレビューなし）";
        }
      })
      .catch(() => { ph.textContent = "（プレビューなし）"; });
  });

  // 編集ボタン
  els.grid.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openEditModal(Number(btn.dataset.edit));
    });
  });

  // 削除ボタン
  els.grid.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteClip(Number(btn.dataset.del), {
        anchor: btn.closest(".card"),
        immediate: e.shiftKey,
      });
    });
  });

  // ピンボタン
  els.grid.querySelectorAll("[data-pin]").forEach((btn) => {
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

  // リンクコピーボタン
  els.grid.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.copy);
      const clip = state.clips.find((c) => c.id === id);
      if (!clip) return;
      const url = clip.url || "";
      if (!url) return;
      try {
        const text = isLocalClip(clip) ? await resolveLocalFilePath(clip) : url;
        await navigator.clipboard.writeText(text);
        const orig = btn.innerHTML;
        btn.innerHTML = "✓";
        setTimeout(() => { btn.innerHTML = orig; }, 1200);
      } catch { /* fallback */ }
    });
  });

  // エクスプローラーで表示ボタン
  els.grid.querySelectorAll("[data-explorer]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.explorer);
      fetch(`${API}/clips/${id}/explorer`, { method: "POST" }).catch(() => {});
    });
  });

  updateBatchBar();
}

function bindPageEntryAnimation(container) {
  container.querySelectorAll(".page-enter-card").forEach((card) => {
    card.addEventListener("animationend", () => {
      card.classList.remove("page-enter-card");
      card.style.removeProperty("--page-enter-index");
    }, { once: true });
  });
}

// ==================== 範囲選択（ラバーバンド） ====================

let rubberBandActive = false;
let rubberBandStartX = 0;
let rubberBandStartY = 0;
let rubberBandEl = null;
let rubberBandAdditive = false;
let suppressNextCardClick = false;

function rectsOverlap(a, b) {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
}

function cancelRubberBand() {
  rubberBandActive = false;
  if (rubberBandEl) {
    rubberBandEl.remove();
    rubberBandEl = null;
  }
  // dragOccurred は呼び出し元で管理する（ここでは触らない）
}

const mainEl = document.querySelector(".main");

mainEl.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  cancelRubberBand();
  // カード上での mousedown は dragOccurred をリセットしない（後続の click で drag 後のブロックに使う）
  if (e.target.closest(".card") || e.target.closest("button") || e.target.closest("select") || e.target.closest("input")) return;
  // 空き領域 → 新しいラバーバンド開始。ここで dragOccurred をリセット
  state.dragOccurred = false;
  suppressNextCardClick = false;
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
  // --- ラバーバンド中にマウスアップ → 範囲確定またはクリック ---
  if (rubberBandActive && rubberBandEl) {
    const bandRect = rubberBandEl.getBoundingClientRect();
    const preserveSelection = rubberBandAdditive;
    const suppressClickFromThisDrag = Boolean(e.target.closest(".card"));
    cancelRubberBand();
    if (!state.dragOccurred) {
      // ドラッグなし＝単なるクリック → 空き領域なら選択解除
      if (!e.target.closest(".card") && !e.target.closest("button") && !e.target.closest("select") && !e.target.closest("input")) {
        if (state.selectedIds.size > 0 && !preserveSelection) clearSelection();
      }
      return;
    }
    // ドラッグあり → 範囲選択を適用
    if (!preserveSelection) clearSelection();
    els.grid.querySelectorAll(".card").forEach((card) => {
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
    // ドラッグ直後にブラウザが発生させるクリックだけを抑制する。
    // 空白でドラッグを終えた場合は次のユーザー操作へ持ち越さない。
    state.dragOccurred = false;
    suppressNextCardClick = suppressClickFromThisDrag;
    if (suppressNextCardClick) {
      window.setTimeout(() => { suppressNextCardClick = false; }, 0);
    }
    return;
  }

  // --- ラバーバンド外のマウスアップ（カード上でのクリックなど）→ 何もしない ---
});

// Escape でラバーバンド中断＋選択解除
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    cancelRubberBand();
    state.dragOccurred = false;
    suppressNextCardClick = false;
    if (state.selectedIds.size > 0) clearSelection();
  }
});

// ==================== 一括操作 ====================

async function batchTag() {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  const input = prompt("追加するタグをカンマ区切りで入力してください：");
  if (!input) return;
  const newTags = input.split(/[,，]/).map((t) => t.trim()).filter(Boolean);
  if (!newTags.length) return;
  clearSelection();
  let ok = 0, fail = 0;
  for (const id of ids) {
    try {
      const clip = state.clips.find((c) => c.id === id);
      const merged = [...new Set([...(clip.tags || []).map((t) => t.name), ...newTags])];
      const res = await fetch(`${API}/clips/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags: merged }),
      });
      if (res.ok) ok++; else fail++;
    } catch { fail++; }
  }
  await loadAll();
  await Promise.all(ids.map((id) => window.refreshPinnedData?.("clip", id)));
  await window.refreshAllPinnedProjects?.();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
}

async function batchCategory() {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  const catNames = state.categories.map((c) => c.name);
  const msg = "カテゴリ名を入力してください（クリアするには空のままOKを押す）：\n\n既存のカテゴリ:\n" + catNames.join(", ");
  const input = prompt(msg);
  if (input === null) return;
  const cat = input.trim() || null;
  clearSelection();
  let ok = 0, fail = 0;
  for (const id of ids) {
    try {
      const res = await fetch(`${API}/clips/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: cat }),
      });
      if (res.ok) ok++; else fail++;
    } catch { fail++; }
  }
  await loadAll();
  await Promise.all(ids.map((id) => window.refreshPinnedData?.("clip", id)));
  await window.refreshAllPinnedProjects?.();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
}

async function batchDelete(event) {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  if (!(await window.confirmDeletion(`${ids.length}件のクリップを削除します。`, {
    anchor: els.batchDelBtn,
    immediate: Boolean(event?.shiftKey),
  }))) return;
  clearSelection();
  let ok = 0, fail = 0;
  for (const id of ids) {
    try {
      const res = await fetch(`${API}/clips/${id}`, { method: "DELETE" });
      if (res.ok) ok++; else fail++;
    } catch { fail++; }
  }
  await loadAll();
  await window.refreshAllPinned?.("clip");
  await window.refreshAllPinnedProjects?.();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
}

async function toggleFav(id, btn) {
  const clip = state.clips.find((c) => c.id === id);
  const optimistic = !clip.is_favorite;
  // 楽観的更新
  clip.is_favorite = optimistic;
  btn.classList.toggle("on", optimistic);
  btn.textContent = optimistic ? "★" : "☆";
  try {
    await fetch(`${API}/clips/${id}/favorite`, { method: "PATCH" });
  } catch (e) {
    // 失敗時は巻き戻し
    clip.is_favorite = !optimistic;
    btn.classList.toggle("on", !optimistic);
    btn.textContent = !optimistic ? "★" : "☆";
  }
}

async function deleteClip(id, options = {}) {
  if (!(await window.confirmDeletion("このクリップを削除します。", options))) return;
  try {
    const res = await fetch(`${API}/clips/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.clips = state.clips.filter((c) => c.id !== id);
    state.selectedIds.delete(id);
    render();
  } catch (e) {
    alert("削除に失敗しました。");
  }
}

// --- クリップ編集モーダル ---
const editEls = {
  modal: $("editModal"),
  title: $("editTitle"),
  comment: $("editComment"),
  category: $("editCategory"),
  categoryClear: $("editCategoryClear"),
  categorySuggest: $("editCategorySuggest"),
  tagBox: $("editTagBox"),
  tagInput: $("editTagInput"),
  tagSuggest: $("editTagSuggest"),
  thumbPreview: $("editThumbPreview"),
  thumbBtn: $("editThumbBtn"),
  thumbFile: $("editThumbFile"),
  cancel: $("editCancel"),
  save: $("editSave"),
};
let editTags = [];
let editTargetId = null;
let editThumbnailUrl = null; // 保存待ちの新しいサムネイルURL(未変更ならnull)

function setEditThumbPreview(url) {
  if (url) {
    editEls.thumbPreview.src = url;
    editEls.thumbPreview.hidden = false;
  } else {
    editEls.thumbPreview.removeAttribute("src");
    editEls.thumbPreview.hidden = true;
  }
}

editEls.thumbBtn.addEventListener("click", () => editEls.thumbFile.click());

editEls.thumbFile.addEventListener("change", () => {
  const file = editEls.thumbFile.files && editEls.thumbFile.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const res = await fetch(`${API}/uploads/thumbnail`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_url: reader.result }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      editThumbnailUrl = data.url;
      setEditThumbPreview(data.url);
    } catch (e) {
      alert("画像のアップロードに失敗しました。");
    } finally {
      editEls.thumbFile.value = "";
    }
  };
  reader.readAsDataURL(file);
});

function renderEditTags() {
  editEls.tagBox.innerHTML = editTags
    .map(
      (t, i) =>
        `<span class="tag">${escapeHtml(t)}<button data-i="${i}" title="削除">×</button></span>`
    )
    .join("");
  editEls.tagBox.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      editTags.splice(Number(b.dataset.i), 1);
      renderEditTags();
    });
  });
}

function addEditTag(value) {
  const name = value.trim();
  if (name && !editTags.includes(name)) {
    editTags.push(name);
    renderEditTags();
  }
  editEls.tagInput.value = "";
}

const editSuggestState = {
  category: { index: -1, input: editEls.category, list: editEls.categorySuggest },
  tag: { index: -1, input: editEls.tagInput, list: editEls.tagSuggest },
};

function getEditSuggestionNames(type) {
  if (type === "category") return state.categories.map((category) => category.name);
  return state.tags
    .map((tag) => tag.name)
    .filter((name) => !editTags.includes(name));
}

function closeEditSuggestions(type) {
  const suggestion = editSuggestState[type];
  if (!suggestion) return;
  suggestion.index = -1;
  suggestion.list.hidden = true;
  suggestion.list.innerHTML = "";
  suggestion.input.setAttribute("aria-expanded", "false");
  suggestion.input.removeAttribute("aria-activedescendant");
}

function renderEditSuggestions(type) {
  const suggestion = editSuggestState[type];
  if (!suggestion) return;
  const query = suggestion.input.value.trim().toLowerCase();
  const names = getEditSuggestionNames(type)
    .filter((name) => !query || name.toLowerCase().includes(query));

  if (!names.length) {
    closeEditSuggestions(type);
    return;
  }

  suggestion.index = Math.min(suggestion.index, names.length - 1);
  suggestion.list.innerHTML = names
    .map((name, index) => {
      const active = index === suggestion.index;
      const optionId = `edit-${type}-suggest-${index}`;
      return `<div id="${optionId}" class="edit-suggest-item${active ? " active" : ""}" role="option" aria-selected="${active}" data-value="${escapeAttr(name)}">${escapeHtml(name)}</div>`;
    })
    .join("");
  suggestion.list.hidden = false;
  suggestion.input.setAttribute("aria-expanded", "true");
  if (suggestion.index >= 0) {
    suggestion.input.setAttribute("aria-activedescendant", `edit-${type}-suggest-${suggestion.index}`);
  } else {
    suggestion.input.removeAttribute("aria-activedescendant");
  }

  suggestion.list.querySelectorAll(".edit-suggest-item").forEach((item) => {
    item.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
    });
    item.addEventListener("click", () => {
      selectEditSuggestion(type, item.dataset.value || "");
    });
  });
}

function selectEditSuggestion(type, value) {
  if (!value) return;
  if (type === "category") {
    editEls.category.value = value;
  } else {
    addEditTag(value);
  }
  closeEditSuggestions(type);
}

function moveEditSuggestion(type, direction) {
  const suggestion = editSuggestState[type];
  const items = suggestion.list.querySelectorAll(".edit-suggest-item");
  if (!items.length) return false;
  suggestion.index = suggestion.index < 0
    ? (direction < 0 ? items.length - 1 : 0)
    : Math.max(0, Math.min(suggestion.index + direction, items.length - 1));
  renderEditSuggestions(type);
  return true;
}

editEls.category.addEventListener("focus", () => renderEditSuggestions("category"));
editEls.category.addEventListener("click", () => {
  if (editEls.categorySuggest.hidden) renderEditSuggestions("category");
});
editEls.category.addEventListener("input", () => {
  editSuggestState.category.index = -1;
  renderEditSuggestions("category");
});
editEls.category.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" && moveEditSuggestion("category", 1)) {
    event.preventDefault();
  } else if (event.key === "ArrowUp" && moveEditSuggestion("category", -1)) {
    event.preventDefault();
  } else if (event.key === "Enter" && editSuggestState.category.index >= 0) {
    const item = editEls.categorySuggest.querySelectorAll(".edit-suggest-item")[editSuggestState.category.index];
    if (item) {
      event.preventDefault();
      selectEditSuggestion("category", item.dataset.value || "");
    }
  } else if (event.key === "Escape") {
    closeEditSuggestions("category");
  }
});

editEls.tagInput.addEventListener("focus", () => renderEditSuggestions("tag"));
editEls.tagInput.addEventListener("click", () => {
  if (editEls.tagSuggest.hidden) renderEditSuggestions("tag");
});
editEls.tagInput.addEventListener("input", () => {
  editSuggestState.tag.index = -1;
  renderEditSuggestions("tag");
});
editEls.tagInput.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" && moveEditSuggestion("tag", 1)) {
    event.preventDefault();
    return;
  }
  if (event.key === "ArrowUp" && moveEditSuggestion("tag", -1)) {
    event.preventDefault();
    return;
  }
  if (event.key === "Escape") {
    closeEditSuggestions("tag");
    return;
  }
  if (event.key === "Enter" || event.key === ",") {
    event.preventDefault();
    const items = editEls.tagSuggest.querySelectorAll(".edit-suggest-item");
    const value = editSuggestState.tag.index >= 0 && items[editSuggestState.tag.index]
      ? items[editSuggestState.tag.index].dataset.value
      : editEls.tagInput.value;
    addEditTag(value || "");
    closeEditSuggestions("tag");
  } else if (event.key === "Backspace" && editEls.tagInput.value === "" && editTags.length) {
    editTags.pop();
    renderEditTags();
    renderEditSuggestions("tag");
  }
});

document.addEventListener("mousedown", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  Object.entries(editSuggestState).forEach(([type, suggestion]) => {
    const wrap = suggestion.input.closest(".edit-suggest-wrap");
    if (suggestion.list.hidden || (wrap && wrap.contains(target))) return;
    closeEditSuggestions(type);
  });
});

function openEditModal(id) {
  const clip = state.clips.find((c) => c.id === id);
  if (!clip) return;
  editTargetId = id;
  editThumbnailUrl = null;
  setEditThumbPreview(clip.thumbnail_url || null);
  editEls.title.value = clip.title || "";
  editEls.comment.value = clip.comment || "";
  editEls.category.value = state.catMap.get(clip.category_id) || "";
  editTags = (clip.tags || []).map((t) => t.name);
  renderEditTags();
  closeEditSuggestions("category");
  closeEditSuggestions("tag");
  editEls.modal.hidden = false;
}

function closeEditModal() {
  closeEditSuggestions("category");
  closeEditSuggestions("tag");
  editEls.modal.hidden = true;
  editTargetId = null;
}

editEls.cancel.addEventListener("click", closeEditModal);
editEls.categoryClear.addEventListener("click", () => {
  editEls.category.value = "";
  closeEditSuggestions("category");
});
// ドラッグしてダイアログの外で離すと click の target が共通祖先(モーダル全体)になるため、
// 押下がモーダル内部で始まった場合は外側クリックとみなさず閉じない。
let editPressStartedOnBackdrop = false;
editEls.modal.addEventListener("pointerdown", (e) => {
  editPressStartedOnBackdrop = e.target === editEls.modal;
});
editEls.modal.addEventListener("click", (e) => {
  if (e.target === editEls.modal && editPressStartedOnBackdrop) closeEditModal();
});

editEls.save.addEventListener("click", async () => {
  if (editTargetId == null) return;
  const payload = {
    title: editEls.title.value.trim() || null,
    comment: editEls.comment.value.trim() || null,
    category: editEls.category.value.trim() || null,
    tags: editTags,
  };
  if (editThumbnailUrl) {
    payload.thumbnail_url = editThumbnailUrl;
  }
  try {
    const clipId = editTargetId;
    const res = await fetch(`${API}/clips/${editTargetId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    closeEditModal();
    await loadAll(); // クリップ・カテゴリ・タグを全部再取得して同期する
    await window.refreshPinnedData?.("clip", clipId);
    await window.refreshAllPinnedProjects?.();
  } catch (e) {
    alert("更新に失敗しました。");
  }
});

// --- 設定モーダル（カテゴリ・タグ管理） ---
async function deleteManaged(type, id, options = {}) {
  const path = type === "category" ? `/categories/${id}` : `/tags/${id}`;
  if (!(await window.confirmDeletion(
    `この${type === "category" ? "カテゴリ" : "タグ"}を削除します。`,
    options,
  ))) return;
  try {
    const res = await fetch(API + path, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await loadAll();
    if (type === "tag") await window.refreshAllPinned?.("clip");
    await window.refreshAllPinnedProjects?.();
  } catch (e) {
    alert("削除に失敗しました。");
  }
}

// コンテキストメニュー（タグ・カテゴリ削除用）
let ctxTarget = null;
function showContextMenu(e, items) {
  hideContextMenu();
  ctxTarget = e.target;
  const menu = document.createElement("div");
  menu.className = "ctx-menu";
  menu.style.left = e.clientX + "px";
  menu.style.top = e.clientY + "px";
  menu.innerHTML = items.map((item) => `<button class="ctx-item">${escapeHtml(item.label)}</button>`).join("");
  menu.querySelectorAll(".ctx-item").forEach((btn, i) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      items[i].action();
      hideContextMenu();
    });
  });
  document.body.appendChild(menu);
  requestAnimationFrame(() => { menu.style.opacity = "1"; });
}
function hideContextMenu() {
  document.querySelectorAll(".ctx-menu").forEach((el) => el.remove());
  ctxTarget = null;
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".ctx-menu")) hideContextMenu();
});
document.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".ctx-menu")) { e.preventDefault(); hideContextMenu(); }
});

// サイドバー
document.querySelectorAll(".side-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const nav = btn.dataset.nav;
    if (nav === "settings") window.openSettings();
  });
});

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

// ==================== 複数選択 ====================

function getSelectedClips() {
  return state.clips.filter((c) => state.selectedIds.has(c.id));
}

function updateBatchBar() {
  const n = state.selectedIds.size;
  els.batchBar.classList.toggle("visible", n > 0);
  if (n > 0) {
    els.batchCount.textContent = `${n}件選択`;
  }
}

function clearSelection() {
  state.selectedIds.clear();
  updateBatchBar();
  els.grid.querySelectorAll(".card.selected").forEach((card) => card.classList.remove("selected"));
}

function toggleSelection(id) {
  if (state.selectedIds.has(id)) {
    state.selectedIds.delete(id);
  } else {
    state.selectedIds.add(id);
  }
  const card = els.grid.querySelector(`.card[data-id="${id}"]`);
  if (card) card.classList.toggle("selected");
  updateBatchBar();
}

// 検索実行（履歴選択・Enterコミット・既存の入力から共通で呼ぶ）
function runSearch(q) {
  state.query = q;
  els.search.value = q;
  render();
}

let searchDragPressed = false;
let searchDragSelecting = false;
let searchDragStartX = 0;
let searchDragStartY = 0;

function restoreSearchFocus() {
  if (document.activeElement === els.search) return;
  els.search.focus({ preventScroll: true });
  const ov = document.getElementById("searchOverlay");
  if (ov) ov.classList.add("show");
}

let suppressSearchOutsideClick = false;

function blockSearchOutsideInteraction(e) {
  const ov = document.getElementById("searchOverlay");
  const searchActive = document.activeElement === els.search;
  const overlayActive = Boolean(ov && ov.classList.contains("show"));
  const target = e.target instanceof Element ? e.target : null;

  if (!target || target.closest("#searchWrap") || target.closest(".sidebar")) return;
  if (!searchActive && !overlayActive && !suppressSearchOutsideClick) return;

  e.preventDefault();
  e.stopImmediatePropagation();

  if (e.type === "mousedown") {
    suppressSearchOutsideClick = true;
    window.setTimeout(() => {
      suppressSearchOutsideClick = false;
    }, 0);
  } else if (e.type === "click") {
    suppressSearchOutsideClick = false;
  }

  if (ov) ov.classList.remove("show");
  const suggest = document.getElementById("searchSuggest");
  if (suggest) suggest.hidden = true;
  els.search.blur();
}

document.addEventListener("mousedown", blockSearchOutsideInteraction, true);
document.addEventListener("click", blockSearchOutsideInteraction, true);

els.search.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  searchDragPressed = true;
  searchDragSelecting = false;
  searchDragStartX = e.clientX;
  searchDragStartY = e.clientY;
});

document.addEventListener("mousemove", (e) => {
  if (!searchDragPressed) return;
  if (Math.hypot(e.clientX - searchDragStartX, e.clientY - searchDragStartY) > 4) {
    searchDragSelecting = true;
  }
});

document.addEventListener("mouseup", () => {
  if (!searchDragPressed) return;
  const wasSelecting = searchDragSelecting;
  searchDragPressed = false;
  searchDragSelecting = false;
  if (wasSelecting) requestAnimationFrame(restoreSearchFocus);
});

// 検索フォーカス ビネット効果
els.search.addEventListener("focus", () => {
  const ov = document.getElementById("searchOverlay");
  if (ov) ov.classList.add("show");
});
els.search.addEventListener("blur", () => {
  if (searchDragPressed || searchDragSelecting) return;
  const ov = document.getElementById("searchOverlay");
  if (ov) ov.classList.remove("show");
});
els.search.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const ov = document.getElementById("searchOverlay");
    if (ov) ov.classList.remove("show");
    const suggest = document.getElementById("searchSuggest");
    if (suggest) suggest.hidden = true;
    els.search.blur();
  }
});
document.addEventListener("click", (e) => {
  const ov = document.getElementById("searchOverlay");
  if (ov && ov.classList.contains("show") && !e.target.closest("#searchWrap")) {
    ov.classList.remove("show");
    els.search.blur();
  }
  const sort = document.getElementById("sortSelect");
  if (sort && !e.target.closest("#sortSelect")) {
    closeSortDropdown();
    sort.blur();
  }
});

// ウィンドウ外クリック（タスクバー等）でフォーカス状態を強制解除
window.addEventListener("blur", () => {
  if (searchDragPressed || searchDragSelecting) return;
  const ov = document.getElementById("searchOverlay");
  if (ov) ov.classList.remove("show");
  const suggest = document.getElementById("searchSuggest");
  if (suggest) suggest.hidden = true;
  els.search.blur();
  closeSortDropdown();
});

// スティッキーヘッダー スクロール検出 — グリッドがヘッダー裏に隠れたらオーバーレイ
(function() {
  const header = document.getElementById("stickyHeader");
  const gridWrap = document.getElementById("gridWrap");
  if (!header || !gridWrap) return;
  const check = () => {
    const hb = header.getBoundingClientRect().bottom;
    const gt = gridWrap.getBoundingClientRect().top;
    const isScrolled = document.body.scrollTop > 8 || window.scrollY > 8;
    const wasScrolled = header.classList.contains("scrolled");
    header.classList.toggle("scrolled", isScrolled);
    document.body.classList.toggle("page-scrolled", isScrolled);
    if (isScrolled) {
      closeSortDropdown();
      els.sortSelect.blur();
    }
  };
  window.addEventListener("scroll", check, { passive: true });
  document.body.addEventListener("scroll", check, { passive: true });
  check();
})();

// イベント
els.search.addEventListener("input", (e) => {
  state.query = e.target.value;
  render();
});

// 検索履歴サジェスト（検索処理とは分離したモジュール）
setupSearchSuggest(els.search, { onSelect: runSearch });

// ── 並び順カスタムドロップダウン ──
function setSortValue(val) {
  const label = els.sortSelect.querySelector(".sort-label");
  const option = els.sortSelect.querySelector(`.sort-option[data-value="${val}"]`);
  if (label && option) label.textContent = option.textContent;
}

els.sortSelect.addEventListener("click", (e) => {
  const option = e.target.closest(".sort-option");
  if (option) {
    const val = option.getAttribute("data-value");
    if (val) {
      state.sortMode = val;
      localStorage.setItem("clipSortMode", state.sortMode);
      setSortValue(val);
      closeSortDropdown();
      render();
      requestAnimationFrame(() => els.sortSelect.blur());
    }
    return;
  }
  // トリガークリックで開閉
  if (e.target.closest(".sort-trigger")) {
    const dd = els.sortSelect.querySelector(".sort-dropdown");
    const opening = !dd.classList.contains("open");
    // すべて閉じてから開く
    closeSortDropdown();
    if (opening) {
      dd.classList.add("open");
      els.sortSelect.classList.add("open");
      els.sortSelect.focus();
    }
  }
});

function closeSortDropdown() {
  document.querySelectorAll(".sort-dropdown").forEach((d) => d.classList.remove("open"));
  document.querySelectorAll(".sort-select.open").forEach((s) => s.classList.remove("open"));
}  // closeSortDropdown

// カテゴリボタン — JS管理のプレス状態（:active の疑似クラス切替え問題を回避）
document.addEventListener("mousedown", (e) => {
  const btn = e.target.closest(".cat-btn");
  if (btn) btn.classList.add("is-pressed");
});
document.addEventListener("mouseup", (e) => {
  const btn = e.target.closest(".cat-btn");
  if (btn) btn.classList.remove("is-pressed");
});
// mouseout でキャプチャ（mouseleave はバブルしないため）
document.addEventListener("mouseout", (e) => {
  const btn = e.target.closest(".cat-btn");
  if (btn && (!e.relatedTarget || !btn.contains(e.relatedTarget))) btn.classList.remove("is-pressed");
});

els.favOnly.addEventListener("click", () => {
  state.favOnly = !state.favOnly;
  els.favOnly.classList.toggle("active", state.favOnly);
  render();
});

els.clearTag.addEventListener("click", () => {
  state.activeTags = [];
  render();
});

// 一括操作ボタン
els.batchTagBtn.addEventListener("click", batchTag);
els.batchCatBtn.addEventListener("click", batchCategory);
els.batchDelBtn.addEventListener("click", batchDelete);

// --- ローカルファイルを開く ---
async function openLocalFile(id) {
  try {
    const res = await fetch(`${API}/clips/${id}/open`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (e) {
    alert("ファイルを開けませんでした。");
  }
}

// --- ファイルアップロードモーダル ---
const uploadEls = {
  modal: $("uploadModal"),
  dropZone: $("uploadDropZone"),
  fileInput: $("uploadFileInput"),
  fileList: $("uploadFileList"),
  bulkWrap: $("uploadBulk"),
  bulkTagBox: $("uploadBulkTagBox"),
  bulkTagInput: $("uploadBulkTagInput"),
  bulkTagList: $("uploadBulkTagList"),
  bulkCategory: $("uploadBulkCategory"),
  cancel: $("uploadCancel"),
  save: $("uploadSave"),
  duplicateConfirm: $("uploadDuplicateConfirm"),
  duplicateMessage: $("uploadDuplicateMessage"),
  duplicateCancel: $("uploadDuplicateCancel"),
  duplicateSubmit: $("uploadDuplicateSubmit"),
};
const pageDropOverlay = $("pageDropOverlay");
let pageDragDepth = 0;

function setPageDropVisible(visible) {
  if (!pageDropOverlay) return;
  pageDropOverlay.classList.toggle("is-active", visible);
  pageDropOverlay.setAttribute("aria-hidden", visible ? "false" : "true");
}

function resetPageDragState() {
  pageDragDepth = 0;
  setPageDropVisible(false);
}

function isFileDragEvent(event) {
  const types = Array.from(event.dataTransfer?.types || []);
  return Boolean(
    event.dataTransfer?.files?.length ||
    types.some((type) => String(type).toLowerCase() === "files")
  );
}

// uploadFiles の各要素: { file: File, tags: string[], category: string, handle: FileSystemFileHandle|null }
uploadEls.modal.setAttribute("role", "dialog");
uploadEls.modal.setAttribute("aria-modal", "true");
uploadEls.modal.setAttribute("aria-hidden", "true");
const uploadModalTitleEl = uploadEls.modal.querySelector(".modal-title");
if (uploadModalTitleEl) {
  uploadModalTitleEl.id = uploadModalTitleEl.id || "uploadModalTitle";
  uploadEls.modal.setAttribute("aria-labelledby", uploadModalTitleEl.id);
}

let uploadFiles = [];
let uploadBulkTags = [];
let uploadBulkCategory = "";
let uploadCloseTimer = null;
let uploadReturnFocus = null;
let duplicateConfirmRequest = null;
let duplicateConfirmHideTimer = null;

function finishDuplicateConfirm(result) {
  const request = duplicateConfirmRequest;
  if (!request) return;
  duplicateConfirmRequest = null;
  clearTimeout(duplicateConfirmHideTimer);
  duplicateConfirmHideTimer = null;

  const dialog = uploadEls.duplicateConfirm;
  if (dialog) {
    dialog.classList.remove("is-open");
    dialog.setAttribute("aria-hidden", "true");
    duplicateConfirmHideTimer = window.setTimeout(() => {
      if (!duplicateConfirmRequest) dialog.hidden = true;
      duplicateConfirmHideTimer = null;
    }, 160);
  }

  if (!result && request.returnFocus?.isConnected) {
    request.returnFocus.focus({ preventScroll: true });
  }
  request.resolve(result);
}

function confirmDuplicateUpload(name) {
  const message = `「${name}」と同じファイルがすでに保存されています。\nアップロードを続行しますか？`;
  const dialog = uploadEls.duplicateConfirm;
  if (!dialog || !uploadEls.duplicateMessage) {
    if (typeof window.appConfirm === "function") {
      return window.appConfirm(message, {
        title: "同じファイルが見つかりました",
        cancelLabel: "キャンセル",
        confirmLabel: "続行する",
      });
    }
    return Promise.resolve(window.confirm(message));
  }

  if (duplicateConfirmRequest) finishDuplicateConfirm(false);
  clearTimeout(duplicateConfirmHideTimer);
  duplicateConfirmHideTimer = null;
  uploadEls.duplicateMessage.textContent = message;
  dialog.hidden = false;
  dialog.setAttribute("aria-hidden", "false");

  return new Promise((resolve) => {
    const request = {
      resolve,
      returnFocus: document.activeElement,
    };
    duplicateConfirmRequest = request;
    requestAnimationFrame(() => {
      if (duplicateConfirmRequest !== request) return;
      dialog.classList.add("is-open");
      uploadEls.duplicateSubmit?.focus();
    });
  });
}

uploadEls.duplicateConfirm?.addEventListener("click", (event) => {
  if (event.target === uploadEls.duplicateConfirm) finishDuplicateConfirm(false);
});
uploadEls.duplicateCancel?.addEventListener("click", () => finishDuplicateConfirm(false));
uploadEls.duplicateSubmit?.addEventListener("click", () => finishDuplicateConfirm(true));
uploadEls.duplicateConfirm?.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  event.preventDefault();
  event.stopPropagation();
  finishDuplicateConfirm(false);
});

function openUploadModal() {
  resetPageDragState();
  finishDuplicateConfirm(false);
  clearTimeout(duplicateConfirmHideTimer);
  duplicateConfirmHideTimer = null;
  if (uploadEls.duplicateConfirm) {
    uploadEls.duplicateConfirm.hidden = true;
    uploadEls.duplicateConfirm.classList.remove("is-open");
    uploadEls.duplicateConfirm.setAttribute("aria-hidden", "true");
  }
  if (uploadCloseTimer !== null) {
    clearTimeout(uploadCloseTimer);
    uploadCloseTimer = null;
  }
  uploadReturnFocus = document.activeElement;
  uploadFiles = [];
  uploadBulkTags = [];
  uploadBulkCategory = "";
  uploadEls.fileList.innerHTML = "";
  uploadEls.bulkTagBox.innerHTML = "";
  uploadEls.bulkTagInput.value = "";
  uploadEls.bulkCategory.value = "";
  uploadEls.bulkWrap.hidden = true;
  uploadEls.modal.classList.remove("has-upload-files");
  renderBulkTags();
  uploadEls.modal.hidden = false;
  uploadEls.modal.setAttribute("aria-hidden", "false");
  requestAnimationFrame(() => {
    uploadEls.modal.classList.add("is-open");
    uploadEls.cancel.focus();
  });
}
function closeUploadModal() {
  resetPageDragState();
  finishDuplicateConfirm(false);
  uploadEls.modal.classList.remove("is-open");
  uploadEls.modal.classList.remove("has-upload-files");
  uploadEls.modal.setAttribute("aria-hidden", "true");
  const returnFocus = uploadReturnFocus;
  uploadReturnFocus = null;
  if (uploadCloseTimer !== null) clearTimeout(uploadCloseTimer);
  uploadCloseTimer = window.setTimeout(() => {
    uploadEls.modal.hidden = true;
    uploadCloseTimer = null;
    if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
  }, 180);
  uploadFiles = [];
  uploadBulkTags = [];
}

els.addLocalBtn.addEventListener("click", openUploadModal);
uploadEls.cancel.addEventListener("click", closeUploadModal);
uploadEls.modal.addEventListener("click", (e) => {
  if (e.target !== uploadEls.modal) return;
  if (duplicateConfirmRequest) {
    finishDuplicateConfirm(false);
    return;
  }
  closeUploadModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || uploadEls.modal.hidden) return;
  if (uploadEls.duplicateConfirm && e.target instanceof Node && uploadEls.duplicateConfirm.contains(e.target)) {
    finishDuplicateConfirm(false);
    return;
  }
  closeUploadModal();
});

async function addReferenceFiles(entries) {
  let added = 0;
  for (const entry of entries || []) {
    const refPath = typeof entry === "string" ? entry : entry?.path;
    if (!refPath || uploadFiles.some((u) => u.refPath === refPath)) continue;

    const fallbackName = refPath.split(/[\\/]/).pop();
    const name = (typeof entry === "object" && entry?.name) || fallbackName;
    const rawSize = typeof entry === "object" ? entry?.size : null;
    const size = Number.isFinite(Number(rawSize)) ? Number(rawSize) : null;
    if (!name || !(await confirmIfDuplicate(name, size))) continue;

    uploadFiles.push({
      file: null,
      refPath,
      name,
      size,
      tags: [],
      category: "",
      handle: null,
    });
    added += 1;
  }
  renderUploadList();
  return added;
}

async function appendReferenceFilesFromDialog() {
  try {
    const res = await fetch(`${API}/dialog/open-files`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return addReferenceFiles(data.files || []);
  } catch (e) {
    alert("ファイル選択ダイアログを開けませんでした。サーバーが起動しているか確認してください。");
    return 0;
  }
}

function getDirectReferenceDropFiles(dataTransfer) {
  return [...(dataTransfer?.files || [])]
    .map((file) => {
      const path = typeof file.path === "string" ? file.path : "";
      return path
        ? { path, name: file.name, size: file.size }
        : null;
    })
    .filter(Boolean);
}

function postNativeDroppedFiles(dataTransfer) {
  const postMessage = window.chrome?.webview?.postMessageWithAdditionalObjects;
  if (typeof postMessage !== "function" || !dataTransfer?.files?.length) return false;

  try {
    // pywebviewのDOMリスナーに加えて明示的にも送ることで、
    // ホーム画面からのdropでもパス通知の順序を安定させる。
    postMessage.call(window.chrome.webview, "FilesDropped", dataTransfer.files);
    return true;
  } catch (e) {
    return false;
  }
}

async function getReferenceDropFiles(event) {
  const nativeApi = window.pywebview?.api;
  if (
    nativeApi &&
    typeof nativeApi.clear_dropped_files === "function" &&
    typeof nativeApi.read_dropped_files === "function"
  ) {
    try {
      await nativeApi.clear_dropped_files();
      postNativeDroppedFiles(event?.dataTransfer);
      const entries = await nativeApi.read_dropped_files();
      if (Array.isArray(entries) && entries.length) return entries;
    } catch (e) {
      // ブラウザのプレビューや旧ランタイムでは、下のFile.pathフォールバックを試す。
    }
  }
  return getDirectReferenceDropFiles(event?.dataTransfer);
}

function clearNativeDroppedFiles() {
  const clear = window.pywebview?.api?.clear_dropped_files;
  if (typeof clear === "function") {
    try {
      Promise.resolve(clear()).catch(() => {});
    } catch (e) {}
  }
}

// ドロップゾーン → 参照モードはネイティブ選択、コピー モードは通常のFile選択
uploadEls.dropZone.addEventListener("click", async () => {
  const isReference = els.fileSaveMethod.value === "reference";

  if (isReference) {
    await appendReferenceFilesFromDialog();
    return;
  }

  uploadEls.fileInput.click();
});
uploadEls.fileInput.addEventListener("change", async () => {
  await addUploadFiles([...uploadEls.fileInput.files]);
  uploadEls.fileInput.value = "";
});

// ドラッグ＆ドロップ(ホーム画面)
let dragModalActive = false;
document.addEventListener("dragenter", (e) => {
  if (dragModalActive) return;
  e.preventDefault();
  if (!isFileDragEvent(e)) return;
  if (pageDragDepth === 0) clearNativeDroppedFiles();
  pageDragDepth += 1;
  setPageDropVisible(true);
});
document.addEventListener("dragover", (e) => {
  if (dragModalActive) return;
  e.preventDefault();
  if (!isFileDragEvent(e)) return;
  setPageDropVisible(true);
});
document.addEventListener("dragleave", (e) => {
  if (dragModalActive) return;
  if (!isFileDragEvent(e)) return;
  e.preventDefault();
  pageDragDepth = Math.max(0, pageDragDepth - 1);
  if (pageDragDepth === 0) setPageDropVisible(false);
});
document.addEventListener("drop", async (e) => {
  if (dragModalActive) return;
  e.preventDefault();
  const hasFiles = Boolean(e.dataTransfer?.files?.length);
  resetPageDragState();
  if (!hasFiles) return;
  if (e.dataTransfer?.files?.length) {
    if (els.fileSaveMethod.value === "reference") {
      const entriesPromise = getReferenceDropFiles(e);
      openUploadModal();
      const entries = await entriesPromise;
      if (entries.length) await addReferenceFiles(entries);
      else await appendReferenceFilesFromDialog();
      return;
    }
    // ドラッグ経由(コピー保存モード): Fileの内容をそのままアップロードする。
    const dropped = [...e.dataTransfer.files];
    openUploadModal();
    await addUploadFiles(dropped);
  }
});
document.addEventListener("dragend", resetPageDragState);
window.addEventListener("blur", resetPageDragState);

// モーダル表示中のドラッグイベントは document 側に伝播させない。
// (伝播すると document 側の drop ハンドラも同じイベントを処理してしまい、
//  uploadFiles が openUploadModal() でもう一度リセットされていたのが原因)
uploadEls.modal.addEventListener("dragenter", (e) => {
  dragModalActive = true;
  resetPageDragState();
  clearNativeDroppedFiles();
  e.stopPropagation();
});
uploadEls.modal.addEventListener("dragover", (e) => {
  e.preventDefault();
  e.stopPropagation();
});
uploadEls.modal.addEventListener("drop", async (e) => {
  e.preventDefault();
  e.stopPropagation();
  dragModalActive = false;
  if (e.dataTransfer?.files?.length) {
    if (els.fileSaveMethod.value === "reference") {
      const entries = await getReferenceDropFiles(e);
      if (entries.length) await addReferenceFiles(entries);
      else await appendReferenceFilesFromDialog();
      return;
    }
    await addUploadFiles([...e.dataTransfer.files]);
  }
});
uploadEls.modal.addEventListener("dragleave", (e) => {
  e.stopPropagation();
  if (!uploadEls.modal.contains(e.relatedTarget)) {
    dragModalActive = false;
  }
});

// 既存クリップの中に、同じファイル名 & 同じファイルサイズのローカルクリップがあるか探す
function findExistingClipMatch(name, size) {
  if (size == null) return null;
  return state.clips.find(
    (c) => isLocalClip(c) && (c.title || "") === name && c.file_size === size
  );
}

async function confirmIfDuplicate(name, size) {
  const dup = findExistingClipMatch(name, size);
  if (!dup) return true;
  return confirmDuplicateUpload(name);
}

async function addUploadFiles(fileList) {
  for (const f of fileList) {
    if (uploadFiles.some((u) => u.file && u.file.name === f.name && u.file.size === f.size)) continue;
    if (!(await confirmIfDuplicate(f.name, f.size))) continue;
    uploadFiles.push({ file: f, tags: [], category: "", handle: null });
  }
  renderUploadList();
}

// 一括タグ入力(Enter-based chip, editTag と同じ UI)
function renderBulkTags() {
  const dl = $("uploadBulkTagList");
  if (dl) dl.innerHTML = state.tags.map((t) => `<option value="${escapeHtml(t.name)}">`).join("");
  uploadEls.bulkTagBox.innerHTML = uploadBulkTags
    .map(
      (t, i) =>
        `<span class="tag">${escapeHtml(t)}<button data-i="${i}" title="削除">×</button></span>`
    )
    .join("");
  uploadEls.bulkTagBox.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      uploadBulkTags.splice(Number(b.dataset.i), 1);
      renderBulkTags();
    });
  });
}

function addBulkUploadTag(value) {
  const name = value.trim();
  if (name && !uploadBulkTags.includes(name)) {
    uploadBulkTags.push(name);
    renderBulkTags();
  }
  uploadEls.bulkTagInput.value = "";
}

uploadEls.bulkTagInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    addBulkUploadTag(uploadEls.bulkTagInput.value);
  } else if (e.key === "Backspace" && uploadEls.bulkTagInput.value === "" && uploadBulkTags.length) {
    uploadBulkTags.pop();
    renderBulkTags();
  }
});

uploadEls.bulkCategory.addEventListener("input", () => {
  uploadBulkCategory = uploadEls.bulkCategory.value;
});

function renderUploadList() {
  uploadEls.bulkWrap.hidden = uploadFiles.length === 0;
  uploadEls.modal.classList.toggle("has-upload-files", uploadFiles.length > 0);
  const catList = state.categories.map((c) => `<option value="${escapeHtml(c.name)}">`).join("");
  const dl = $("uploadCategoryList");
  if (dl) dl.innerHTML = catList;
  const tagDl = $("uploadTagList");
  if (tagDl) tagDl.innerHTML = state.tags.map((t) => `<option value="${escapeHtml(t.name)}">`).join("");

  uploadEls.fileList.innerHTML = uploadFiles
    .map(
      (u, i) =>
        `<div class="upload-row">
          <span class="upload-name">${escapeHtml(u.file ? u.file.name : u.name)}</span>
          <div class="upload-row-tags-wrap">
            <div class="upload-row-tagbox" data-i="${i}">${u.tags.map((t) => `<span class="tag">${escapeHtml(t)}<button data-fi="${i}" data-ti="${t}" title="削除">×</button></span>`).join("")}</div>
            <input class="upload-row-taginput" data-i="${i}" list="uploadTagList" placeholder="タグを追加" />
          </div>
          <input class="upload-row-cat" data-i="${i}" list="uploadCategoryList" placeholder="カテゴリ" value="${escapeAttr(u.category)}" />
          <button class="upload-remove" data-i="${i}" title="削除">×</button>
        </div>`
    )
    .join("");

  // 個別タグ入力 (Enter-based)
  uploadEls.fileList.querySelectorAll(".upload-row-taginput").forEach((inp) => {
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        const fi = Number(inp.dataset.i);
        const name = inp.value.trim();
        if (name && !uploadFiles[fi].tags.includes(name)) {
          uploadFiles[fi].tags.push(name);
          renderUploadList();
        }
        inp.value = "";
      }
    });
  });

  // 個別タグ削除
  uploadEls.fileList.querySelectorAll(".upload-row-tagbox button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fi = Number(btn.dataset.fi);
      const ti = btn.dataset.ti;
      uploadFiles[fi].tags = uploadFiles[fi].tags.filter((t) => t !== ti);
      renderUploadList();
    });
  });

  // 個別カテゴリ
  uploadEls.fileList.querySelectorAll(".upload-row-cat").forEach((inp) => {
    inp.addEventListener("input", () => { uploadFiles[Number(inp.dataset.i)].category = inp.value; });
  });

  // 削除ボタン
  uploadEls.fileList.querySelectorAll(".upload-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      uploadFiles.splice(Number(btn.dataset.i), 1);
      renderUploadList();
    });
  });
}

uploadEls.save.addEventListener("click", async () => {
  if (!uploadFiles.length || uploadEls.save.disabled) return;
  const originalSaveLabel = uploadEls.save.textContent;
  uploadEls.save.disabled = true;
  uploadEls.save.textContent = "保存中…";
  uploadEls.save.setAttribute("aria-busy", "true");
  let ok = 0, fail = 0;

  try {
    for (const u of uploadFiles) {
      const mergedTags = [...new Set([...uploadBulkTags, ...u.tags])];
      const cat = u.category || uploadBulkCategory;

      try {
        if (u.refPath) {
          // 元ファイル参照モード: サーバーで取得した本物の絶対パスを送る
          const payload = {
            file_path: u.refPath,
            title: u.name,
            comment: null,
            category: cat || null,
            tags: mergedTags.join(","),
          };
          const res = await fetch(`${API}/clips/local/reference`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok) throw new Error();
        } else {
          // コピー保存モード: ファイル内容をアップロード
          const fd = new FormData();
          fd.append("file", u.file);
          fd.append("comment", "");
          if (mergedTags.length) fd.append("tags", mergedTags.join(","));
          if (cat) fd.append("category", cat);
          const res = await fetch(`${API}/clips/local`, { method: "POST", body: fd });
          if (!res.ok) throw new Error();
        }
        ok++;
      } catch {
        fail++;
      }
    }
  } finally {
    uploadEls.save.disabled = false;
    uploadEls.save.textContent = originalSaveLabel;
    uploadEls.save.removeAttribute("aria-busy");
  }

  closeUploadModal();
  await loadAll();
  if (fail) alert(`${ok}件成功、${fail}件失敗しました。`);
});

// --- 設定: ファイル保存方法 ---
async function loadFileSaveMethod() {
  try {
    const res = await fetch(`${API}/settings/file_save_method`);
    if (res.ok) {
      const data = await res.json();
      els.fileSaveMethod.value = data.value || "copy";
      updateFileSaveDesc(els.fileSaveMethod.value);
    }
  } catch {}
}
// fileSaveMethodのchangeハンドラは pins.js で一元管理
function updateFileSaveDesc(v) {
  els.fileSaveMethodDesc.textContent =
    v === "copy"
      ? "リンク切れの心配はありませんが、その分データ容量が増えます。"
      : "アップロードしたファイルの場所をそのまま参照します。";
}

loadAll()
  .then(() => loadFileSaveMethod())
  .catch((e) => {
  els.grid.innerHTML = "";
  els.empty.hidden = false;
  els.empty.querySelector(".empty-msg").textContent = "バックエンドに接続できません";
  els.empty.querySelector(".empty-sub").textContent =
    `サーバー(${API})を起動してください。`;
});

// タブが再びアクティブになったら一覧を自動更新
// (拡張機能で保存 → ホーム画面のタブに戻る想定)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    loadAll().catch(() => {});
    // 最近開いた順では、戻ってきたときにも並びを再評価する
    // (サーバーデータは変わらないため loadAll がスキップされるため)
    if (state.sortMode === "recent_opened") render();
  }
});

// カラム数のブレークポイントをまたいだときだけ再レイアウトする
let lastColCount = gridColCount();
let colResizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(colResizeTimer);
  colResizeTimer = setTimeout(() => {
    const count = gridColCount();
    if (count !== lastColCount) {
      lastColCount = count;
      render();
    }
  }, 150);
});

// Chrome拡張機能の保存後も、ホーム画面を手動更新せず一覧へ反映する。
// 画面が表示中のときだけ確認し、データが変わった場合だけ再描画する。
window.addEventListener("focus", () => {
  loadAll().catch(() => {});
  // 最近開いた順では、戻ってきたときにも並びを再評価する
  if (state.sortMode === "recent_opened") render();
});
window.setInterval(() => {
  if (document.visibilityState === "visible") {
    loadAll().catch(() => {});
  }
}, 1000);
