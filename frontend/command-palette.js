(() => {
  const API = window.location.origin;
  const RECENT_KEY = "sparkle.commandPalette.recent";
  const ENTITY_LABELS = {
    clip: "クリップ",
    note: "メモ",
    task: "タスク",
    project: "プロジェクト",
  };
  const EMPTY_COMMANDS = [
    { label: "ホームを開く", hint: "クリップ", target: "/Home" },
    { label: "タスク・メモを開く", hint: "タスク・メモ", target: "/Notes" },
    { label: "プロジェクトを開く", hint: "プロジェクト", target: "/Projects" },
    { label: "設定を開く", hint: "設定", target: "/Settings" },
  ];

  let root = null;
  let input = null;
  let list = null;
  let status = null;
  let closeButton = null;
  let activeIndex = -1;
  let items = [];
  let debounceTimer = null;
  let requestController = null;
  let returnFocus = null;
  let requestSequence = 0;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function recentQueries() {
    try {
      const parsed = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
    } catch {
      return [];
    }
  }

  function rememberQuery(query) {
    const value = String(query || "").trim();
    if (!value) return;
    const next = [value, ...recentQueries().filter((item) => item !== value)].slice(0, 6);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch {}
  }

  function ensureRoot() {
    if (root) return root;
    root = document.createElement("div");
    root.id = "commandPalette";
    root.className = "command-palette";
    root.hidden = true;
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-labelledby", "commandPaletteTitle");
    root.innerHTML = `
      <div class="command-palette-card" role="document">
        <div class="command-palette-header">
          <div>
            <h2 id="commandPaletteTitle" class="command-palette-title">コマンドパレット</h2>
            <p class="command-palette-subtitle">メモ・クリップ・タスク・プロジェクトを横断検索</p>
          </div>
          <button type="button" class="command-palette-close" aria-label="コマンドパレットを閉じる">Esc</button>
        </div>
        <label class="sr-only" for="commandPaletteInput">検索語</label>
        <div class="command-palette-input-wrap">
          <span class="command-palette-search-icon" aria-hidden="true">⌕</span>
          <input
            id="commandPaletteInput"
            class="command-palette-input"
            type="search"
            autocomplete="off"
            spellcheck="false"
            placeholder="自然な言葉で検索…"
            role="combobox"
            aria-autocomplete="list"
            aria-haspopup="listbox"
            aria-controls="commandPaletteResults"
            aria-expanded="true"
          />
        </div>
        <div id="commandPaletteStatus" class="command-palette-status" role="status" aria-live="polite" aria-atomic="true"></div>
        <div id="commandPaletteResults" class="command-palette-results" role="listbox" aria-label="検索結果" aria-busy="false"></div>
        <div class="command-palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> 移動</span>
          <span><kbd>Enter</kbd> 開く</span>
          <span><kbd>Esc</kbd> 閉じる</span>
        </div>
      </div>`;
    document.body.appendChild(root);
    input = root.querySelector("#commandPaletteInput");
    list = root.querySelector("#commandPaletteResults");
    status = root.querySelector("#commandPaletteStatus");
    closeButton = root.querySelector(".command-palette-close");

    closeButton.addEventListener("click", close);
    root.addEventListener("click", (event) => {
      if (event.target === root) close();
    });
    input.addEventListener("input", () => {
      scheduleSearch(input.value);
    });
    input.addEventListener("keydown", handleInputKeydown);
    list.addEventListener("click", (event) => {
      const item = event.target.closest("[data-command-index]");
      if (!item) return;
      activate(Number(item.dataset.commandIndex));
    });
    return root;
  }

  function setStatus(message) {
    if (status) status.textContent = message || "";
  }

  function renderEmpty() {
    const recent = recentQueries();
    items = [
      ...EMPTY_COMMANDS.map((item) => ({ ...item, kind: "command" })),
      ...recent.map((query) => ({ label: query, hint: "最近の検索", query, kind: "recent" })),
    ];
    activeIndex = -1;
    list.innerHTML = items.length
      ? items.map((item, index) => `
          <button type="button" role="option" tabindex="-1" class="command-palette-item" data-command-index="${index}">
            <span class="command-palette-item-icon" aria-hidden="true">${item.kind === "recent" ? "↻" : "→"}</span>
            <span class="command-palette-item-copy">
              <span class="command-palette-item-title">${escapeHtml(item.label)}</span>
              <span class="command-palette-item-snippet">${escapeHtml(item.hint)}</span>
            </span>
          </button>`).join("")
      : '<div class="command-palette-empty">検索語を入力してください。</div>';
    list.setAttribute("aria-busy", "false");
    setStatus(recent.length ? "最近の検索と移動先" : "移動先を選ぶか、検索語を入力してください。");
    syncActiveDescendant();
  }

  function renderResults(payload) {
    items = Array.isArray(payload.results)
      ? payload.results.map((result) => ({ ...result, kind: "result" }))
      : [];
    activeIndex = items.length ? 0 : -1;
    if (!items.length) {
      list.innerHTML = '<div class="command-palette-empty">該当する項目がありません。</div>';
    } else {
      list.innerHTML = items.map((item, index) => {
        const label = ENTITY_LABELS[item.entity_type] || item.entity_type;
        const meta = [
          label,
          item.is_done === true ? "完了" : item.is_done === false ? "未完了" : "",
          item.due_date ? `期限 ${item.due_date}` : "",
          item.priority ? `優先度 ${item.priority}` : "",
        ].filter(Boolean).join(" · ");
        return `
          <button type="button" role="option" tabindex="-1" class="command-palette-item" data-command-index="${index}">
            <span class="command-palette-item-icon command-palette-kind-${escapeHtml(item.entity_type)}" aria-hidden="true">${escapeHtml(label.slice(0, 1))}</span>
            <span class="command-palette-item-copy">
              <span class="command-palette-item-title">${escapeHtml(item.title)}</span>
              <span class="command-palette-item-meta">${escapeHtml(meta)}</span>
              ${item.snippet ? `<span class="command-palette-item-snippet">${escapeHtml(item.snippet)}</span>` : ""}
            </span>
          </button>`;
      }).join("");
    }
    list.setAttribute("aria-busy", "false");
    const parserLabel = payload.parser === "lfm2.5-350m" ? "LFM2.5-350Mで解釈" : "通常検索";
    setStatus(`${payload.total || 0}件 · ${parserLabel}`);
    syncActiveDescendant();
  }

  function syncActiveDescendant() {
    const buttons = [...list.querySelectorAll("[data-command-index]")];
    buttons.forEach((button, index) => {
      const active = index === activeIndex;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    if (activeIndex >= 0 && buttons[activeIndex]) {
      const id = `commandPaletteOption${activeIndex}`;
      buttons[activeIndex].id = id;
      input.setAttribute("aria-activedescendant", id);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function moveActive(delta) {
    if (!items.length) return;
    activeIndex = (activeIndex + delta + items.length) % items.length;
    syncActiveDescendant();
    const active = list.querySelector(`[data-command-index="${activeIndex}"]`);
    active?.scrollIntoView({ block: "nearest" });
  }

  function handleInputKeydown(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (activeIndex >= 0) activate(activeIndex);
    }
  }

  function activate(index) {
    const item = items[index];
    if (!item) return;
    if (item.kind === "recent") {
      input.value = item.query;
      scheduleSearch(item.query, true);
      return;
    }
    if (item.kind === "result") {
      rememberQuery(input.value);
      const target = String(item.target || "");
      if (target.startsWith("/")) {
        close(false);
        window.location.assign(target);
      }
      return;
    }
    if (item.target) {
      close(false);
      window.location.assign(item.target);
    }
  }

  function scheduleSearch(query, immediate = false) {
    clearTimeout(debounceTimer);
    if (requestController) requestController.abort();
    if (!String(query || "").trim()) {
      renderEmpty();
      return;
    }
    if (immediate) {
      search(query);
      return;
    }
    debounceTimer = window.setTimeout(() => search(query), 280);
  }

  async function search(query) {
    const currentQuery = String(query || "").trim();
    if (!currentQuery) return;
    const sequence = ++requestSequence;
    requestController = new AbortController();
    list.setAttribute("aria-busy", "true");
    setStatus("検索中…");
    try {
      const response = await fetch(`${API}/command-palette/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: currentQuery, limit: 30, use_ai: true }),
        signal: requestController.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (sequence !== requestSequence || input.value.trim() !== currentQuery) return;
      renderResults(payload);
    } catch (error) {
      if (error?.name === "AbortError") return;
      if (sequence !== requestSequence) return;
      list.setAttribute("aria-busy", "false");
      list.innerHTML = '<div class="command-palette-error">検索に失敗しました。通常検索も利用できません。</div>';
      setStatus("検索エラー");
    }
  }

  function open() {
    ensureRoot();
    if (!root.hidden) return;
    returnFocus = document.activeElement;
    root.hidden = false;
    input.value = "";
    renderEmpty();
    requestAnimationFrame(() => input.focus({ preventScroll: true }));
  }

  function close(restore = true) {
    if (!root || root.hidden) return;
    clearTimeout(debounceTimer);
    requestController?.abort();
    requestController = null;
    root.hidden = true;
    if (restore && returnFocus?.isConnected) {
      requestAnimationFrame(() => returnFocus.focus({ preventScroll: true }));
    }
    returnFocus = null;
  }

  document.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const key = String(event.key || "").toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "k" && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      open();
      return;
    }
    if (!root || root.hidden || key !== "escape") return;
    event.preventDefault();
    event.stopPropagation();
    close();
  }, true);

  window.openCommandPalette = open;
  window.closeCommandPalette = close;
})();
