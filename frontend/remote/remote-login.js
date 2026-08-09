(() => {
  const form = document.getElementById("remoteLoginForm");
  const keyInput = document.getElementById("remoteAccessKeyInput");
  const trustInput = document.getElementById("remoteTrustDevice");
  const labelInput = document.getElementById("remoteDeviceLabel");
  const errorEl = document.getElementById("remoteLoginError");
  const submit = form?.querySelector("button[type=submit]");
  if (!form || !keyInput || !trustInput || !labelInput || !errorEl || !submit) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    if (!keyInput.value.trim()) {
      errorEl.textContent = "アクセスキーを入力してください。";
      keyInput.focus();
      return;
    }

    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    submit.textContent = "確認しています…";
    try {
      const response = await fetch("/remote/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          access_key: keyInput.value.trim(),
          trust_device: trustInput.checked,
          device_label: labelInput.value.trim() || "ブラウザ",
        }),
      });
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) throw new Error(data.detail || "アクセスキーを確認できませんでした。");
      window.location.assign("/");
    } catch (error) {
      errorEl.textContent = error.message || "ログインできませんでした。";
      keyInput.focus();
      keyInput.select();
    } finally {
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
      submit.textContent = "Web版を開く";
    }
  });
})();
