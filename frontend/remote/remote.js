(() => {
  const main = document.getElementById("remoteMain");
  const fileInput = document.getElementById("remoteFileInput");
  const toast = document.getElementById("remoteToast");
  const drawer = document.getElementById("remoteDrawer");
  const backdrop = document.getElementById("remoteDrawerBackdrop");
  const menuButton = document.getElementById("remoteMenuButton");
  const drawerClose = document.getElementById("remoteDrawerClose");
  const clipActionDialog = document.getElementById("remoteClipActionDialog");
  const clipActionSummary = document.getElementById("remoteClipActionSummary");
  const clipFavoriteAction = document.getElementById("remoteClipFavoriteAction");
  const clipDeleteAction = document.getElementById("remoteClipDeleteAction");
  const itemActionDialog = document.getElementById("remoteItemActionDialog");
  const itemActionKicker = document.getElementById("remoteItemActionKicker");
  const itemActionTitle = document.getElementById("remoteItemActionTitle");
  const itemActionSummary = document.getElementById("remoteItemActionSummary");
  const itemEditAction = document.getElementById("remoteItemEditAction");
  const itemDeleteAction = document.getElementById("remoteItemDeleteAction");
  const projectAttachDialog = document.getElementById("remoteProjectAttachDialog");
  const projectAttachTitle = document.getElementById("remoteProjectAttachTitle");
  const projectAttachSummary = document.getElementById("remoteProjectAttachSummary");
  const projectAttachLabel = document.getElementById("remoteProjectAttachLabel");
  const projectAttachSelect = document.getElementById("remoteProjectAttachSelect");
  const projectAttachSubmit = document.getElementById("remoteProjectAttachSubmit");
  if (
    !main || !fileInput || !toast || !drawer || !backdrop || !menuButton || !drawerClose ||
    !clipActionDialog || !clipActionSummary || !clipFavoriteAction || !clipDeleteAction ||
    !itemActionDialog || !itemActionKicker || !itemActionTitle || !itemActionSummary ||
    !itemEditAction || !itemDeleteAction || !projectAttachDialog || !projectAttachTitle ||
    !projectAttachSummary || !projectAttachLabel || !projectAttachSelect || !projectAttachSubmit
  ) return;

  const state = {
    screen: "home",
    homeView: "list",
    detailClipId: null,
    detailReturnProjectId: null,
    workspaceTab: "tasks",
    workspaceStatus: "active",
    projectStatus: "active",
    clips: [],
    categories: [],
    tags: [],
    tasks: [],
    notes: [],
    projects: [],
    search: "",
    category: "",
    tagFilter: "",
    favoritesOnly: false,
    sort: "date_desc",
    editingClip: null,
    uploadFile: null,
    editingTask: null,
    editingNote: null,
    editingProject: null,
    editorReturnProjectId: null,
    projectDetailId: null,
    loading: false,
    dataSignature: "",
  };
  let toastTimer = null;
  let clipActionTarget = null;
  let clipActionTrigger = null;
  let itemActionTarget = null;
  let itemActionTrigger = null;
  let projectAttachTarget = null;
  let settingsRenderToken = 0;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(value) {
    const raw = String(value || "").trim();
    try {
      const parsed = new URL(raw);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? raw : "";
    } catch {
      return "";
    }
  }

  function readCookie(name) {
    const prefix = name + "=";
    for (const item of document.cookie.split(";")) {
      const value = item.trim();
      if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
    }
    return "";
  }

  async function api(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const isForm = options.body instanceof FormData;
    const headers = {
      Accept: "application/json",
      ...(options.headers || {}),
    };
    if (options.body && !isForm) headers["Content-Type"] = "application/json";
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      const csrf = readCookie("__Host-sparkle_remote_csrf");
      if (csrf) headers["X-Sparkle-CSRF"] = csrf;
    }
    const response = await fetch(path, {
      ...options,
      method,
      credentials: "same-origin",
      headers,
    });
    if (response.status === 401) {
      window.location.assign("/remote-login");
      throw new Error("ログインが必要です。");
    }
    let data = null;
    try { data = await response.json(); } catch {}
    if (!response.ok) {
      throw new Error(data?.detail || ("HTTP " + response.status));
    }
    return data;
  }

  function showToast(message, isError = false) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.dataset.tone = isError ? "error" : "normal";
    toast.classList.add("show");
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3000);
  }

  function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric" }).format(date);
  }

  function projectName(projectId) {
    const project = state.projects.find((item) => Number(item.id) === Number(projectId));
    return project ? project.name : "";
  }

  function taskPriorityValue(task) {
    const value = Number(task?.priority);
    return Number.isInteger(value) && value >= 1 && value <= 5 ? value : null;
  }

  function taskPriorityLabel(task) {
    const priority = taskPriorityValue(task);
    return priority === null ? "設定なし" : "優先度" + priority;
  }

  function taskNotes(task) {
    return Array.isArray(task?.notes) ? task.notes : [];
  }

  function highestTaskPriority(tasks) {
    const priorities = tasks
      .filter((task) => !task.is_done)
      .map(taskPriorityValue)
      .filter((priority) => priority !== null);
    return priorities.length ? Math.min(...priorities) : null;
  }

  function priorityOptions(selected) {
    const current = taskPriorityValue({ priority: selected });
    return '<option value="">設定なし</option>' + [1, 2, 3, 4, 5].map((value) =>
      '<option value="' + value + '"' + (current === value ? " selected" : "") + ">優先度" + value + "</option>"
    ).join("");
  }

  function linkedToProject(item, projectId) {
    const ids = Array.isArray(item?.project_ids)
      ? item.project_ids
      : (item?.project_id == null ? [] : [item.project_id]);
    return ids.some((id) => Number(id) === Number(projectId));
  }

  function noteIsDone(note) {
    if (note?.is_done === true) return true;
    const taskIds = Array.isArray(note?.task_ids)
      ? note.task_ids
      : (note?.task_id == null ? [] : [note.task_id]);
    return taskIds.some((id) => state.tasks.some((task) => Number(task.id) === Number(id) && task.is_done));
  }

  function statusMatches(item, filter, kind) {
    if (filter === "all") return true;
    const done = kind === "note" ? noteIsDone(item) : Boolean(item?.is_done);
    return filter === "done" ? done : !done;
  }

  function renderStatusFilters(filter, scope) {
    return '<div class="remote-status-filter" aria-label="状態で絞り込む">' +
      [
        ["all", "すべて"],
        ["active", "進行中"],
        ["done", "完了済み"],
      ].map(([value, label]) =>
        '<button class="remote-status-button ' + (filter === value ? "active" : "") + '" type="button" data-status-scope="' + scope + '" data-status-filter="' + value + '" aria-pressed="' + (filter === value ? "true" : "false") + '">' + label + "</button>"
      ).join("") +
      "</div>";
  }

  function bindLongPress(element, { onTap, onLongPress }) {
    let pressTimer = null;
    let pressStart = null;
    let longPressed = false;
    const cancel = (resetLongPress = true) => {
      if (pressTimer !== null) window.clearTimeout(pressTimer);
      pressTimer = null;
      pressStart = null;
      if (resetLongPress) longPressed = false;
    };
    element.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button, input, a, select, textarea")) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      cancel();
      pressStart = { x: event.clientX, y: event.clientY };
      pressTimer = window.setTimeout(() => {
        longPressed = true;
        cancel(false);
        onLongPress(event);
      }, 550);
    });
    element.addEventListener("pointermove", (event) => {
      if (!pressStart) return;
      if (Math.hypot(event.clientX - pressStart.x, event.clientY - pressStart.y) > 10) cancel();
    });
    element.addEventListener("pointerup", () => cancel(false));
    element.addEventListener("pointercancel", () => cancel());
    element.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse") cancel();
    });
    element.addEventListener("contextmenu", (event) => {
      if (longPressed) event.preventDefault();
    });
    element.addEventListener("click", (event) => {
      if (event.target.closest("button, input, a, select, textarea")) return;
      if (longPressed) {
        longPressed = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      onTap(event);
    });
    element.addEventListener("keydown", (event) => {
      if (event.target !== element || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      onTap(event);
    });
  }

  function categoryName(categoryId) {
    const category = state.categories.find((item) => Number(item.id) === Number(categoryId));
    return category ? category.name : "";
  }

  function youtubeThumbnailUrl(rawUrl) {
    const source = safeHref(rawUrl);
    if (!source) return "";
    try {
      const parsed = new URL(source);
      const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
      const parts = parsed.pathname.split("/").filter(Boolean);
      let videoId = "";
      if (host === "youtu.be") {
        videoId = parts[0] || "";
      } else if (host === "youtube.com" || host === "youtube-nocookie.com") {
        if (parts[0] === "watch") videoId = parsed.searchParams.get("v") || "";
        if (["shorts", "embed", "live", "v"].includes(parts[0])) videoId = parts[1] || "";
      }
      if (!/^[A-Za-z0-9_-]{6,64}$/.test(videoId)) return "";
      return "https://i.ytimg.com/vi/" + videoId + "/hqdefault.jpg";
    } catch {
      return "";
    }
  }

  function clipImageUrl(clip) {
    const raw = String(clip?.thumbnail_url || "").trim();
    if (!raw) {
      const fallback = youtubeThumbnailUrl(clip?.url);
      return fallback ? "/thumbnail-proxy?url=" + encodeURIComponent(fallback) : "";
    }
    if (raw.startsWith("/")) return raw;
    const external = safeHref(raw);
    return external ? "/thumbnail-proxy?url=" + encodeURIComponent(external) : "";
  }

  function clipSourceLabel(clip) {
    if (clip?.clip_type === "local") return "ファイル";
    return safeHref(clip?.url) ? "URL" : "クリップ";
  }

  function clipTitle(clip) {
    return String(clip?.title || clip?.url || "無題のクリップ");
  }

  function parseTags(value) {
    return String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item, index, all) => all.indexOf(item) === index);
  }

  function renderTags(tags) {
    const values = Array.isArray(tags) ? tags : [];
    if (!values.length) return "";
    return '<div class="remote-tag-row">' + values.map((tag) => (
      (() => {
        const name = String(tag.name || tag);
        const selected = state.tagFilter === name;
        return '<button class="remote-chip remote-tag-chip ' + (selected ? "active" : "") + '" type="button" data-tag-filter="' + escapeHtml(name) + '" aria-pressed="' + (selected ? "true" : "false") + '" aria-label="タグ「' + escapeHtml(name) + '」で絞り込む">' + escapeHtml(name) + "</button>";
      })()
    )).join("") + "</div>";
  }

  function renderPageHeader(kicker, title, description, actionHtml) {
    return (
      '<header class="remote-page-header">' +
        '<div><p class="remote-page-kicker">' + escapeHtml(kicker) + "</p>" +
        '<h1 class="remote-page-title">' + escapeHtml(title) + "</h1>" +
        (description ? '<p class="remote-page-description">' + escapeHtml(description) + "</p>" : "") +
        "</div>" +
        (actionHtml || "") +
      "</header>"
    );
  }

  function filteredClips() {
    const query = state.search.trim().toLocaleLowerCase();
    let clips = state.clips.filter((clip) => {
      if (state.favoritesOnly && !clip.is_favorite) return false;
      if (state.category && String(clip.category_id) !== String(state.category)) return false;
      if (state.tagFilter && !(Array.isArray(clip.tags) && clip.tags.some((tag) => String(tag.name || tag) === state.tagFilter))) return false;
      if (!query) return true;
      const haystack = [
        clip.title,
        clip.url,
        clip.comment,
        ...(Array.isArray(clip.tags) ? clip.tags.map((tag) => tag.name || tag) : []),
      ].join(" ").toLocaleLowerCase();
      return haystack.includes(query);
    });
    if (state.sort === "title") {
      clips = clips.slice().sort((a, b) => clipTitle(a).localeCompare(clipTitle(b), "ja"));
    } else if (state.sort === "random") {
      clips = clips.slice().sort(() => Math.random() - 0.5);
    } else {
      clips = clips.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    }
    return clips;
  }

  function renderClipCard(clip) {
    const image = clipImageUrl(clip);
    const source = safeHref(clip?.url);
    const title = clipTitle(clip);
    return (
      '<article class="remote-card" data-detail-id="' + Number(clip.id) + '" tabindex="0" role="button" aria-label="' + escapeHtml(title) + 'の詳細を見る">' +
        '<div class="remote-card-media">' +
        (image
          ? '<img src="' + escapeHtml(image) + '" alt="" loading="lazy" draggable="false" />'
          : '<span class="remote-card-media-placeholder" aria-hidden="true">' + (clip.clip_type === "local" ? "▧" : "✦") + "</span>") +
        (clip.is_favorite ? '<span class="remote-card-favorite" aria-label="お気に入り">★</span>' : "") +
        "</div>" +
        '<div class="remote-card-body">' +
          '<h2 class="remote-card-title">' + escapeHtml(title) + "</h2>" +
          '<div class="remote-card-meta"><span>' + escapeHtml(clipSourceLabel(clip)) + "</span>" +
          (categoryName(clip.category_id) ? "<span>·</span><span>" + escapeHtml(categoryName(clip.category_id)) + "</span>" : "") +
          (clip.created_at ? "<span>·</span><span>" + escapeHtml(formatDate(clip.created_at)) + "</span>" : "") +
          "</div>" +
          (source
            ? '<a class="remote-card-url" href="' + escapeHtml(source) + '" target="_blank" rel="noreferrer">' + escapeHtml(clip.url) + "</a>"
            : '<span class="remote-card-url">' + escapeHtml(clip.url || "PC内のファイル") + "</span>") +
          renderTags(clip.tags) +
        "</div>" +
      "</article>"
    );
  }

  function renderHome() {
    state.homeView = "list";
    state.detailClipId = null;
    state.detailReturnProjectId = null;
    const categories = [
      '<button class="remote-chip ' + (!state.category ? "active" : "") + '" type="button" data-category="">すべて</button>',
      ...state.categories.map((category) =>
        '<button class="remote-chip ' + (String(state.category) === String(category.id) ? "active" : "") + '" type="button" data-category="' + Number(category.id) + '">' + escapeHtml(category.name) + "</button>"
      ),
    ].join("");
    const clips = filteredClips();
    main.innerHTML =
      renderPageHeader(
        "SPARKLE WEB",
        "ホーム",
        "PCに保存されているクリップを、スマホ向けのWeb画面から管理します。",
        '<div class="remote-header-actions"><button id="remoteNewClip" class="remote-primary-button" type="button">＋ URLを追加</button><button id="remoteNewFile" class="remote-secondary-button" type="button">＋ ファイル</button></div>',
      ) +
      '<section class="remote-panel">' +
        '<div class="remote-search-row">' +
          '<input id="remoteSearch" class="remote-search-input" type="search" placeholder="タイトル・URL・タグを検索" autocomplete="off" value="' + escapeHtml(state.search) + '" />' +
          '<button id="remoteFavoriteFilter" class="remote-secondary-button" type="button">' + (state.favoritesOnly ? "★ お気に入り中" : "☆ お気に入り") + "</button>" +
        "</div>" +
        '<div class="remote-filter-row" aria-label="カテゴリ">' + categories + "</div>" +
        '<div class="remote-filter-row remote-tag-filter-row" aria-label="タグ絞り込み">' +
          (state.tagFilter
            ? '<span class="remote-filter-label">タグ:</span><button class="remote-chip active" type="button" data-clear-tag-filter aria-label="タグ「' + escapeHtml(state.tagFilter) + '」の絞り込みを解除">' + escapeHtml(state.tagFilter) + ' ×</button>'
            : '<span class="remote-filter-hint">クリップのタグをタップすると、そのタグだけに絞り込めます。</span>') +
        "</div>" +
        '<div class="remote-filter-row">' +
          '<label class="remote-field" style="min-width: 170px;">並び順<select id="remoteSort"><option value="date_desc">最近追加した順</option><option value="title">タイトル順</option><option value="random">ランダム</option></select></label>' +
        "</div>" +
      "</section>" +
      '<section class="remote-panel" aria-labelledby="remoteClipHeading">' +
        '<div class="remote-panel-heading"><h2 id="remoteClipHeading">クリップ ' + clips.length + "件</h2></div>" +
        (clips.length ? '<div class="remote-grid">' + clips.map(renderClipCard).join("") + "</div>" : '<div class="remote-empty">条件に一致するクリップはありません。</div>') +
      "</section>";

    document.getElementById("remoteNewClip").addEventListener("click", () => renderEditor(null, null));
    document.getElementById("remoteNewFile").addEventListener("click", () => fileInput.click());
    document.getElementById("remoteSearch").addEventListener("input", (event) => {
      state.search = event.target.value;
      renderHome();
      const input = document.getElementById("remoteSearch");
      input.focus();
      input.setSelectionRange(state.search.length, state.search.length);
    });
    document.getElementById("remoteFavoriteFilter").addEventListener("click", () => {
      state.favoritesOnly = !state.favoritesOnly;
      renderHome();
    });
    document.getElementById("remoteSort").value = state.sort;
    document.getElementById("remoteSort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderHome();
    });
    main.querySelectorAll("[data-category]").forEach((button) => {
      button.addEventListener("click", () => {
        state.category = button.dataset.category || "";
        renderHome();
      });
    });
    main.querySelector("[data-clear-tag-filter]")?.addEventListener("click", () => {
      state.tagFilter = "";
      renderHome();
    });
    main.querySelectorAll("[data-tag-filter]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const tag = button.dataset.tagFilter || "";
        state.tagFilter = state.tagFilter === tag ? "" : tag;
        renderHome();
      });
    });
    main.querySelectorAll("[data-detail-id]").forEach((card) => {
      let pressTimer = null;
      let pressStart = null;
      let longPressed = false;
      const clearPress = (resetLongPress = false) => {
        if (pressTimer !== null) window.clearTimeout(pressTimer);
        pressTimer = null;
        pressStart = null;
        if (resetLongPress) longPressed = false;
      };
      card.addEventListener("pointerdown", (event) => {
        if (event.target.closest("a, button")) return;
        if (event.pointerType === "mouse" && event.button !== 0) return;
        clearPress(true);
        pressStart = { x: event.clientX, y: event.clientY };
        pressTimer = window.setTimeout(() => {
          longPressed = true;
          clearPress();
          openClipActionDialog(Number(card.dataset.detailId), card);
        }, 550);
      });
      card.addEventListener("pointermove", (event) => {
        if (!pressStart) return;
        if (Math.hypot(event.clientX - pressStart.x, event.clientY - pressStart.y) > 10) {
          clearPress(true);
        }
      });
      card.addEventListener("pointerup", () => clearPress());
      card.addEventListener("pointercancel", () => clearPress(true));
      card.addEventListener("pointerleave", (event) => {
        if (event.pointerType === "mouse") clearPress(true);
      });
      card.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
      card.addEventListener("dragstart", (event) => {
        event.preventDefault();
      });
      card.addEventListener("click", (event) => {
        if (longPressed) {
          longPressed = false;
          event.preventDefault();
          return;
        }
        if (event.target.closest("a, button")) return;
        renderDetail(Number(card.dataset.detailId));
      });
      card.addEventListener("keydown", (event) => {
        if (event.target !== card || !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        renderDetail(Number(card.dataset.detailId));
      });
    });
  }

  function closeClipActionDialog() {
    clipActionTarget = null;
    if (clipActionDialog.open) clipActionDialog.close();
    else clipActionDialog.removeAttribute("open");
  }

  function openClipActionDialog(id, trigger) {
    const clip = state.clips.find((item) => Number(item.id) === Number(id));
    if (!clip) return;
    clipActionTarget = clip;
    clipActionTrigger = trigger || null;
    clipActionSummary.textContent = clipTitle(clip);
    clipFavoriteAction.textContent = clip.is_favorite ? "お気に入りを解除" : "お気に入り";
    clipFavoriteAction.setAttribute("aria-label", clip.is_favorite ? "お気に入りを解除" : "お気に入りに追加");
    if (typeof clipActionDialog.showModal === "function") {
      clipActionDialog.showModal();
    } else {
      clipActionDialog.setAttribute("open", "");
    }
    clipFavoriteAction.focus();
  }

  clipActionDialog.addEventListener("click", (event) => {
    if (event.target === clipActionDialog) closeClipActionDialog();
  });
  clipActionDialog.addEventListener("close", () => {
    clipActionTarget = null;
    const trigger = clipActionTrigger;
    clipActionTrigger = null;
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  });
  clipFavoriteAction.addEventListener("click", async () => {
    const clip = clipActionTarget;
    if (!clip) return;
    clipFavoriteAction.disabled = true;
    await toggleFavorite(clip.id);
    clipFavoriteAction.disabled = false;
    closeClipActionDialog();
  });
  clipDeleteAction.addEventListener("click", async () => {
    const clip = clipActionTarget;
    if (!clip) return;
    closeClipActionDialog();
    await deleteClip(clip.id);
  });

  function itemActionInfo(kind, id) {
    if (kind === "project") {
      const item = state.projects.find((project) => Number(project.id) === Number(id));
      return item ? { item, label: "プロジェクト", summary: item.name } : null;
    }
    if (kind === "task") {
      const item = state.tasks.find((task) => Number(task.id) === Number(id));
      return item ? { item, label: "タスク", summary: item.title } : null;
    }
    const item = state.notes.find((note) => Number(note.id) === Number(id));
    return item ? { item, label: "メモ", summary: item.title } : null;
  }

  function closeItemActionDialog() {
    itemActionTarget = null;
    if (itemActionDialog.open) itemActionDialog.close();
    else itemActionDialog.removeAttribute("open");
  }

  function openItemActionDialog(kind, id, trigger) {
    const info = itemActionInfo(kind, id);
    if (!info) return;
    itemActionTarget = { kind, id: Number(id) };
    itemActionTrigger = trigger || null;
    itemActionKicker.textContent = info.label.toUpperCase() + " ACTIONS";
    itemActionTitle.textContent = info.label + "の操作";
    itemActionSummary.textContent = info.summary;
    if (typeof itemActionDialog.showModal === "function") itemActionDialog.showModal();
    else itemActionDialog.setAttribute("open", "");
    itemEditAction.focus();
  }

  itemActionDialog.addEventListener("click", (event) => {
    if (event.target === itemActionDialog) closeItemActionDialog();
  });
  itemActionDialog.addEventListener("close", () => {
    itemActionTarget = null;
    const trigger = itemActionTrigger;
    itemActionTrigger = null;
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  });
  itemEditAction.addEventListener("click", () => {
    const target = itemActionTarget;
    closeItemActionDialog();
    if (!target) return;
    if (target.kind === "project") renderProjectEditor(target.id);
    else if (target.kind === "task") renderTaskEditor(target.id);
    else renderNoteEditor(target.id);
  });
  itemDeleteAction.addEventListener("click", async () => {
    const target = itemActionTarget;
    closeItemActionDialog();
    if (!target) return;
    if (target.kind === "project") await deleteProject(target.id);
    else if (target.kind === "task") await deleteTask(target.id);
    else await deleteNote(target.id);
  });

  projectAttachDialog.addEventListener("click", (event) => {
    if (event.target === projectAttachDialog) projectAttachDialog.close();
  });
  projectAttachDialog.addEventListener("close", () => {
    projectAttachTarget = null;
  });
  projectAttachSelect.addEventListener("change", () => {
    projectAttachSubmit.disabled = !projectAttachSelect.value;
  });
  projectAttachSubmit.addEventListener("click", async () => {
    const target = projectAttachTarget;
    const itemId = Number(projectAttachSelect.value);
    if (!target || !itemId) return;
    projectAttachSubmit.disabled = true;
    try {
      if (target.kind === "clip") {
        await api("/projects/" + target.projectId + "/clips/" + itemId, { method: "POST" });
      } else if (target.kind === "task") {
        await api("/tasks/" + itemId, { method: "PUT", body: JSON.stringify({ project_id: target.projectId }) });
      } else {
        await api("/projects/" + target.projectId + "/notes/" + itemId, { method: "POST" });
      }
      projectAttachDialog.close();
      await loadData(false);
      renderProjectDetail(target.projectId);
      showToast("プロジェクトに添付しました。");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      projectAttachSubmit.disabled = false;
    }
  });

  async function toggleFavorite(id) {
    try {
      const result = await api("/clips/" + id + "/favorite", { method: "PATCH" });
      const clip = state.clips.find((item) => Number(item.id) === id);
      if (clip) clip.is_favorite = Boolean(result?.is_favorite);
      renderHome();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderDetail(id, returnProjectId = null) {
    const clip = state.clips.find((item) => Number(item.id) === id);
    if (!clip) {
      renderHome();
      return;
    }
    state.homeView = "detail";
    state.detailClipId = Number(id);
    state.detailReturnProjectId = returnProjectId == null ? null : Number(returnProjectId);
    const source = safeHref(clip.url);
    const image = clipImageUrl(clip);
    main.innerHTML =
      '<div class="remote-panel">' +
        '<div class="remote-panel-heading">' +
          '<button id="remoteDetailBack" class="remote-quiet-button" type="button">← 戻る</button>' +
          '<div class="remote-card-actions">' +
            '<button id="remoteDetailEdit" class="remote-secondary-button" type="button">編集</button>' +
            '<button id="remoteDetailDelete" class="remote-danger-button" type="button">削除</button>' +
          "</div>" +
        "</div>" +
        '<div class="remote-detail-hero">' +
          (image ? '<img src="' + escapeHtml(image) + '" alt="" />' : '<span class="remote-card-media-placeholder" aria-hidden="true">✦</span>') +
          '<div><p class="remote-page-kicker">' + escapeHtml(clipSourceLabel(clip)) + "</p>" +
          '<h1 class="remote-page-title">' + escapeHtml(clipTitle(clip)) + "</h1>" +
          (clip.is_favorite ? '<span class="remote-detail-favorite">★ お気に入り</span>' : "") +
          "</div>" +
        "</div>" +
        '<dl class="remote-detail-list">' +
          '<div><dt>URL / ファイル</dt><dd>' + (source
            ? '<a href="' + escapeHtml(source) + '" target="_blank" rel="noreferrer">' + escapeHtml(clip.url) + "</a>"
            : escapeHtml(clip.url || "PC内のファイル")) + "</dd></div>" +
          '<div><dt>カテゴリ</dt><dd>' + escapeHtml(categoryName(clip.category_id) || "未設定") + "</dd></div>" +
          '<div><dt>コメント</dt><dd>' + escapeHtml(clip.comment || "コメントはありません。") + "</dd></div>" +
          '<div><dt>タグ</dt><dd>' + (clip.tags?.length ? clip.tags.map((tag) => escapeHtml(tag.name || tag)).join(", ") : "未設定") + "</dd></div>" +
        "</dl>" +
        (clip.clip_type === "local"
          ? '<div class="remote-panel remote-detail-file"><h2>ファイル</h2><a class="remote-secondary-button" href="/clips/' + Number(clip.id) + '/file" target="_blank" rel="noreferrer">ファイルを表示 / ダウンロード</a><pre id="remoteTextPreview" class="remote-preview">プレビューを読み込んでいます…</pre></div>'
          : "") +
      "</div>";

    document.getElementById("remoteDetailBack").addEventListener("click", () => {
      const projectId = state.detailReturnProjectId;
      state.detailReturnProjectId = null;
      if (projectId !== null) {
        state.screen = "projects";
        state.homeView = "list";
        syncNavigation();
        renderProjectDetail(projectId);
      } else {
        renderHome();
      }
    });
    document.getElementById("remoteDetailEdit").addEventListener("click", () => renderEditor(clip, null));
    document.getElementById("remoteDetailDelete").addEventListener("click", () => deleteClip(clip.id));
    if (clip.clip_type === "local") {
      api("/clips/" + Number(clip.id) + "/text-preview")
        .then((data) => {
          const preview = document.getElementById("remoteTextPreview");
          if (preview) preview.textContent = data?.preview || "テキストプレビューはありません。";
        })
        .catch(() => {
          const preview = document.getElementById("remoteTextPreview");
          if (preview) preview.hidden = true;
        });
    }
  }

  async function deleteClip(id) {
    if (!window.confirm("このクリップを削除しますか？")) return;
    try {
      await api("/clips/" + Number(id), { method: "DELETE" });
      await loadData(false);
      renderHome();
      showToast("クリップを削除しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function categoryOptions(selected) {
    return '<option value="">カテゴリなし</option>' + state.categories.map((category) =>
      '<option value="' + Number(category.id) + '"' + (Number(selected) === Number(category.id) ? " selected" : "") + ">" + escapeHtml(category.name) + "</option>"
    ).join("");
  }

  function renderEditor(clip, uploadFile) {
    state.editingClip = clip;
    state.uploadFile = uploadFile;
    state.homeView = "editor";
    state.detailClipId = null;
    const isUpload = Boolean(uploadFile);
    const isEdit = Boolean(clip);
    const tags = Array.isArray(clip?.tags) ? clip.tags.map((tag) => tag.name || tag).join(", ") : "";
    let metadataThumbnailUrl = String(clip?.thumbnail_url || "");
    let metadataTimer = null;
    let metadataRequestId = 0;
    main.innerHTML =
      '<div class="remote-panel">' +
        '<div class="remote-panel-heading"><div><p class="remote-page-kicker">' + (isEdit ? "CLIP EDITOR" : "NEW CLIP") + "</p><h1 class=\"remote-page-title\">" + (isEdit ? "クリップを編集" : "クリップを追加") + "</h1></div></div>" +
        '<form id="remoteClipForm" class="remote-form-grid">' +
          (isEdit || isUpload
            ? '<div class="remote-field full"><span>保存対象</span><div class="remote-inline-input">' + escapeHtml(isUpload ? uploadFile.name : (clip.url || "PC内のファイル")) + "</div></div>"
            : '<label class="remote-field full"><span>URL</span><input name="url" type="url" required placeholder="https://example.com/..." value="" /></label>') +
          '<label class="remote-field"><span>タイトル</span><input name="title" type="text" maxlength="500" autocomplete="off" value="' + escapeHtml(isUpload ? uploadFile.name : (clip?.title || "")) + '"' + (!isEdit && !isUpload ? ' readonly aria-readonly="true" placeholder="URLから自動取得"' : "") + ' /></label>' +
          (!isEdit && !isUpload ? '<p id="remoteClipMetadataStatus" class="remote-field-help full" role="status" aria-live="polite">URLを入力するとタイトルを自動取得します。</p>' : "") +
          (!isEdit && !isUpload ? '<div id="remoteClipMetadataPreview" class="remote-clip-metadata-preview full" hidden><p class="remote-clip-metadata-preview-label">サムネイルプレビュー</p><div class="remote-clip-metadata-preview-frame"><img id="remoteClipMetadataPreviewImage" alt="取得したサムネイルのプレビュー" draggable="false" /><span id="remoteClipMetadataPreviewEmpty" class="remote-clip-metadata-preview-empty">URLを入力すると表示されます。</span></div></div>' : "") +
          '<label class="remote-field"><span>カテゴリ</span><select name="category">' + categoryOptions(clip?.category_id) + "</select></label>" +
          '<label class="remote-field"><span>タグ（カンマ区切り）</span><input name="tags" type="text" autocomplete="off" value="' + escapeHtml(tags) + '" placeholder="例：読書,あとで見る" /></label>' +
          '<label class="remote-field full"><span>コメント</span><textarea name="comment" rows="5" maxlength="10000" placeholder="メモを残す">' + escapeHtml(clip?.comment || "") + "</textarea></label>" +
          '<div class="remote-form-actions full"><button id="remoteClipCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">' + (isEdit ? "保存する" : "追加する") + "</button></div>" +
          '<p id="remoteClipError" class="remote-form-error full" role="alert" aria-live="polite"></p>' +
        "</form>" +
      "</div>";
    if (!isEdit && !isUpload) {
      main.querySelector("[name=url]").focus();
    } else {
      main.querySelector("[name=title]").focus();
    }
    document.getElementById("remoteClipCancel").addEventListener("click", () => {
      state.editingClip = null;
      state.uploadFile = null;
      renderHome();
    });
    document.getElementById("remoteClipForm").addEventListener("submit", (event) => submitClipForm(event, () => metadataThumbnailUrl));
    const urlInput = main.querySelector("[name=url]");
    const titleInput = main.querySelector("[name=title]");
    const metadataStatus = main.querySelector("#remoteClipMetadataStatus");
    const metadataPreview = main.querySelector("#remoteClipMetadataPreview");
    const metadataPreviewImage = main.querySelector("#remoteClipMetadataPreviewImage");
    const metadataPreviewEmpty = main.querySelector("#remoteClipMetadataPreviewEmpty");
    const updateMetadataPreview = () => {
      if (!metadataPreview || !metadataPreviewImage || !metadataPreviewEmpty) return;
      const rawThumbnail = metadataThumbnailUrl || youtubeThumbnailUrl(urlInput?.value);
      const previewUrl = rawThumbnail.startsWith("/")
        ? rawThumbnail
        : (safeHref(rawThumbnail) ? "/thumbnail-proxy?url=" + encodeURIComponent(rawThumbnail) : "");
      if (!previewUrl) {
        metadataPreview.hidden = true;
        metadataPreviewImage.removeAttribute("src");
        metadataPreviewImage.hidden = false;
        metadataPreviewEmpty.hidden = false;
        metadataPreviewEmpty.textContent = "URLを入力すると表示されます。";
        return;
      }
      metadataPreview.hidden = false;
      metadataPreviewImage.hidden = false;
      metadataPreviewEmpty.hidden = true;
      metadataPreviewEmpty.textContent = "サムネイルを表示できません。保存時に再試行します。";
      metadataPreviewImage.src = previewUrl;
    };
    metadataPreviewImage?.addEventListener("error", () => {
      metadataPreviewImage.hidden = true;
      metadataPreviewEmpty.hidden = false;
      metadataPreviewEmpty.textContent = "サムネイルを表示できません。保存時に再試行します。";
    });
    const requestMetadata = async () => {
      const url = String(urlInput.value || "").trim();
      const requestId = ++metadataRequestId;
      if (!safeHref(url)) {
        metadataThumbnailUrl = "";
        titleInput.value = "";
        if (metadataStatus) metadataStatus.textContent = "URLを入力するとタイトルを自動取得します。";
        updateMetadataPreview();
        return;
      }
      if (metadataStatus) metadataStatus.textContent = "タイトルを取得しています…";
      try {
        const metadata = await api("/url-metadata?url=" + encodeURIComponent(url));
        if (requestId !== metadataRequestId || String(urlInput.value || "").trim() !== url) return;
        titleInput.value = metadata?.title || "";
        metadataThumbnailUrl = metadata?.thumbnail_url || "";
        updateMetadataPreview();
        if (metadataStatus) metadataStatus.textContent = metadata?.title
          ? "タイトルを更新しました。内容を確認してから「追加する」を押してください。"
          : "このURLからタイトルを取得できませんでした。保存時に再試行します。";
      } catch {
        if (requestId !== metadataRequestId) return;
        updateMetadataPreview();
        if (metadataStatus) metadataStatus.textContent = "タイトルを取得できませんでした。保存時に再試行します。";
      }
    };
    urlInput?.addEventListener("input", () => {
      if (metadataTimer !== null) window.clearTimeout(metadataTimer);
      metadataThumbnailUrl = "";
      titleInput.value = "";
      if (metadataStatus) metadataStatus.textContent = "タイトルを取得しています…";
      updateMetadataPreview();
      metadataTimer = window.setTimeout(requestMetadata, 320);
    });
    urlInput?.addEventListener("blur", () => {
      if (metadataTimer !== null) window.clearTimeout(metadataTimer);
      metadataTimer = null;
      requestMetadata();
    });
  }

  async function submitClipForm(event, getMetadataThumbnailUrl = () => "") {
    event.preventDefault();
    const form = event.currentTarget;
    const errorEl = document.getElementById("remoteClipError");
    const submit = form.querySelector("button[type=submit]");
    const formData = new FormData(form);
    submit.disabled = true;
    try {
      const title = String(formData.get("title") || "").trim();
      const comment = String(formData.get("comment") || "").trim();
      const category = String(formData.get("category") || "").trim();
      const tags = parseTags(formData.get("tags"));
      let result;
      if (state.uploadFile) {
        const upload = new FormData();
        upload.append("file", state.uploadFile);
        upload.append("title", title);
        upload.append("comment", comment);
        upload.append("category", category);
        upload.append("tags", tags.join(","));
        result = await api("/clips/local", { method: "POST", body: upload });
      } else if (state.editingClip) {
        result = await api("/clips/" + Number(state.editingClip.id), {
          method: "PUT",
          body: JSON.stringify({ title, comment, category: category || null, tags }),
        });
    } else {
      const url = String(formData.get("url") || "").trim();
      if (!safeHref(url)) throw new Error("http:// または https:// のURLを入力してください。");
      const thumbnailUrl = getMetadataThumbnailUrl() || youtubeThumbnailUrl(url);
      result = await api("/clips", {
          method: "POST",
          body: JSON.stringify({
            url,
            title: title || null,
            thumbnail_url: thumbnailUrl || null,
            comment: comment || null,
            category: category || null,
            tags,
            clip_type: "url",
          }),
        });
      }
      await loadData(false);
      state.editingClip = null;
      state.uploadFile = null;
      if (result?.id) renderDetail(Number(result.id));
      else renderHome();
      showToast("保存しました。");
    } catch (error) {
      errorEl.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  }

  function renderWorkspace() {
    const tasksActive = state.workspaceTab === "tasks";
    const visibleTasks = state.tasks.filter((task) => statusMatches(task, state.workspaceStatus, "task"));
    const visibleNotes = state.notes.filter((note) => statusMatches(note, state.workspaceStatus, "note"));
    main.innerHTML =
      renderPageHeader("WORKSPACE", "タスク・メモ", "Android版と同じPC上のタスクとメモをWebから確認します。") +
      '<section class="remote-panel">' +
        '<div class="remote-tab-row"><button class="remote-tab ' + (tasksActive ? "active" : "") + '" data-workspace-tab="tasks" type="button">タスク ' + state.tasks.length + '</button><button class="remote-tab ' + (!tasksActive ? "active" : "") + '" data-workspace-tab="notes" type="button">メモ ' + state.notes.length + "</button></div>" +
        renderStatusFilters(state.workspaceStatus, "workspace") +
        (tasksActive ? renderTaskList(visibleTasks) : renderNoteList(visibleNotes)) +
      "</section>";
    main.querySelectorAll("[data-workspace-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        state.workspaceTab = button.dataset.workspaceTab;
        renderWorkspace();
      });
    });
    main.querySelectorAll('[data-status-scope="workspace"]').forEach((button) => {
      button.addEventListener("click", () => {
        state.workspaceStatus = button.dataset.statusFilter || "active";
        renderWorkspace();
      });
    });
    if (tasksActive) {
      document.getElementById("remoteNewTask")?.addEventListener("click", () => renderTaskEditor(null));
      main.querySelectorAll("[data-task-toggle]").forEach((input) => {
        input.addEventListener("click", (event) => event.stopPropagation());
        input.addEventListener("change", () => toggleTask(Number(input.dataset.taskToggle)));
      });
      main.querySelectorAll("[data-task-row]").forEach((row) => {
        bindLongPress(row, {
          onTap: () => renderTaskEditor(Number(row.dataset.taskRow)),
          onLongPress: () => openItemActionDialog("task", Number(row.dataset.taskRow), row),
        });
      });
    } else {
      document.getElementById("remoteNewNote")?.addEventListener("click", () => renderNoteEditor(null));
      main.querySelectorAll("[data-note-row]").forEach((row) => {
        bindLongPress(row, {
          onTap: () => renderNoteEditor(Number(row.dataset.noteRow)),
          onLongPress: () => openItemActionDialog("note", Number(row.dataset.noteRow), row),
        });
      });
    }
  }

  function renderTaskList(tasks) {
    const highestPriority = highestTaskPriority(tasks);
    const rows = tasks.map((task) => {
      const priority = taskPriorityValue(task);
      const notes = taskNotes(task);
      const project = task.project_id ? (projectName(task.project_id) || "不明なプロジェクト") : "設定なし";
      const noteLabel = notes.length ? notes.map((note) => note.title).join("、") : "設定なし";
      const isHighest = !task.is_done && priority !== null && priority === highestPriority;
      const relatedLabel = "プロジェクト: " + project + " · メモ: " + noteLabel;
      const ariaLabel = "タスク「" + task.title + "」を編集。" + taskPriorityLabel(task) + "。" + relatedLabel + (isHighest ? "。最優先" : "");
      return '<div class="remote-list-row remote-interactive-row' + (isHighest ? " remote-task-priority-highlight" : "") + '" data-task-row="' + Number(task.id) + '" tabindex="0" role="button" aria-label="' + escapeHtml(ariaLabel) + '">' +
        '<label class="remote-list-checkbox"><input type="checkbox" data-task-toggle="' + Number(task.id) + '" aria-label="' + (task.is_done ? "未完了に戻す" : "完了にする") + '"' + (task.is_done ? " checked" : "") + ' /></label>' +
        '<div class="remote-list-main"><div class="remote-task-title-row"><p class="remote-list-title ' + (task.is_done ? "done" : "") + '">' + escapeHtml(task.title) + "</p><div class=\"remote-task-badges\"><span class=\"remote-task-priority\">" + escapeHtml(taskPriorityLabel(task)) + "</span>" + (isHighest ? '<span class="remote-task-priority-best">最優先</span>' : "") + "</div></div>" +
        '<p class="remote-list-subtitle">' + (task.due_date ? "期限 " + escapeHtml(task.due_date) : "期限なし") + "</p>" +
        '<p class="remote-list-related">' + escapeHtml(relatedLabel) + "</p></div></div>";
    }).join("");
    return '<div class="remote-panel-heading"><h2>タスク</h2><button id="remoteNewTask" class="remote-primary-button" type="button">＋ タスク追加</button></div>' +
      (tasks.length ? '<div class="remote-task-list">' + rows + "</div>" : '<div class="remote-empty">この状態のタスクはありません。</div>');
  }

  function renderNoteList(notes) {
    return '<div class="remote-panel-heading"><h2>メモ</h2><button id="remoteNewNote" class="remote-primary-button" type="button">＋ メモ追加</button></div>' +
      (notes.length ? '<div class="remote-note-list">' + notes.map((note) =>
        '<div class="remote-list-row remote-interactive-row" data-note-row="' + Number(note.id) + '" tabindex="0" role="button" aria-label="メモ「' + escapeHtml(note.title) + '」を編集"><div class="remote-list-main"><p class="remote-list-title ' + (noteIsDone(note) ? "done" : "") + '">' + escapeHtml(note.title) + "</p><p class=\"remote-list-subtitle\">" + escapeHtml((note.body || "").slice(0, 180) || "本文なし") + (noteIsDone(note) ? " · 完了済み" : "") + "</p></div></div>"
      ).join("") + "</div>" : '<div class="remote-empty">この状態のメモはありません。</div>');
  }

  function renderTaskEditor(id, returnProjectId = null) {
    const task = id ? state.tasks.find((item) => Number(item.id) === Number(id)) : null;
    state.editingTask = task;
    state.editorReturnProjectId = returnProjectId == null ? null : Number(returnProjectId);
    main.innerHTML =
      '<div class="remote-panel"><div class="remote-panel-heading"><div><p class="remote-page-kicker">TASK</p><h1 class="remote-page-title">' + (task ? "タスクを編集" : "タスクを追加") + '</h1></div></div>' +
      '<form id="remoteTaskForm" class="remote-form-grid">' +
      '<label class="remote-field full"><span>タイトル</span><input name="title" required maxlength="500" value="' + escapeHtml(task?.title || "") + '" /></label>' +
      '<label class="remote-field"><span>期限</span><input name="due_date" type="date" value="' + escapeHtml(task?.due_date || "") + '" /></label>' +
      '<label class="remote-field"><span>優先度</span><select name="priority">' + priorityOptions(task?.priority) + '</select><small class="remote-field-help">優先度1が最も高い優先度です。</small></label>' +
      '<div class="remote-form-actions full"><button id="remoteTaskCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">保存する</button></div><p id="remoteTaskError" class="remote-form-error full" role="alert"></p></form></div>';
    main.querySelector("[name=title]").focus();
    document.getElementById("remoteTaskCancel").addEventListener("click", () => {
      const projectId = state.editorReturnProjectId;
      state.editingTask = null;
      state.editorReturnProjectId = null;
      if (projectId !== null) renderProjectDetail(projectId);
      else renderWorkspace();
    });
    document.getElementById("remoteTaskForm").addEventListener("submit", submitTaskForm);
  }

  async function submitTaskForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const errorEl = document.getElementById("remoteTaskError");
    const data = new FormData(form);
    const payload = {
      title: String(data.get("title") || "").trim(),
      due_date: String(data.get("due_date") || "") || null,
      priority: String(data.get("priority") || "") ? Number(data.get("priority")) : null,
    };
    try {
      if (!payload.title) throw new Error("タイトルを入力してください。");
      if (state.editingTask) {
        await api("/tasks/" + Number(state.editingTask.id), { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/tasks", { method: "POST", body: JSON.stringify(payload) });
      }
      await loadData(false);
      const projectId = state.editorReturnProjectId;
      state.editingTask = null;
      state.editorReturnProjectId = null;
      if (projectId !== null) renderProjectDetail(projectId);
      else renderWorkspace();
      showToast("タスクを保存しました。");
    } catch (error) {
      errorEl.textContent = error.message;
    }
  }

  async function toggleTask(id) {
    try {
      await api("/tasks/" + id + "/toggle", { method: "PATCH" });
      await loadData(false);
      renderWorkspace();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function deleteTask(id) {
    if (!window.confirm("このタスクを削除しますか？")) return;
    try {
      await api("/tasks/" + id, { method: "DELETE" });
      await loadData(false);
      renderWorkspace();
      showToast("タスクを削除しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderNoteEditor(id, returnProjectId = null) {
    const note = id ? state.notes.find((item) => Number(item.id) === Number(id)) : null;
    state.editingNote = note;
    state.editorReturnProjectId = returnProjectId == null ? null : Number(returnProjectId);
    main.innerHTML =
      '<div class="remote-panel"><div class="remote-panel-heading"><div><p class="remote-page-kicker">NOTE</p><h1 class="remote-page-title">' + (note ? "メモを編集" : "メモを追加") + '</h1></div></div>' +
      '<form id="remoteNoteForm" class="remote-form-grid"><label class="remote-field full"><span>タイトル</span><input name="title" required maxlength="500" value="' + escapeHtml(note?.title || "") + '" /></label>' +
      '<label class="remote-field full"><span>本文</span><textarea name="body" rows="12" maxlength="100000">' + escapeHtml(note?.body || "") + '</textarea></label>' +
      '<div class="remote-form-actions full"><button id="remoteNoteCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">保存する</button></div><p id="remoteNoteError" class="remote-form-error full" role="alert"></p></form></div>';
    main.querySelector("[name=title]").focus();
    document.getElementById("remoteNoteCancel").addEventListener("click", () => {
      const projectId = state.editorReturnProjectId;
      state.editingNote = null;
      state.editorReturnProjectId = null;
      if (projectId !== null) renderProjectDetail(projectId);
      else renderWorkspace();
    });
    document.getElementById("remoteNoteForm").addEventListener("submit", submitNoteForm);
  }

  async function submitNoteForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const errorEl = document.getElementById("remoteNoteError");
    const payload = {
      title: String(data.get("title") || "").trim(),
      body: String(data.get("body") || ""),
    };
    try {
      if (!payload.title) throw new Error("タイトルを入力してください。");
      if (state.editingNote) {
        await api("/notes/" + Number(state.editingNote.id), { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/notes", { method: "POST", body: JSON.stringify(payload) });
      }
      await loadData(false);
      const projectId = state.editorReturnProjectId;
      state.editingNote = null;
      state.editorReturnProjectId = null;
      if (projectId !== null) renderProjectDetail(projectId);
      else renderWorkspace();
      showToast("メモを保存しました。");
    } catch (error) {
      errorEl.textContent = error.message;
    }
  }

  async function deleteNote(id) {
    if (!window.confirm("このメモを削除しますか？")) return;
    try {
      await api("/notes/" + id, { method: "DELETE" });
      await loadData(false);
      renderWorkspace();
      showToast("メモを削除しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderProjects() {
    state.projectDetailId = null;
    const projects = state.projects.filter((project) => statusMatches(project, state.projectStatus, "project"));
    main.innerHTML =
      renderPageHeader("PROJECTS", "プロジェクト", "クリップ・タスク・メモをまとめるPC側のプロジェクトです.", '<button id="remoteNewProject" class="remote-primary-button" type="button">＋ プロジェクト追加</button>') +
      '<section class="remote-panel">' +
      renderStatusFilters(state.projectStatus, "projects") +
      (projects.length ? '<div class="remote-project-list">' + projects.map((project) =>
        '<div class="remote-list-row remote-interactive-row" data-project-row="' + Number(project.id) + '" tabindex="0" role="button" aria-label="プロジェクト「' + escapeHtml(project.name) + '」を開く">' +
        '<label class="remote-list-checkbox"><input type="checkbox" data-project-toggle="' + Number(project.id) + '" aria-label="' + escapeHtml(project.name) + 'の完了状態を切り替え"' + (project.is_done ? " checked" : "") + ' /></label>' +
        '<div class="remote-list-main"><p class="remote-list-title ' + (project.is_done ? "done" : "") + '">' + escapeHtml(project.name) + "</p><p class=\"remote-list-subtitle\">" + escapeHtml(project.description || "説明なし") + "</p></div></div>"
      ).join("") + "</div>" : '<div class="remote-empty">この状態のプロジェクトはありません。</div>') +
      "</section>";
    document.getElementById("remoteNewProject").addEventListener("click", () => renderProjectEditor(null));
    main.querySelectorAll('[data-status-scope="projects"]').forEach((button) => {
      button.addEventListener("click", () => {
        state.projectStatus = button.dataset.statusFilter || "active";
        renderProjects();
      });
    });
    main.querySelectorAll("[data-project-toggle]").forEach((input) => {
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("change", () => toggleProject(Number(input.dataset.projectToggle)));
    });
    main.querySelectorAll("[data-project-row]").forEach((row) => {
      bindLongPress(row, {
        onTap: () => renderProjectDetail(Number(row.dataset.projectRow)),
        onLongPress: () => openItemActionDialog("project", Number(row.dataset.projectRow), row),
      });
    });
  }

  function openProjectLinkedItem(kind, id, projectId) {
    const itemId = Number(id);
    const returnProjectId = Number(projectId);
    if (kind === "clip") {
      state.screen = "home";
      state.homeView = "detail";
      state.projectDetailId = returnProjectId;
      syncNavigation();
      renderDetail(itemId, returnProjectId);
    } else if (kind === "task") {
      renderTaskEditor(itemId, returnProjectId);
    } else {
      renderNoteEditor(itemId, returnProjectId);
    }
  }

  function projectLinkSection(title, kind, items, projectId, emptyText) {
    const rows = items.length
      ? '<div class="remote-project-link-list">' + items.map((item) => {
        const done = kind === "task" ? Boolean(item.is_done) : kind === "note" ? noteIsDone(item) : false;
        const subtitle = kind === "clip"
          ? (item.url || "PC内のファイル")
          : kind === "task"
            ? (taskPriorityLabel(item) + " · " + (item.due_date ? "期限 " + item.due_date : "期限なし"))
            : ((item.body || "").slice(0, 160) || "本文なし");
        const label = kind === "clip" ? clipTitle(item) : item.title;
        const image = kind === "clip" ? clipImageUrl(item) : "";
        const media = kind === "clip"
          ? (image
            ? '<span class="remote-project-link-media"><img src="' + escapeHtml(image) + '" alt="" loading="lazy" draggable="false" /></span>'
            : '<span class="remote-project-link-media remote-project-link-media-placeholder" aria-hidden="true">✦</span>')
          : "";
        const openLabel = title + "「" + label + "」を開く";
        return '<div class="remote-project-link-row"><button class="remote-project-link-open" type="button" data-project-open-kind="' + escapeHtml(kind) + '" data-project-open-id="' + Number(item.id) + '" data-project-open-project="' + Number(projectId) + '" aria-label="' + escapeHtml(openLabel) + '">' + media + '<div class="remote-list-main"><p class="remote-list-title ' + (done ? "done" : "") + '">' + escapeHtml(label) + "</p><p class=\"remote-list-subtitle\">" + escapeHtml(subtitle) + "</p></div></button><button class=\"remote-list-unlink\" type=\"button\" data-project-unlink-kind=\"" + escapeHtml(kind) + "\" data-project-unlink-id=\"" + Number(item.id) + '" aria-label="' + escapeHtml(title + "「" + label + "」の添付を解除") + '">解除</button></div>';
      }).join("") + "</div>"
      : '<div class="remote-empty remote-project-link-empty">' + escapeHtml(emptyText) + "</div>";
    return '<section class="remote-project-links remote-panel"><div class="remote-panel-heading"><h2>' + title + "</h2><button class=\"remote-secondary-button\" type=\"button\" data-project-attach=\"" + kind + "\">＋ 添付</button></div>" + rows + "</section>";
  }

  function renderProjectDetail(id) {
    const project = state.projects.find((item) => Number(item.id) === Number(id));
    if (!project) {
      renderProjects();
      return;
    }
    state.projectDetailId = Number(id);
    const clips = state.clips.filter((clip) => linkedToProject(clip, id));
    const tasks = state.tasks.filter((task) => Number(task.project_id) === Number(id));
    const notes = state.notes.filter((note) => linkedToProject(note, id));
    main.innerHTML =
      '<div class="remote-project-detail-header remote-panel"><div class="remote-panel-heading"><button id="remoteProjectDetailBack" class="remote-quiet-button" type="button">← プロジェクト一覧</button><label class="remote-detail-check"><input id="remoteProjectDetailDone" type="checkbox"' + (project.is_done ? " checked" : "") + ' />完了</label></div><p class="remote-page-kicker">PROJECT</p><h1 class="remote-page-title">' + escapeHtml(project.name) + "</h1>" + (project.description ? '<p class="remote-page-description">' + escapeHtml(project.description) + "</p>" : "") + "</div>" +
      projectLinkSection("クリップ", "clip", clips, id, "このプロジェクトにクリップはありません。") +
      projectLinkSection("タスク", "task", tasks, id, "このプロジェクトにタスクはありません。") +
      projectLinkSection("メモ", "note", notes, id, "このプロジェクトにメモはありません。");
    document.getElementById("remoteProjectDetailBack").addEventListener("click", renderProjects);
    document.getElementById("remoteProjectDetailDone").addEventListener("change", () => toggleProject(Number(id), true));
    main.querySelectorAll("[data-project-open-kind]").forEach((button) => {
      button.addEventListener("click", () => openProjectLinkedItem(
        button.dataset.projectOpenKind,
        Number(button.dataset.projectOpenId),
        Number(button.dataset.projectOpenProject),
      ));
    });
    main.querySelectorAll("[data-project-attach]").forEach((button) => {
      button.addEventListener("click", () => openProjectAttachDialog(Number(id), button.dataset.projectAttach));
    });
    main.querySelectorAll("[data-project-unlink-kind]").forEach((button) => {
      button.addEventListener("click", () => unlinkProjectItem(Number(id), button.dataset.projectUnlinkKind, Number(button.dataset.projectUnlinkId)));
    });
  }

  function projectAttachItems(kind, projectId) {
    if (kind === "clip") return state.clips.filter((item) => !linkedToProject(item, projectId));
    if (kind === "task") return state.tasks.filter((item) => Number(item.project_id) !== Number(projectId));
    return state.notes.filter((item) => !linkedToProject(item, projectId));
  }

  function openProjectAttachDialog(projectId, kind) {
    const labels = { clip: "クリップ", task: "タスク", note: "メモ" };
    const label = labels[kind] || "項目";
    const items = projectAttachItems(kind, projectId);
    projectAttachTarget = { projectId: Number(projectId), kind };
    projectAttachTitle.textContent = label + "を添付";
    projectAttachSummary.textContent = projectName(projectId) + "に追加する" + label + "を選択してください。";
    projectAttachLabel.textContent = "添付する" + label;
    projectAttachSelect.innerHTML = items.length
      ? '<option value="">選択してください…</option>' + items.map((item) => '<option value="' + Number(item.id) + '">' + escapeHtml(kind === "clip" ? clipTitle(item) : item.title) + "</option>").join("")
      : '<option value="">添付できる' + label + "がありません。</option>";
    projectAttachSelect.disabled = items.length === 0;
    projectAttachSubmit.disabled = true;
    if (typeof projectAttachDialog.showModal === "function") projectAttachDialog.showModal();
    else projectAttachDialog.setAttribute("open", "");
    projectAttachSelect.focus();
  }

  async function unlinkProjectItem(projectId, kind, itemId) {
    try {
      if (kind === "clip") {
        await api("/projects/" + projectId + "/clips/" + itemId, { method: "DELETE" });
      } else if (kind === "task") {
        await api("/tasks/" + itemId, { method: "PUT", body: JSON.stringify({ project_id: null }) });
      } else {
        await api("/projects/" + projectId + "/notes/" + itemId, { method: "DELETE" });
      }
      await loadData(false);
      renderProjectDetail(projectId);
      showToast("プロジェクトから解除しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderProjectEditor(id) {
    const project = id ? state.projects.find((item) => Number(item.id) === Number(id)) : null;
    state.editingProject = project;
    state.editorReturnProjectId = null;
    main.innerHTML =
      '<div class="remote-panel"><div class="remote-panel-heading"><div><p class="remote-page-kicker">PROJECT</p><h1 class="remote-page-title">' + (project ? "プロジェクトを編集" : "プロジェクトを追加") + '</h1></div></div>' +
      '<form id="remoteProjectForm" class="remote-form-grid"><label class="remote-field full"><span>名前</span><input name="name" required maxlength="200" value="' + escapeHtml(project?.name || "") + '" /></label><label class="remote-field full"><span>説明</span><textarea name="description" rows="6" maxlength="10000">' + escapeHtml(project?.description || "") + '</textarea></label><div class="remote-form-actions full"><button id="remoteProjectCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">保存する</button></div><p id="remoteProjectError" class="remote-form-error full" role="alert"></p></form></div>';
    main.querySelector("[name=name]").focus();
    document.getElementById("remoteProjectCancel").addEventListener("click", renderProjects);
    document.getElementById("remoteProjectForm").addEventListener("submit", submitProjectForm);
  }

  async function submitProjectForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const errorEl = document.getElementById("remoteProjectError");
    const payload = {
      name: String(data.get("name") || "").trim(),
      description: String(data.get("description") || ""),
    };
    try {
      if (!payload.name) throw new Error("名前を入力してください。");
      if (state.editingProject) {
        await api("/projects/" + Number(state.editingProject.id), { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/projects", { method: "POST", body: JSON.stringify(payload) });
      }
      await loadData(false);
      state.editingProject = null;
      renderProjects();
      showToast("プロジェクトを保存しました。");
    } catch (error) {
      errorEl.textContent = error.message;
    }
  }

  async function toggleProject(id, keepDetail = false) {
    try {
      await api("/projects/" + id + "/toggle", { method: "PATCH" });
      await loadData(false);
      if (keepDetail) renderProjectDetail(id);
      else renderProjects();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function deleteProject(id) {
    if (!window.confirm("このプロジェクトを削除しますか？")) return;
    try {
      await api("/projects/" + id, { method: "DELETE" });
      await loadData(false);
      renderProjects();
      showToast("プロジェクトを削除しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function readSetting(key, fallback) {
    try {
      const data = await api("/settings/" + key);
      return data?.value == null ? fallback : String(data.value);
    } catch {
      return fallback;
    }
  }

  async function saveSetting(key, value) {
    try {
      await api("/settings/" + key, {
        method: "PUT",
        body: JSON.stringify({ value: String(value) }),
      });
      showToast("設定を保存しました。");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function renderSettings() {
    const renderToken = ++settingsRenderToken;
    main.innerHTML =
      renderPageHeader("APP SETTINGS", "アプリ設定", "PC側に保存される設定です。Web入口の認証設定はPCの設定画面から管理します。") +
      '<section class="remote-panel"><div id="remoteSettingsLoading" class="remote-loading">設定を読み込んでいます…</div><div id="remoteSettingsForm" hidden>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>タスク作成時に同名の空メモを作成</strong><small>タスクとメモを一緒に管理します。</small></span><input id="remoteSettingTaskNote" type="checkbox" /></label>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>プロジェクト作成時に同名の空メモを作成</strong><small>プロジェクトの概要メモを自動で用意します。</small></span><input id="remoteSettingProjectNote" type="checkbox" /></label>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>完了タスクの自動削除</strong><small>PC側のメンテナンス設定です。</small></span><select id="remoteSettingTaskDelete"><option value="3d">3日後</option><option value="1w">1週間後</option><option value="1m">1か月後</option><option value="never">自動削除しない</option></select></label>' +
      '</div><p id="remoteSettingsError" class="remote-form-error" role="alert" hidden></p></section>';
    const loadingEl = document.getElementById("remoteSettingsLoading");
    const formEl = document.getElementById("remoteSettingsForm");
    const errorEl = document.getElementById("remoteSettingsError");
    try {
      const values = await Promise.all([
        readSetting("auto_create_note_on_task", "false"),
        readSetting("auto_create_note_on_project", "false"),
        readSetting("task_auto_delete", "1w"),
      ]);
      if (renderToken !== settingsRenderToken || !loadingEl?.isConnected) return;
      const taskNoteEl = document.getElementById("remoteSettingTaskNote");
      const projectNoteEl = document.getElementById("remoteSettingProjectNote");
      const taskDeleteEl = document.getElementById("remoteSettingTaskDelete");
      taskNoteEl.checked = values[0] === "true";
      projectNoteEl.checked = values[1] === "true";
      taskDeleteEl.value = values[2];
      taskNoteEl.addEventListener("change", (event) => saveSetting("auto_create_note_on_task", event.target.checked));
      projectNoteEl.addEventListener("change", (event) => saveSetting("auto_create_note_on_project", event.target.checked));
      taskDeleteEl.addEventListener("change", (event) => saveSetting("task_auto_delete", event.target.value));
    } catch (error) {
      if (renderToken !== settingsRenderToken || !loadingEl?.isConnected) return;
      if (errorEl) {
        errorEl.textContent = error.message || "設定を読み込めませんでした。";
        errorEl.hidden = false;
      }
    } finally {
      if (renderToken === settingsRenderToken && loadingEl?.isConnected) {
        loadingEl.hidden = true;
        if (formEl) formEl.hidden = false;
      }
    }
  }

  async function loadData(showLoading = true) {
    if (state.loading) return;
    state.loading = true;
    if (showLoading) main.innerHTML = '<div class="remote-loading" role="status">PCのデータを読み込んでいます…</div>';
    try {
      const values = await Promise.all([
        api("/clips"),
        api("/categories"),
        api("/tags"),
        api("/tasks"),
        api("/notes"),
        api("/projects"),
      ]);
      const nextSignature = JSON.stringify(values);
      const changed = nextSignature !== state.dataSignature;
      state.dataSignature = nextSignature;
      state.clips = values[0] || [];
      state.categories = values[1] || [];
      state.tags = values[2] || [];
      state.tasks = values[3] || [];
      state.notes = values[4] || [];
      state.projects = values[5] || [];
      return changed;
    } catch (error) {
      main.innerHTML = '<div class="remote-empty"><div><p>' + escapeHtml(error.message) + "</p><button id=\"remoteRetryData\" class=\"remote-primary-button\" type=\"button\">再読み込み</button></div></div>";
      document.getElementById("remoteRetryData")?.addEventListener("click", () => loadData(true));
    } finally {
      state.loading = false;
    }
  }

  function syncNavigation() {
    document.querySelectorAll("[data-screen]").forEach((button) => {
      button.classList.toggle("active", button.dataset.screen === state.screen);
    });
  }

  function renderCurrentScreen() {
    syncNavigation();
    if (state.screen === "home") {
      if (state.homeView === "detail" && state.detailClipId !== null) renderDetail(state.detailClipId, state.detailReturnProjectId);
      else if (state.homeView === "list") renderHome();
    } else if (state.screen === "workspace") renderWorkspace();
    else if (state.screen === "projects") {
      if (state.projectDetailId !== null) renderProjectDetail(state.projectDetailId);
      else renderProjects();
    }
    else if (state.screen === "settings") renderSettings();
  }

  function openDrawer() {
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    backdrop.hidden = false;
    menuButton.setAttribute("aria-expanded", "true");
    drawerClose.focus();
  }

  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    backdrop.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
  }

  document.querySelectorAll("[data-screen]").forEach((button) => {
    button.addEventListener("click", () => {
      state.screen = button.dataset.screen;
      state.homeView = "list";
      state.detailClipId = null;
      state.detailReturnProjectId = null;
      state.projectDetailId = null;
      state.editingClip = null;
      state.uploadFile = null;
      state.editingTask = null;
      state.editingNote = null;
      state.editingProject = null;
      state.editorReturnProjectId = null;
      closeClipActionDialog();
      closeItemActionDialog();
      if (projectAttachDialog.open) projectAttachDialog.close();
      closeDrawer();
      renderCurrentScreen();
    });
  });
  menuButton.addEventListener("click", openDrawer);
  drawerClose.addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);
  document.getElementById("remoteLogoutButton").addEventListener("click", async () => {
    if (!window.confirm("このブラウザからログアウトしますか？")) return;
    try {
      await fetch("/remote/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      window.location.assign("/remote-login");
    }
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    fileInput.value = "";
    if (file) renderEditor(null, file);
  });

  function hasOpenRemoteDialog() {
    return [clipActionDialog, itemActionDialog, projectAttachDialog].some((dialog) => dialog.open || dialog.hasAttribute("open"));
  }

  async function refreshRemoteData() {
    if (
      state.loading ||
      state.homeView === "editor" ||
      state.editingClip ||
      state.uploadFile ||
      state.editingTask ||
      state.editingNote ||
      state.editingProject ||
      hasOpenRemoteDialog()
    ) return;
    const view = {
      screen: state.screen,
      homeView: state.homeView,
      detailClipId: state.detailClipId,
      projectDetailId: state.projectDetailId,
    };
    const changed = await loadData(false);
    if (!changed || hasOpenRemoteDialog()) return;
    if (
      view.screen !== state.screen ||
      view.homeView !== state.homeView ||
      view.detailClipId !== state.detailClipId ||
      view.projectDetailId !== state.projectDetailId ||
      state.homeView === "editor" ||
      state.editingClip ||
      state.uploadFile ||
      state.editingTask ||
      state.editingNote ||
      state.editingProject
    ) return;
    if (state.screen !== "settings") renderCurrentScreen();
  }

  loadData(true).then(renderCurrentScreen);
  window.setInterval(async () => {
    await refreshRemoteData();
  }, 5000);
  window.addEventListener("focus", refreshRemoteData);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshRemoteData();
  });
})();
