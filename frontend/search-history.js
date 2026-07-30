/* 検索履歴 + サジェストUI。
 * - SearchHistory: localStorage ベースの履歴保存・取得・削除（単一責務）
 * - setupSearchSuggest: 入力欄にサジェストドロップダウンを付与。
 *   プロバイダ配列を受け取るため、将来の「検索候補」「AI候補」も
 *   同じ仕組みで追加可能（検索処理と履歴管理を分離）。
 */
(function () {
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

  const SearchHistory = {
    KEY: "clipSearchHistory",
    MAX: 30,
    _read() {
      try {
        const a = JSON.parse(localStorage.getItem(this.KEY));
        return Array.isArray(a) ? a : [];
      } catch (e) {
        return [];
      }
    },
    _write(arr) {
      try {
        localStorage.setItem(this.KEY, JSON.stringify(arr.slice(0, this.MAX)));
      } catch (e) {
        /* 容量不足等は無視 */
      }
      this._emit();
    },
    all() {
      return this._read();
    },
    add(q) {
      const t = (q || "").trim();
      if (!t) return; // 空文字は保存しない
      const arr = this._read().filter(
        (x) => x.trim().toLowerCase() !== t.toLowerCase()
      );
      arr.unshift(t); // 重複は除去して先頭へ
      this._write(arr);
    },
    remove(q) {
      const t = (q || "").trim().toLowerCase();
      this._write(this._read().filter((x) => x.trim().toLowerCase() !== t));
    },
    clear() {
      this._write([]);
    },
    filter(q) {
      const t = (q || "").trim().toLowerCase();
      const arr = this._read();
      if (!t) return arr.slice();
      return arr.filter((x) => x.toLowerCase().includes(t));
    },

    // --- サジェストプロバイダー interface ---
    name: "履歴",
    deletable: true,
    getSuggestions(query) {
      return this.filter(query);
    },
    removeSuggestion(item) {
      this.remove(item);
    },
    _emit() {
      try {
        window.dispatchEvent(new Event("searchhistory:changed"));
      } catch (e) {
        /* noop */
      }
    },
  };

  function setupSearchSuggest(inputEl, opts) {
    const providers = (opts && opts.providers) || [SearchHistory];
    const onSelect = (opts && opts.onSelect) || function () {};
    const box = document.getElementById("searchSuggest");
    if (!box || !inputEl) return;

    let items = []; // 表示中の { text, provider }
    let activeIndex = -1;

    function gather(query) {
      const out = [];
      for (const p of providers) {
        const list = p.getSuggestions ? p.getSuggestions(query) : [];
        for (const text of list) out.push({ text, provider: p });
      }
      return out;
    }

    function render() {
      const q = inputEl.value;
      items = gather(q);
      if (items.length === 0) {
        box.hidden = true;
        activeIndex = -1;
        return;
      }
      if (activeIndex >= items.length) activeIndex = items.length - 1;
      box.innerHTML = items
        .map((it, i) => {
          const del = it.provider.deletable
            ? `<button class="suggest-del" type="button" data-del="${escapeAttr(it.text)}" title="削除">×</button>`
            : "";
          return (
            `<div class="suggest-item${i === activeIndex ? " active" : ""}" data-q="${escapeAttr(it.text)}">` +
            `<span class="suggest-text">${escapeHtml(it.text)}</span>${del}</div>`
          );
        })
        .join("");
      box.hidden = false;
    }

    function open() {
      render();
    }
    function close() {
      box.hidden = true;
      activeIndex = -1;
    }

    function select(text) {
      SearchHistory.add(text); // 選択でも先頭へ移動
      onSelect(text);
      close();
    }
    function commit() {
      SearchHistory.add(inputEl.value);
      onSelect(inputEl.value);
      close();
    }

    inputEl.addEventListener("focus", open);
    inputEl.addEventListener("click", open);
    inputEl.addEventListener("input", () => {
      activeIndex = -1;
      render();
    });

    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (box.hidden) open();
        if (items.length) activeIndex = (activeIndex + 1) % items.length;
        render();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (box.hidden) open();
        if (items.length)
          activeIndex = (activeIndex - 1 + items.length) % items.length;
        render();
      } else if (e.key === "Enter") {
        if (!box.hidden && activeIndex >= 0 && items[activeIndex]) {
          e.preventDefault();
          select(items[activeIndex].text);
        } else {
          commit();
        }
      } else if (e.key === "Escape") {
        close();
      }
    });

    box.addEventListener("click", (e) => {
      const del = e.target.closest(".suggest-del");
      if (del) {
        e.stopPropagation();
        const text = del.getAttribute("data-del");
        const hit = items.find((it) => it.text === text);
        if (hit && hit.provider.removeSuggestion)
          hit.provider.removeSuggestion(text);
        render();
        return;
      }
      const item = e.target.closest(".suggest-item");
      if (item) select(item.getAttribute("data-q"));
    });

    document.addEventListener("click", (e) => {
      const wrap = inputEl.closest(".search-wrap") || inputEl.parentNode;
      if (wrap && !wrap.contains(e.target)) close();
    });

    window.addEventListener("searchhistory:changed", () => {
      if (!box.hidden) render();
    });

    return { open, close, render };
  }

  window.SearchHistory = SearchHistory;
  window.setupSearchSuggest = setupSearchSuggest;
})();
