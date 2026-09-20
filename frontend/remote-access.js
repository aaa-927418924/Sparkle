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
  const modeSelect = document.getElementById("remoteAccessMode");
  const modeApply = document.getElementById("remoteAccessModeApply");
  const modeHint = document.getElementById("remoteAccessModeHint");
  const keyPanel = document.getElementById("remoteAccessKeyPanel");
  const keyInput = document.getElementById("remoteAccessKey");
  const urlWrap = document.getElementById("remoteAccessUrl");
  const urlLink = document.getElementById("remoteAccessUrlLink");
  const mcpStatusEl = document.getElementById("remoteMcpStatus");
  let busy = false;

  const modeInfo = {
    funnel: {
      name: "Funnel Web",
      description: "Tailscaleなしの端末からアクセスできます。",
      confirmation: "インターネット上からアクセスできるFunnel Web入口を作成します。アクセスキーを知っている人だけに共有してください。続行しますか？",
    },
    serve: {
      name: "Serve Web（Android）",
      description: "AndroidなどTailscaleに接続した端末からだけアクセスできます。",
      confirmation: "Android向けのTailscale Serve入口をHTTPS 8443番ポートに作成します。続行しますか？",
    },
  };

  function getMode(data = {}) {
    const value = data.web_mode || data.auth?.remote_mode || modeSelect?.value;
    return modeInfo[value] ? value : "funnel";
  }

  function getWebRoute(data, mode) {
    return data.web_route || data.android || data[mode] || data.funnel || data.serve || {};
  }

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

  function setPanelStatus(element, message, tone = "") {
    if (!element) return;
    element.textContent = message;
    element.dataset.tone = tone;
  }

  function setStatus(message, tone = "") {
    setPanelStatus(statusEl, message, tone);
  }

  function setMcpStatus(message, tone = "") {
    setPanelStatus(mcpStatusEl, message, tone);
  }

  function showKey(key, input, panel) {
    if (!key || !input || !panel) return;
    input.value = key;
    panel.hidden = false;
    input.focus();
    input.select();
  }

  function renderMcp() {
    setMcpStatus("Remote MCPはこのアプリでは無効化されています。", "warning");
  }

  function render(data) {
    const auth = data?.auth || {};
    const mode = getMode(data);
    const info = modeInfo[mode];
    const route = getWebRoute(data, mode);
    const enabled = Boolean(auth.enabled);
    const expectedTarget = mode === "serve" ? "main" : "remote";
    const active = Boolean(route.active && route.target === expectedTarget);
    const statusError = data?.last_error || route.error;

    if (modeSelect && modeSelect.value !== mode) modeSelect.value = mode;
    if (modeHint) modeHint.textContent = info.description;
    buttons.enable.hidden = enabled;
    buttons.retry.hidden = !enabled || active;
    buttons.rotate.hidden = !enabled;
    buttons.revoke.hidden = !enabled;
    buttons.disable.hidden = !enabled;
    buttons.enable.textContent = info.name + "を有効にする";
    buttons.disable.textContent = info.name + "を無効にする";

    if (!enabled) {
      setStatus("通常モード：Tailscale経由の接続を使用しています。" + info.name + "を使う場合は方式を選んで有効にしてください。");
      urlWrap.hidden = true;
      if (keyPanel) keyPanel.hidden = true;
      if (keyInput) keyInput.value = "";
    } else {
      if (active) {
        const count = Number(auth.session_count || 0);
        const scope = mode === "serve"
          ? "Tailscale接続端末からアクセスできます。"
          : "アクセスキーを知っている端末からアクセスできます。";
        setStatus(info.name + "は有効です。" + scope + "信頼端末" + count + "台", "success");
      } else if (statusError) {
        setStatus("設定は保存されていますが、" + info.name + "に接続できません：" + statusError, "warning");
      } else if (!route.available) {
        setStatus("設定は保存されています。Tailscaleの状態を確認できるまで待っています。", "warning");
      } else {
        setStatus(info.name + "を起動しています…", "warning");
      }

      const publicUrl = typeof route.public_url === "string" ? route.public_url : "";
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

    renderMcp(data);
  }

  async function refresh() {
    try {
      render(await request("/settings/remote-access"));
    } catch (error) {
      setStatus("状態を取得できません：" + error.message, "warning");
      renderMcp();
    }
  }

  async function runOperation(button, path, confirmation, showReturnedKey = false, panel = {}) {
    if (busy || !button) return;
    if (confirmation && !window.confirm(confirmation)) return;
    busy = true;
    button.disabled = true;
    const operationStatus = panel.status || statusEl;
    setPanelStatus(operationStatus, "処理しています…", "warning");
    try {
      const data = await request(path, { method: "POST", body: "{}" });
      if (showReturnedKey) showKey(data.access_key, panel.keyInput || keyInput, panel.keyPanel || keyPanel);
      render(data.status || data);
      if (data.error) setPanelStatus(operationStatus, data.error, "warning");
    } catch (error) {
      setPanelStatus(operationStatus, "処理に失敗しました：" + error.message, "warning");
    } finally {
      button.disabled = false;
      busy = false;
      await refresh();
    }
  }

  async function applyMode() {
    if (busy || !modeSelect || !modeApply) return;
    const mode = getMode({ web_mode: modeSelect.value });
    const info = modeInfo[mode];
    if (!window.confirm(info.name + "に公開方式を変更します。現在有効なWeb入口がある場合は接続先を切り替えます。続行しますか？")) {
      await refresh();
      return;
    }
    busy = true;
    modeApply.disabled = true;
    setStatus("公開方式を切り替えています…", "warning");
    try {
      const data = await request("/settings/remote-access/mode", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      render(data.status || data);
      if (data.error) setStatus(data.error, "warning");
    } catch (error) {
      setStatus("公開方式の変更に失敗しました：" + error.message, "warning");
    } finally {
      modeApply.disabled = false;
      busy = false;
      await refresh();
    }
  }

  buttons.enable.addEventListener("click", () => {
    const mode = getMode({ web_mode: modeSelect?.value });
    runOperation(buttons.enable, "/settings/remote-access/enable", modeInfo[mode].confirmation, true);
  });
  buttons.retry.addEventListener("click", () => runOperation(buttons.retry, "/settings/remote-access/retry"));
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
  buttons.disable.addEventListener("click", () => {
    const mode = getMode({ web_mode: modeSelect?.value });
    runOperation(
      buttons.disable,
      "/settings/remote-access/disable",
      modeInfo[mode].name + "を停止し、外部Webからのアクセスを無効にします。続行しますか？",
    );
  });

  modeApply?.addEventListener("click", applyMode);

  document.getElementById("remoteAccessCopyKey")?.addEventListener("click", async () => {
    if (!keyInput?.value) return;
    try {
      await navigator.clipboard.writeText(keyInput.value);
    } catch {
      keyInput.focus();
      keyInput.select();
      document.execCommand("copy");
    }
    setStatus("Web公開用アクセスキーをコピーしました。", "success");
  });

  refresh();
  window.setInterval(refresh, 5000);
})();
