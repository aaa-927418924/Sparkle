(() => {
  const params = new URLSearchParams(window.location.search);
  const debugMode = params.get("debug") === "extension";
  const debugNote = document.getElementById("extensionGuideDebugNote");
  const status = document.getElementById("extensionGuideStatus");
  const skipButton = document.getElementById("extensionGuideSkip");
  const doneButton = document.getElementById("extensionGuideDone");

  function finish() {
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
