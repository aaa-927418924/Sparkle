(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const serverStatus = $("remoteClientServerStatus");
  const clientStatus = $("remoteDataStatus");
  if (!serverStatus && !clientStatus) return;

  const serverButtons = {
    enable: $("remoteClientEnable"),
    retry: $("remoteClientRetry"),
    rotate: $("remoteClientRotate"),
    revoke: $("remoteClientRevokeAll"),
    disable: $("remoteClientDisable"),
  };
  const keyPanel = $("remoteClientKeyPanel");
  const keyInput = $("remoteClientAccessKey");
  const route = $("remoteClientServerUrl");
  const routeLink = $("remoteClientServerUrlLink");
  const dataEnabled = $("remoteDataEnabled");
  const dataConfig = $("remoteDataConfig");
  const dataUrl = $("remoteDataServerUrl");
  const dataKey = $("remoteDataAccessKey");
  const dataConnect = $("remoteDataConnect");
  const dataTest = $("remoteDataTest");
  const dataDisconnect = $("remoteDataDisconnect");
  let busy = false;

  function setMessage(element, message, tone = "") {
    if (!element) return;
    element.textContent = message;
    if (tone) element.dataset.tone = tone;
    else delete element.dataset.tone;
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
    });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  }

  function renderServerStatus(data) {
    const auth = data?.client_auth || {};
    const clientRoute = data?.client_route || {};
    const enabled = Boolean(auth.enabled);
    const active = Boolean(clientRoute.active);
    if (!serverStatus) return;
    if (!enabled) {
      setMessage(serverStatus, "無効（クライアントはこのPCのデータへ接続できません）");
    } else if (active) {
      setMessage(serverStatus, `有効（接続中のクライアント ${auth.session_count || 0}台）`, "success");
    } else {
      setMessage(serverStatus, "有効ですが、接続入口が停止しています。再試行してください。", "warning");
    }
    if (route && routeLink) {
      const publicUrl = String(clientRoute.public_url || "");
      route.hidden = !publicUrl;
      routeLink.textContent = publicUrl;
      if (publicUrl) routeLink.href = publicUrl;
      else routeLink.removeAttribute("href");
    }
    if (serverButtons.enable) serverButtons.enable.hidden = enabled;
    if (serverButtons.retry) serverButtons.retry.hidden = !enabled || active;
    if (serverButtons.rotate) serverButtons.rotate.hidden = !enabled;
    if (serverButtons.revoke) serverButtons.revoke.hidden = !enabled;
    if (serverButtons.disable) serverButtons.disable.hidden = !enabled;
  }

  function showKey(value) {
    if (!keyPanel || !keyInput || !value) return;
    keyInput.value = value;
    keyPanel.hidden = false;
  }

  async function refreshServer() {
    try {
      const data = await request("/settings/remote-access");
      renderServerStatus(data);
    } catch (error) {
      setMessage(serverStatus, `状態を取得できません：${error.message}`, "warning");
    }
  }

  async function runServerOperation(button, path, confirmation, showReturnedKey = false) {
    if (busy || !button) return;
    if (confirmation && !window.confirm(confirmation)) return;
    busy = true;
    button.disabled = true;
    setMessage(serverStatus, "処理しています…", "warning");
    try {
      const data = await request(path, { method: "POST", body: "{}" });
      if (showReturnedKey) showKey(data.access_key);
      renderServerStatus(data.status || data);
      if (data.error) setMessage(serverStatus, data.error, "warning");
    } catch (error) {
      setMessage(serverStatus, error.message || "処理に失敗しました。", "warning");
    } finally {
      button.disabled = false;
      busy = false;
      await refreshServer();
    }
  }

  async function refreshDataConnection() {
    try {
      const data = await request("/settings/remote-client");
      const enabled = Boolean(data?.enabled);
      if (dataEnabled) dataEnabled.checked = enabled;
      if (dataUrl && data.server_url) dataUrl.value = data.server_url;
      if (dataConfig) dataConfig.hidden = !enabled && !dataEnabled?.checked;
      if (dataConnect) dataConnect.hidden = enabled;
      if (dataTest) dataTest.hidden = !enabled;
      if (dataDisconnect) dataDisconnect.hidden = !enabled;
      setMessage(
        clientStatus,
        enabled
          ? `サーバーDBを使用中：${data.server_label || data.server_url}`
          : "ローカルDBを使用中",
        enabled ? "success" : "",
      );
    } catch (error) {
      setMessage(clientStatus, `接続設定を取得できません：${error.message}`, "warning");
    }
  }

  async function connectData() {
    if (busy || !dataConnect) return;
    const serverUrl = dataUrl?.value.trim() || "";
    const accessKey = dataKey?.value.trim() || "";
    if (!serverUrl || !accessKey) {
      setMessage(clientStatus, "サーバーURLとアクセスキーを入力してください。", "warning");
      return;
    }
    busy = true;
    dataConnect.disabled = true;
    setMessage(clientStatus, "サーバーへ接続しています…", "warning");
    try {
      await request("/settings/remote-client/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server_url: serverUrl, access_key: accessKey }),
      });
      if (dataKey) dataKey.value = "";
      setMessage(clientStatus, "接続しました。画面を再読み込みします…", "success");
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      setMessage(clientStatus, error.message || "接続できませんでした。", "warning");
      if (dataEnabled) dataEnabled.checked = false;
    } finally {
      dataConnect.disabled = false;
      busy = false;
    }
  }

  async function testData() {
    if (busy || !dataTest) return;
    busy = true;
    dataTest.disabled = true;
    setMessage(clientStatus, "接続を確認しています…", "warning");
    try {
      const data = await request("/settings/remote-client/test", { method: "POST", body: "{}" });
      setMessage(clientStatus, `接続中：${data?.status?.server || "Sparkle"}`, "success");
    } catch (error) {
      setMessage(clientStatus, error.message || "接続を確認できません。", "warning");
    } finally {
      dataTest.disabled = false;
      busy = false;
    }
  }

  async function disconnectData() {
    if (busy || !dataDisconnect) return;
    if (!window.confirm("ローカルDBへ戻します。サーバー側のデータは削除されません。続行しますか？")) {
      if (dataEnabled) dataEnabled.checked = true;
      if (dataConfig) dataConfig.hidden = false;
      return;
    }
    busy = true;
    dataDisconnect.disabled = true;
    setMessage(clientStatus, "ローカルDBへ切り替えています…", "warning");
    try {
      await request("/settings/remote-client/disconnect", { method: "POST", body: "{}" });
      window.location.reload();
    } catch (error) {
      setMessage(clientStatus, error.message || "切り替えに失敗しました。", "warning");
      if (dataEnabled) dataEnabled.checked = true;
      if (dataConfig) dataConfig.hidden = false;
      dataDisconnect.disabled = false;
      busy = false;
    }
  }

  serverButtons.enable?.addEventListener("click", () => runServerOperation(
    serverButtons.enable,
    "/settings/remote-access/client/enable",
    "このPCのデータをデスクトップクライアントへ公開します。続行しますか？",
    true,
  ));
  serverButtons.retry?.addEventListener("click", () => runServerOperation(serverButtons.retry, "/settings/remote-access/client/retry"));
  serverButtons.rotate?.addEventListener("click", () => runServerOperation(
    serverButtons.rotate,
    "/settings/remote-access/client/rotate",
    "既存のデスクトップクライアント接続をすべて無効にして、キーを再発行します。続行しますか？",
    true,
  ));
  serverButtons.revoke?.addEventListener("click", () => runServerOperation(
    serverButtons.revoke,
    "/settings/remote-access/client/revoke-all",
    "既存のデスクトップクライアント接続をすべて解除します。続行しますか？",
  ));
  serverButtons.disable?.addEventListener("click", () => runServerOperation(
    serverButtons.disable,
    "/settings/remote-access/client/disable",
    "デスクトップクライアントからの接続を停止します。続行しますか？",
  ));

  $("remoteClientCopyKey")?.addEventListener("click", async () => {
    if (!keyInput?.value) return;
    if (typeof window.sparkleCopyText === "function") await window.sparkleCopyText(keyInput.value);
    else await navigator.clipboard?.writeText(keyInput.value);
  });
  dataEnabled?.addEventListener("change", () => {
    if (dataConfig) dataConfig.hidden = !dataEnabled.checked;
    if (!dataEnabled.checked && dataDisconnect && !dataDisconnect.hidden) void disconnectData();
  });
  dataConnect?.addEventListener("click", connectData);
  dataTest?.addEventListener("click", testData);
  dataDisconnect?.addEventListener("click", disconnectData);

  void refreshServer();
  void refreshDataConnection();
})();
