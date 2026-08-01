(() => {
  const itemsEl = document.getElementById("migrationItems");
  const summaryEl = document.getElementById("migrationSummary");
  const statusEl = document.getElementById("migrationStatus");
  const runButton = document.getElementById("migrationRun");
  const exitButton = document.getElementById("migrationExit");

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
  }

  function renderStatus(data) {
    if (!data.required) {
      window.location.replace("/Home");
      return;
    }
    const items = data.items || [];
    itemsEl.replaceChildren();
    let totalFiles = 0;
    let totalBytes = 0;
    items.forEach((item) => {
      totalFiles += Number(item.files || 0);
      totalBytes += Number(item.bytes || 0);
      const row = document.createElement("li");
      row.className = "migration-item";
      const label = document.createElement("strong");
      label.textContent = item.label || "移行対象";
      const source = document.createElement("span");
      source.textContent = item.source || "";
      row.append(label, source);
      itemsEl.appendChild(row);
    });
    summaryEl.textContent = `${items.length}項目 / ${totalFiles}ファイル${formatBytes(totalBytes) ? ` / ${formatBytes(totalBytes)}` : ""}`;
    if (data.conflict) {
      runButton.disabled = true;
      statusEl.textContent = "Sparkle側に既存データがあるため、自動移行を安全に実行できません。旧データを確認してから再度起動してください。";
    }
  }

  async function loadStatus() {
    try {
      const response = await fetch("/migration/status", { cache: "no-store" });
      if (!response.ok) throw new Error("移行情報を取得できませんでした");
      renderStatus(await response.json());
    } catch (error) {
      runButton.disabled = true;
      statusEl.textContent = error.message || "移行情報を取得できませんでした。";
    }
  }

  async function runMigration() {
    runButton.disabled = true;
    exitButton.disabled = true;
    statusEl.textContent = "データを検証して移行しています。しばらくお待ちください…";
    try {
      const response = await fetch("/migration/run", { method: "POST" });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        throw new Error(result.error || "移行に失敗しました。");
      }
      statusEl.textContent = result.warnings?.length
        ? `移行は完了しました。一部の項目は後で確認してください。`
        : "移行が完了しました。Sparkleを起動しています…";
      window.location.replace("/Home");
    } catch (error) {
      exitButton.disabled = false;
      runButton.disabled = false;
      statusEl.textContent = error.message || "移行に失敗しました。データは削除されていません。もう一度お試しください。";
    }
  }

  runButton.addEventListener("click", runMigration);
  exitButton.addEventListener("click", () => {
    const api = window.pywebview?.api;
    if (api && typeof api.exit_application === "function") void api.exit_application();
  });
  loadStatus();
})();
