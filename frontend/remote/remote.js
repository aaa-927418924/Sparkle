(() => {
  const main = document.getElementById("remoteMain");
  const fileInput = document.getElementById("remoteFileInput");
  const toast = document.getElementById("remoteToast");
  const drawer = document.getElementById("remoteDrawer");
  const backdrop = document.getElementById("remoteDrawerBackdrop");
  const menuButton = document.getElementById("remoteMenuButton");
  const drawerClose = document.getElementById("remoteDrawerClose");
  if (!main || !fileInput || !toast || !drawer || !backdrop || !menuButton || !drawerClose) return;

  const state = {
    screen: "home",
    workspaceTab: "tasks",
    clips: [],
    categories: [],
    tags: [],
    tasks: [],
    notes: [],
    projects: [],
    search: "",
    category: "",
    favoritesOnly: false,
    sort: "date_desc",
    editingClip: null,
    uploadFile: null,
    editingTask: null,
    editingNote: null,
    editingProject: null,
    loading: false,
  };
  let toastTimer = null;

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

  function categoryName(categoryId) {
    const category = state.categories.find((item) => Number(item.id) === Number(categoryId));
    return category ? category.name : "";
  }

  function clipImageUrl(clip) {
    if (!clip?.thumbnail_url) return "";
    const raw = String(clip.thumbnail_url);
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
      '<span class="remote-chip">' + escapeHtml(tag.name || tag) + "</span>"
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
    return (
      '<article class="remote-card">' +
        '<div class="remote-card-media">' +
        (image
          ? '<img src="' + escapeHtml(image) + '" alt="" loading="lazy" />'
          : '<span class="remote-card-media-placeholder" aria-hidden="true">' + (clip.clip_type === "local" ? "▧" : "✦") + "</span>") +
        "</div>" +
        '<div class="remote-card-body">' +
          '<h2 class="remote-card-title">' + escapeHtml(clipTitle(clip)) + "</h2>" +
          '<div class="remote-card-meta"><span>' + escapeHtml(clipSourceLabel(clip)) + "</span>" +
          (categoryName(clip.category_id) ? "<span>·</span><span>" + escapeHtml(categoryName(clip.category_id)) + "</span>" : "") +
          (clip.created_at ? "<span>·</span><span>" + escapeHtml(formatDate(clip.created_at)) + "</span>" : "") +
          "</div>" +
          (source
            ? '<a class="remote-card-url" href="' + escapeHtml(source) + '" target="_blank" rel="noreferrer">' + escapeHtml(clip.url) + "</a>"
            : '<span class="remote-card-url">' + escapeHtml(clip.url || "PC内のファイル") + "</span>") +
          renderTags(clip.tags) +
          '<div class="remote-card-actions">' +
            '<button class="remote-primary-button remote-card-open" type="button" data-detail-id="' + Number(clip.id) + '">詳細を見る</button>' +
            '<button class="remote-quiet-button remote-star ' + (clip.is_favorite ? "active" : "") + '" type="button" data-favorite-id="' + Number(clip.id) + '" aria-label="' + (clip.is_favorite ? "お気に入りを解除" : "お気に入りに追加") + '">' + (clip.is_favorite ? "★" : "☆") + "</button>" +
          "</div>" +
        "</div>" +
      "</article>"
    );
  }

  function renderHome() {
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
    main.querySelectorAll("[data-detail-id]").forEach((button) => {
      button.addEventListener("click", () => renderDetail(Number(button.dataset.detailId)));
    });
    main.querySelectorAll("[data-favorite-id]").forEach((button) => {
      button.addEventListener("click", () => toggleFavorite(Number(button.dataset.favoriteId)));
    });
  }

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

  function renderDetail(id) {
    const clip = state.clips.find((item) => Number(item.id) === id);
    if (!clip) {
      renderHome();
      return;
    }
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
          '<button id="remoteDetailFavorite" class="remote-quiet-button remote-star ' + (clip.is_favorite ? "active" : "") + '" type="button">' + (clip.is_favorite ? "★ お気に入り" : "☆ お気に入り") + "</button></div>" +
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

    document.getElementById("remoteDetailBack").addEventListener("click", renderHome);
    document.getElementById("remoteDetailEdit").addEventListener("click", () => renderEditor(clip, null));
    document.getElementById("remoteDetailDelete").addEventListener("click", () => deleteClip(clip.id));
    document.getElementById("remoteDetailFavorite").addEventListener("click", async () => {
      await toggleFavorite(clip.id);
      renderDetail(clip.id);
    });
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

  function projectOptions(selected) {
    return '<option value="">プロジェクトなし</option>' + state.projects.map((project) =>
      '<option value="' + Number(project.id) + '"' + (Number(selected) === Number(project.id) ? " selected" : "") + ">" + escapeHtml(project.name) + "</option>"
    ).join("");
  }

  function categoryOptions(selected) {
    return '<option value="">カテゴリなし</option>' + state.categories.map((category) =>
      '<option value="' + Number(category.id) + '"' + (Number(selected) === Number(category.id) ? " selected" : "") + ">" + escapeHtml(category.name) + "</option>"
    ).join("");
  }

  function renderEditor(clip, uploadFile) {
    state.editingClip = clip;
    state.uploadFile = uploadFile;
    const isUpload = Boolean(uploadFile);
    const isEdit = Boolean(clip);
    const tags = Array.isArray(clip?.tags) ? clip.tags.map((tag) => tag.name || tag).join(", ") : "";
    main.innerHTML =
      '<div class="remote-panel">' +
        '<div class="remote-panel-heading"><div><p class="remote-page-kicker">' + (isEdit ? "CLIP EDITOR" : "NEW CLIP") + "</p><h1 class=\"remote-page-title\">" + (isEdit ? "クリップを編集" : "クリップを追加") + "</h1></div></div>" +
        '<form id="remoteClipForm" class="remote-form-grid">' +
          (isEdit || isUpload
            ? '<div class="remote-field full"><span>保存対象</span><div class="remote-inline-input">' + escapeHtml(isUpload ? uploadFile.name : (clip.url || "PC内のファイル")) + "</div></div>"
            : '<label class="remote-field full"><span>URL</span><input name="url" type="url" required placeholder="https://example.com/..." value="" /></label>') +
          '<label class="remote-field"><span>タイトル</span><input name="title" type="text" maxlength="500" autocomplete="off" value="' + escapeHtml(isUpload ? uploadFile.name : (clip?.title || "")) + '" /></label>' +
          '<label class="remote-field"><span>カテゴリ</span><select name="category">' + categoryOptions(clip?.category_id) + "</select></label>" +
          '<label class="remote-field"><span>プロジェクト</span><select name="project_id">' + projectOptions(clip?.project_id) + "</select></label>" +
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
    document.getElementById("remoteClipForm").addEventListener("submit", submitClipForm);
    const urlInput = main.querySelector("[name=url]");
    const titleInput = main.querySelector("[name=title]");
    urlInput?.addEventListener("blur", async () => {
      const url = String(urlInput.value || "").trim();
      if (!safeHref(url) || titleInput.value.trim()) return;
      try {
        const metadata = await api("/url-metadata?url=" + encodeURIComponent(url));
        if (metadata?.title && !titleInput.value.trim()) titleInput.value = metadata.title;
      } catch {
        // Metadata lookup is a convenience; saving the URL must still work.
      }
    });
  }

  async function submitClipForm(event) {
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
      const projectValue = String(formData.get("project_id") || "");
      const projectId = projectValue ? Number(projectValue) : null;
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
          body: JSON.stringify({ title, comment, category: category || null, tags, project_id: projectId }),
        });
    } else {
      const url = String(formData.get("url") || "").trim();
      if (!safeHref(url)) throw new Error("http:// または https:// のURLを入力してください。");
      result = await api("/clips", {
          method: "POST",
          body: JSON.stringify({
            url,
            title: title || null,
            comment: comment || null,
            category: category || null,
            tags,
            clip_type: "url",
            project_id: projectId,
          }),
        });
      }
      if (state.uploadFile && result?.id && projectId) {
        result = await api("/clips/" + Number(result.id), {
          method: "PUT",
          body: JSON.stringify({ project_id: projectId }),
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
    main.innerHTML =
      renderPageHeader("WORKSPACE", "タスク・メモ", "Android版と同じPC上のタスクとメモをWebから確認します。") +
      '<section class="remote-panel">' +
        '<div class="remote-tab-row"><button class="remote-tab ' + (tasksActive ? "active" : "") + '" data-workspace-tab="tasks" type="button">タスク ' + state.tasks.length + '</button><button class="remote-tab ' + (!tasksActive ? "active" : "") + '" data-workspace-tab="notes" type="button">メモ ' + state.notes.length + "</button></div>" +
        (tasksActive ? renderTaskList() : renderNoteList()) +
      "</section>";
    main.querySelectorAll("[data-workspace-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        state.workspaceTab = button.dataset.workspaceTab;
        renderWorkspace();
      });
    });
    if (tasksActive) {
      document.getElementById("remoteNewTask")?.addEventListener("click", () => renderTaskEditor(null));
      main.querySelectorAll("[data-task-toggle]").forEach((button) => button.addEventListener("click", () => toggleTask(Number(button.dataset.taskToggle))));
      main.querySelectorAll("[data-task-edit]").forEach((button) => button.addEventListener("click", () => renderTaskEditor(Number(button.dataset.taskEdit))));
      main.querySelectorAll("[data-task-delete]").forEach((button) => button.addEventListener("click", () => deleteTask(Number(button.dataset.taskDelete))));
    } else {
      document.getElementById("remoteNewNote")?.addEventListener("click", () => renderNoteEditor(null));
      main.querySelectorAll("[data-note-edit]").forEach((button) => button.addEventListener("click", () => renderNoteEditor(Number(button.dataset.noteEdit))));
      main.querySelectorAll("[data-note-delete]").forEach((button) => button.addEventListener("click", () => deleteNote(Number(button.dataset.noteDelete))));
    }
  }

  function renderTaskList() {
    return '<div class="remote-panel-heading"><h2>タスク</h2><button id="remoteNewTask" class="remote-primary-button" type="button">＋ タスク追加</button></div>' +
      (state.tasks.length ? '<div class="remote-task-list">' + state.tasks.map((task) =>
        '<div class="remote-list-row"><button class="remote-check-button ' + (task.is_done ? "done" : "") + '" type="button" data-task-toggle="' + Number(task.id) + '" aria-label="' + (task.is_done ? "未完了に戻す" : "完了にする") + '">' + (task.is_done ? "✓" : "○") + "</button>" +
        '<div class="remote-list-main"><p class="remote-list-title ' + (task.is_done ? "done" : "") + '">' + escapeHtml(task.title) + "</p><p class=\"remote-list-subtitle\">" + (task.due_date ? "期限 " + escapeHtml(task.due_date) : "期限なし") + (task.project_id ? " · " + escapeHtml(projectName(task.project_id)) : "") + "</p></div>" +
        '<div class="remote-list-actions"><button type="button" data-task-edit="' + Number(task.id) + '" aria-label="タスクを編集">編集</button><button type="button" data-task-delete="' + Number(task.id) + '" aria-label="タスクを削除">削除</button></div></div>'
      ).join("") + "</div>" : '<div class="remote-empty">タスクはありません。</div>');
  }

  function renderNoteList() {
    return '<div class="remote-panel-heading"><h2>メモ</h2><button id="remoteNewNote" class="remote-primary-button" type="button">＋ メモ追加</button></div>' +
      (state.notes.length ? '<div class="remote-note-list">' + state.notes.map((note) =>
        '<div class="remote-list-row"><div class="remote-list-main"><p class="remote-list-title">' + escapeHtml(note.title) + "</p><p class=\"remote-list-subtitle\">" + escapeHtml((note.body || "").slice(0, 180) || "本文なし") + "</p></div>" +
        '<div class="remote-list-actions"><button type="button" data-note-edit="' + Number(note.id) + '" aria-label="メモを編集">編集</button><button type="button" data-note-delete="' + Number(note.id) + '" aria-label="メモを削除">削除</button></div></div>'
      ).join("") + "</div>" : '<div class="remote-empty">メモはありません。</div>');
  }

  function renderTaskEditor(id) {
    const task = id ? state.tasks.find((item) => Number(item.id) === Number(id)) : null;
    state.editingTask = task;
    main.innerHTML =
      '<div class="remote-panel"><div class="remote-panel-heading"><div><p class="remote-page-kicker">TASK</p><h1 class="remote-page-title">' + (task ? "タスクを編集" : "タスクを追加") + '</h1></div></div>' +
      '<form id="remoteTaskForm" class="remote-form-grid">' +
      '<label class="remote-field full"><span>タイトル</span><input name="title" required maxlength="500" value="' + escapeHtml(task?.title || "") + '" /></label>' +
      '<label class="remote-field"><span>期限</span><input name="due_date" type="date" value="' + escapeHtml(task?.due_date || "") + '" /></label>' +
      '<label class="remote-field"><span>優先度</span><select name="priority"><option value="">標準</option><option value="1">高</option><option value="2">中</option><option value="3">低</option></select></label>' +
      '<label class="remote-field full"><span>プロジェクト</span><select name="project_id">' + projectOptions(task?.project_id) + "</select></label>" +
      '<div class="remote-form-actions full"><button id="remoteTaskCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">保存する</button></div><p id="remoteTaskError" class="remote-form-error full" role="alert"></p></form></div>';
    const priority = main.querySelector("[name=priority]");
    priority.value = task?.priority == null ? "" : String(task.priority);
    main.querySelector("[name=title]").focus();
    document.getElementById("remoteTaskCancel").addEventListener("click", () => {
      state.editingTask = null;
      renderWorkspace();
    });
    document.getElementById("remoteTaskForm").addEventListener("submit", submitTaskForm);
  }

  async function submitTaskForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const errorEl = document.getElementById("remoteTaskError");
    const data = new FormData(form);
    const projectId = String(data.get("project_id") || "");
    const payload = {
      title: String(data.get("title") || "").trim(),
      due_date: String(data.get("due_date") || "") || null,
      priority: String(data.get("priority") || "") ? Number(data.get("priority")) : null,
      project_id: projectId ? Number(projectId) : null,
    };
    try {
      if (!payload.title) throw new Error("タイトルを入力してください。");
      if (state.editingTask) {
        await api("/tasks/" + Number(state.editingTask.id), { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/tasks", { method: "POST", body: JSON.stringify(payload) });
      }
      await loadData(false);
      state.editingTask = null;
      renderWorkspace();
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

  function renderNoteEditor(id) {
    const note = id ? state.notes.find((item) => Number(item.id) === Number(id)) : null;
    state.editingNote = note;
    main.innerHTML =
      '<div class="remote-panel"><div class="remote-panel-heading"><div><p class="remote-page-kicker">NOTE</p><h1 class="remote-page-title">' + (note ? "メモを編集" : "メモを追加") + '</h1></div></div>' +
      '<form id="remoteNoteForm" class="remote-form-grid"><label class="remote-field full"><span>タイトル</span><input name="title" required maxlength="500" value="' + escapeHtml(note?.title || "") + '" /></label>' +
      '<label class="remote-field full"><span>本文</span><textarea name="body" rows="12" maxlength="100000">' + escapeHtml(note?.body || "") + '</textarea></label>' +
      '<div class="remote-form-actions full"><button id="remoteNoteCancel" class="remote-secondary-button" type="button">キャンセル</button><button class="remote-primary-button" type="submit">保存する</button></div><p id="remoteNoteError" class="remote-form-error full" role="alert"></p></form></div>';
    main.querySelector("[name=title]").focus();
    document.getElementById("remoteNoteCancel").addEventListener("click", () => {
      state.editingNote = null;
      renderWorkspace();
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
      state.editingNote = null;
      renderWorkspace();
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
    main.innerHTML =
      renderPageHeader("PROJECTS", "プロジェクト", "クリップ・タスク・メモをまとめるPC側のプロジェクトです.", '<button id="remoteNewProject" class="remote-primary-button" type="button">＋ プロジェクト追加</button>') +
      '<section class="remote-panel">' +
      (state.projects.length ? '<div class="remote-project-list">' + state.projects.map((project) =>
        '<div class="remote-list-row"><div class="remote-list-main"><p class="remote-list-title ' + (project.is_done ? "done" : "") + '">' + escapeHtml(project.name) + "</p><p class=\"remote-list-subtitle\">" + escapeHtml(project.description || "説明なし") + "</p></div><div class=\"remote-list-actions\"><button type=\"button\" data-project-toggle=\"" + Number(project.id) + '">' + (project.is_done ? "戻す" : "完了") + '</button><button type="button" data-project-edit="' + Number(project.id) + '">編集</button><button type="button" data-project-delete="' + Number(project.id) + '">削除</button></div></div>'
      ).join("") + "</div>" : '<div class="remote-empty">プロジェクトはありません。</div>') +
      "</section>";
    document.getElementById("remoteNewProject").addEventListener("click", () => renderProjectEditor(null));
    main.querySelectorAll("[data-project-toggle]").forEach((button) => button.addEventListener("click", () => toggleProject(Number(button.dataset.projectToggle))));
    main.querySelectorAll("[data-project-edit]").forEach((button) => button.addEventListener("click", () => renderProjectEditor(Number(button.dataset.projectEdit))));
    main.querySelectorAll("[data-project-delete]").forEach((button) => button.addEventListener("click", () => deleteProject(Number(button.dataset.projectDelete))));
  }

  function renderProjectEditor(id) {
    const project = id ? state.projects.find((item) => Number(item.id) === Number(id)) : null;
    state.editingProject = project;
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

  async function toggleProject(id) {
    try {
      await api("/projects/" + id + "/toggle", { method: "PATCH" });
      await loadData(false);
      renderProjects();
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
    main.innerHTML =
      renderPageHeader("APP SETTINGS", "アプリ設定", "PC側に保存される設定です。Web入口の認証設定はPCの設定画面から管理します。") +
      '<section class="remote-panel"><div id="remoteSettingsLoading" class="remote-loading">設定を読み込んでいます…</div><div id="remoteSettingsForm" hidden>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>タスク作成時に同名の空メモを作成</strong><small>タスクとメモを一緒に管理します。</small></span><input id="remoteSettingTaskNote" type="checkbox" /></label>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>プロジェクト作成時に同名の空メモを作成</strong><small>プロジェクトの概要メモを自動で用意します。</small></span><input id="remoteSettingProjectNote" type="checkbox" /></label>' +
      '<label class="remote-setting-row"><span class="remote-setting-copy"><strong>完了タスクの自動削除</strong><small>PC側のメンテナンス設定です。</small></span><select id="remoteSettingTaskDelete"><option value="3d">3日後</option><option value="1w">1週間後</option><option value="1m">1か月後</option><option value="never">自動削除しない</option></select></label>' +
      '</div></section>';
    try {
      const values = await Promise.all([
        readSetting("auto_create_note_on_task", "false"),
        readSetting("auto_create_note_on_project", "false"),
        readSetting("task_auto_delete", "1w"),
      ]);
      document.getElementById("remoteSettingTaskNote").checked = values[0] === "true";
      document.getElementById("remoteSettingProjectNote").checked = values[1] === "true";
      document.getElementById("remoteSettingTaskDelete").value = values[2];
      document.getElementById("remoteSettingsLoading").hidden = true;
      document.getElementById("remoteSettingsForm").hidden = false;
      document.getElementById("remoteSettingTaskNote").addEventListener("change", (event) => saveSetting("auto_create_note_on_task", event.target.checked));
      document.getElementById("remoteSettingProjectNote").addEventListener("change", (event) => saveSetting("auto_create_note_on_project", event.target.checked));
      document.getElementById("remoteSettingTaskDelete").addEventListener("change", (event) => saveSetting("task_auto_delete", event.target.value));
    } catch (error) {
      document.getElementById("remoteSettingsLoading").textContent = error.message;
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
      state.clips = values[0] || [];
      state.categories = values[1] || [];
      state.tags = values[2] || [];
      state.tasks = values[3] || [];
      state.notes = values[4] || [];
      state.projects = values[5] || [];
    } catch (error) {
      main.innerHTML = '<div class="remote-empty"><div><p>' + escapeHtml(error.message) + "</p><button id=\"remoteRetryData\" class=\"remote-primary-button\" type=\"button\">再読み込み</button></div></div>";
      document.getElementById("remoteRetryData")?.addEventListener("click", () => loadData(true));
    } finally {
      state.loading = false;
    }
  }

  function renderCurrentScreen() {
    document.querySelectorAll("[data-screen]").forEach((button) => {
      button.classList.toggle("active", button.dataset.screen === state.screen);
    });
    if (state.screen === "home") renderHome();
    else if (state.screen === "workspace") renderWorkspace();
    else if (state.screen === "projects") renderProjects();
    else if (state.screen === "settings") renderSettings();
    main.focus({ preventScroll: true });
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
      closeDrawer();
      renderCurrentScreen();
    });
  });
  menuButton.addEventListener("click", openDrawer);
  drawerClose.addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);
  document.getElementById("remoteRefreshButton").addEventListener("click", async () => {
    await loadData(true);
    renderCurrentScreen();
    showToast("最新のデータを読み込みました。");
  });
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

  loadData(true).then(renderCurrentScreen);
  window.setInterval(async () => {
    if (state.screen === "home" && !state.editingClip && !state.uploadFile) {
      await loadData(false);
      renderHome();
    }
  }, 10000);
})();
