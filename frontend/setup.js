(() => {
  const params = new URLSearchParams(window.location.search);
  const debugMode = params.get("debug") === "setup";
  const migrationMode = params.get("source") === "migration";
  const eyebrow = document.querySelector(".migration-eyebrow");
  const title = document.getElementById("setupTitle");
  const description = document.getElementById("setupDescription");
  const fileSaveMethod = document.getElementById("setupFileSaveMethod");
  const fileSaveMethodDesc = document.getElementById("setupFileSaveMethodDesc");
  const taskAutoDelete = document.getElementById("setupTaskAutoDelete");
  const autoCreateNoteOnTask = document.getElementById("setupAutoCreateNoteOnTask");
  const autoCreateNoteOnProject = document.getElementById("setupAutoCreateNoteOnProject");
  const aiExportEnabled = document.getElementById("setupAiExportEnabled");
  const debugNote = document.getElementById("setupDebugNote");
  const status = document.getElementById("setupStatus");
  const completeButton = document.getElementById("setupComplete");
  const exitButton = document.getElementById("setupExit");

  const defaults = {
    file_save_method: "reference",
    task_auto_delete: "1w",
    auto_create_note_on_task: false,
    auto_create_note_on_project: false,
    ai_export_enabled: true,
  };

  if (migrationMode) {
    document.title = "Sparkle — 設定の確認";
    if (eyebrow) eyebrow.textContent = "移行後の確認";
    if (title) title.textContent = "設定を確認しましょう";
    if (description) {
      description.textContent = "データの移行が完了しました。Sparkleで使う保存方法や整理方法を確認し、必要なら変更してください。";
    }
  }

  function updateFileSaveDescription(value) {
    if (!fileSaveMethodDesc) return;
    fileSaveMethodDesc.textContent = value === "copy"
      ? "リンク切れの心配はありませんが、その分データ容量が増えます。"
      : "アップロードしたファイルの場所をそのまま参照します。";
  }

  function setFormValues(values = {}) {
    const next = { ...defaults, ...values };
    const savedTaskSetting = localStorage.getItem("autoCreateNoteOnTask");
    const savedProjectSetting = localStorage.getItem("autoCreateNoteOnProject");
    if (savedTaskSetting !== null) next.auto_create_note_on_task = savedTaskSetting === "true";
    if (savedProjectSetting !== null) next.auto_create_note_on_project = savedProjectSetting === "true";
    fileSaveMethod.value = next.file_save_method;
    taskAutoDelete.value = next.task_auto_delete;
    autoCreateNoteOnTask.checked = Boolean(next.auto_create_note_on_task);
    autoCreateNoteOnProject.checked = Boolean(next.auto_create_note_on_project);
    aiExportEnabled.checked = Boolean(next.ai_export_enabled);
    updateFileSaveDescription(fileSaveMethod.value);
  }

  function setBusy(busy) {
    completeButton.disabled = busy;
    exitButton.disabled = busy;
    fileSaveMethod.disabled = busy;
    taskAutoDelete.disabled = busy;
    autoCreateNoteOnTask.disabled = busy;
    autoCreateNoteOnProject.disabled = busy;
    aiExportEnabled.disabled = busy;
  }

  async function loadStatus() {
    try {
      const response = await fetch("/setup/status", { cache: "no-store" });
      if (!response.ok) throw new Error("初期設定の状態を取得できませんでした。");
      const data = await response.json();
      if (!data.required && !debugMode && !migrationMode) {
        window.location.replace("/Home");
        return;
      }
      setFormValues(data.values || data.defaults);
      if (debugMode) {
        debugNote.hidden = false;
        exitButton.textContent = "閉じる";
        status.textContent = "デバッグ用に初期設定画面を表示しています。";
      } else if (migrationMode) {
        status.textContent = "移行した設定を確認できます。必要ならここで変更してください。";
      }
    } catch (error) {
      completeButton.disabled = true;
      status.textContent = error.message || "初期設定の状態を取得できませんでした。";
    }
  }

  async function completeSetup() {
    setBusy(true);
    status.textContent = "設定を保存しています…";
    const payload = {
      flow: migrationMode ? "migration" : "initial",
      file_save_method: fileSaveMethod.value,
      task_auto_delete: taskAutoDelete.value,
      auto_create_note_on_task: autoCreateNoteOnTask.checked,
      auto_create_note_on_project: autoCreateNoteOnProject.checked,
      ai_export_enabled: aiExportEnabled.checked,
    };
    try {
      const response = await fetch("/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error(result.detail || result.error || "初期設定の保存に失敗しました。");
      }
      localStorage.setItem("autoCreateNoteOnTask", payload.auto_create_note_on_task ? "true" : "false");
      localStorage.setItem("autoCreateNoteOnProject", payload.auto_create_note_on_project ? "true" : "false");
      status.textContent = migrationMode
        ? "確認が完了しました。Chrome拡張の更新案内を表示します…"
        : "設定が完了しました。Chrome拡張の案内を表示します…";
      if (migrationMode) {
        window.location.replace("/ExtensionGuide?source=migration");
        return;
      }
      const extensionQuery = debugMode ? "?source=setup&debug=extension" : "?source=setup";
      window.location.replace(`/ExtensionGuide${extensionQuery}`);
    } catch (error) {
      setBusy(false);
      status.textContent = error.message || "初期設定に失敗しました。設定はまだ完了していません。";
    }
  }

  function exitSetup() {
    if (debugMode) {
      window.location.replace("/Home");
      return;
    }
    const api = window.pywebview?.api;
    if (api && typeof api.exit_application === "function") void api.exit_application();
  }

  fileSaveMethod.addEventListener("change", () => updateFileSaveDescription(fileSaveMethod.value));
  aiExportEnabled.addEventListener("change", async () => {
    if (aiExportEnabled.checked) return;
    aiExportEnabled.disabled = true;
    const message = "エクスポートした内容が全て削除されますが、続行しますか？\nデータ自体は保持されます。";
    const confirmed = typeof window.confirmDeletion === "function"
      ? await window.confirmDeletion(message, {
        anchor: aiExportEnabled,
        title: "AI向けエクスポートを無効にしますか？",
        confirmLabel: "無効にする",
      })
      : window.confirm(message);
    if (!confirmed) aiExportEnabled.checked = true;
    aiExportEnabled.disabled = false;
  });
  completeButton.addEventListener("click", completeSetup);
  exitButton.addEventListener("click", exitSetup);
  loadStatus();
})();
