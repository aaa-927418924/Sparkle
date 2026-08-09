(() => {
  const params = new URLSearchParams(window.location.search);
  const debugMode = params.get("debug") === "extension";
  const migrationMode = params.get("source") === "migration";
  const setupMode = params.get("source") === "setup";
  const eyebrow = document.querySelector(".migration-eyebrow");
  const title = document.getElementById("extensionGuideTitle");
  const description = document.getElementById("extensionGuideDescription");
  const debugNote = document.getElementById("extensionGuideDebugNote");
  const status = document.getElementById("extensionGuideStatus");
  const skipButton = document.getElementById("extensionGuideSkip");
  const doneButton = document.getElementById("extensionGuideDone");

  if (migrationMode) {
    document.title = "Sparkle — Chrome拡張の更新";
    if (eyebrow) eyebrow.textContent = "移行後の仕上げ";
    if (title) title.textContent = "Chrome拡張も更新しましょう";
    if (description) {
      description.textContent = "Sparkleへの移行が完了しました。Chrome拡張も新しいSparkleに合わせて更新して、これまでどおりページを保存できるようにしましょう。あとから設定することもできます。";
    }
    doneButton.textContent = "Sparkleを始める";
  }
  if (setupMode || debugMode) doneButton.textContent = "次へ";

  let busy = false;
  async function finish() {
    if (busy) return;
    busy = true;
    skipButton.disabled = true;
    doneButton.disabled = true;
    if (migrationMode) {
      try {
        await fetch("/setup/post-migration/complete", { method: "POST" });
      } catch {
        // Continue to the home page; the pending marker will show this guide
        // again on the next launch if the completion request did not finish.
      }
      window.location.replace("/Home");
      return;
    }
    if (setupMode && !debugMode) {
      status.textContent = "続きの案内を準備しています…";
      try {
        const response = await fetch("/setup/tutorial/start", {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.ok) {
          throw new Error(result.detail || "セットアップガイドを準備できませんでした。");
        }
      } catch (error) {
        busy = false;
        skipButton.disabled = false;
        doneButton.disabled = false;
        status.textContent = error.message || "続きの案内を開けませんでした。もう一度お試しください。";
        return;
      }
      window.location.replace("/Tutorial?source=setup");
      return;
    }
    if (debugMode) {
      window.location.replace("/Tutorial?source=setup&debug=tutorial");
      return;
    }
    window.location.replace("/Home");
  }

  if (debugMode) {
    debugNote.hidden = false;
    status.textContent = "デバッグ用にChrome拡張の案内を表示しています。";
  }

  skipButton.addEventListener("click", finish);
  doneButton.addEventListener("click", finish);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    finish();
  });

  requestAnimationFrame(() => doneButton.focus({ preventScroll: true }));
})();
