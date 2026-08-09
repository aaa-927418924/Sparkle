(() => {
  const statusEl = document.getElementById("remoteAccessStatus");
  if (!statusEl) return;

  const buttons = {
    enable: document.getElementById("remoteAccessEnable"),
    retry: document.getElementById("remoteAccessRetry"),
    rotate: document.getElementById("remoteAccessRotate"),
    revoke: document.getElementById("remoteAccessRevokeAll"),
    disable: document.getElementById("remoteAccessDisable"),
  };
  const keyPanel = document.getElementById("remoteAccessKeyPanel");
  const keyInput = document.getElementById("remoteAccessKey");
  const urlWrap = document.getElementById("remoteAccessUrl");
  const urlLink = document.getElementById("remoteAccessUrlLink");
  let busy = false;

  async function request(path, options = {}) {
    const response = await fetch(window.location.origin + path, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) {
      throw new Error(data.detail || ("HTTP " + response.status));
    }
    return data;
  }

  function setStatus(message, tone = "") {
    statusEl.textContent = message;
    statusEl.dataset.tone = tone;
  }

  function showKey(key) {
    if (!key || !keyInput || !keyPanel) return;
    keyInput.value = key;
    keyPanel.hidden = false;
    keyInput.focus();
    keyInput.select();
  }

  function render(data) {
    const auth = data?.auth || {};
    const funnel = data?.funnel || {};
    const enabled = Boolean(auth.enabled);
    const active = Boolean(funnel.active && funnel.target === "remote");
    const statusError = data?.last_error || funnel.error;

    buttons.enable.hidden = enabled;
    buttons.retry.hidden = !enabled || active;
    buttons.rotate.hidden = !enabled;
    buttons.revoke.hidden = !enabled;
    buttons.disable.hidden = !enabled;

    if (!enabled) {
      setStatus("通常モード：Tailscale経由の接続を使用しています。");
      urlWrap.hidden = true;
      if (keyPanel) keyPanel.hidden = true;
      if (keyInput) keyInput.value = "";
      return;
    }

    if (active) {
      const count = Number(auth.session_count || 0);
      setStatus("Funnel Webは有効です。信頼端末 " + count + " 台", "success");
    } else if (statusError) {
      setStatus("設定は保存されていますが、Funnelに接続できません：" + statusError, "warning");
    } else if (!funnel.available) {
      setStatus("設定は保存されています。Tailscaleの状態を確認できるまで待っています。", "warning");
    } else {
      setStatus("Funnel Webを起動しています…", "warning");
    }

    const publicUrl = typeof funnel.public_url === "string" ? funnel.public_url : "";
    if (publicUrl) {
      urlWrap.hidden = false;
      urlLink.href = publicUrl;
      urlLink.textContent = publicUrl;
    } else {
      urlWrap.hidden = true;
      urlLink.removeAttribute("href");
      urlLink.textContent = "";
    }
  }

  async function refresh() {
    try {
      render(await request("/settings/remote-access"));
    } catch (error) {
      setStatus("状態を取得できません：" + error.message, "warning");
    }
  }

  async function runOperation(button, path, confirmation, showReturnedKey = false) {
    if (busy) return;
    if (confirmation && !window.confirm(confirmation)) return;
    busy = true;
    button.disabled = true;
    setStatus("処理しています…", "warning");
    try {
      const data = await request(path, { method: "POST", body: "{}" });
      if (showReturnedKey && data.access_key) showKey(data.access_key);
      render(data.status || data);
      if (data.error) setStatus(data.error, "warning");
    } catch (error) {
      setStatus("処理に失敗しました：" + error.message, "warning");
    } finally {
      button.disabled = false;
      busy = false;
      await refresh();
    }
  }

  buttons.enable.addEventListener("click", () => runOperation(
    buttons.enable,
    "/settings/remote-access/enable",
    "インターネット上からアクセスできるWeb入口を作成します。アクセスキーを知っている人だけに共有してください。続行しますか？",
    true,
  ));
  buttons.retry.addEventListener("click", () => runOperation(
    buttons.retry,
    "/settings/remote-access/retry",
    null,
  ));
  buttons.rotate.addEventListener("click", () => runOperation(
    buttons.rotate,
    "/settings/remote-access/rotate",
    "アクセスキーを再発行すると、既存の全ブラウザのログインが解除されます。続行しますか？",
    true,
  ));
  buttons.revoke.addEventListener("click", () => runOperation(
    buttons.revoke,
    "/settings/remote-access/revoke-all",
    "すべての信頼端末を解除します。続行しますか？",
  ));
  buttons.disable.addEventListener("click", () => runOperation(
    buttons.disable,
    "/settings/remote-access/disable",
    "Funnel Webを停止し、外部Webからのアクセスを無効にします。続行しますか？",
  ));

  document.getElementById("remoteAccessCopyKey")?.addEventListener("click", async () => {
    if (!keyInput?.value) return;
    try {
      await navigator.clipboard.writeText(keyInput.value);
    } catch {
      keyInput.focus();
      keyInput.select();
      document.execCommand("copy");
    }
    setStatus("アクセスキーをコピーしました。", "success");
  });

  refresh();
  window.setInterval(refresh, 5000);
})();
