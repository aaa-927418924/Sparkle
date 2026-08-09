(() => {
  const params = new URLSearchParams(window.location.search);
  const source = params.get("source") || "setup";
  const debugMode = params.get("debug") === "tutorial";
  const steps = [...document.querySelectorAll("[data-tutorial-step]")];
  const progressItems = [...document.querySelectorAll("[data-progress-step]")];
  const debugNote = document.getElementById("tutorialDebugNote");
  const status = document.getElementById("tutorialStatus");
  const backButton = document.getElementById("tutorialBack");
  const skipButton = document.getElementById("tutorialSkip");
  const nextButton = document.getElementById("tutorialNext");
  let currentStep = 0;
  let busy = false;

  if (!steps.length || !backButton || !skipButton || !nextButton) return;
  if (debugMode && debugNote) debugNote.hidden = false;
  if (source === "settings") skipButton.textContent = "設定に戻る";

  function setBusy(nextBusy) {
    busy = nextBusy;
    backButton.disabled = nextBusy;
    skipButton.disabled = nextBusy;
    nextButton.disabled = nextBusy;
  }

  function focusCurrentHeading() {
    const heading = steps[currentStep]?.querySelector("h2");
    if (heading) heading.focus({ preventScroll: true });
  }

  function renderStep({ focus = false } = {}) {
    steps.forEach((step, index) => {
      const active = index === currentStep;
      step.hidden = !active;
      step.setAttribute("aria-hidden", active ? "false" : "true");
    });
    progressItems.forEach((item, index) => {
      const active = index === currentStep;
      const complete = index < currentStep;
      item.classList.toggle("is-active", active);
      item.classList.toggle("is-complete", complete);
      if (active) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    backButton.disabled = busy || currentStep === 0;
    nextButton.textContent = currentStep === steps.length - 1
      ? (source === "settings" ? "設定に戻る" : "Sparkleを始める")
      : "次へ";
    if (status && !busy) status.textContent = `${currentStep + 1} / ${steps.length} の手順`;
    if (focus) requestAnimationFrame(focusCurrentHeading);
  }

  function nextPage() {
    if (source === "settings") return "/Settings";
    return "/Home";
  }

  async function completeTutorial() {
    if (busy) return;
    setBusy(true);
    if (status) status.textContent = "セットアップガイドを保存しています…";
    try {
      if (!debugMode) {
        const response = await fetch("/setup/tutorial/complete", {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.ok) {
          throw new Error(result.detail || "セットアップガイドの保存に失敗しました。");
        }
      }
      window.location.replace(nextPage());
    } catch (error) {
      setBusy(false);
      if (status) status.textContent = error.message || "保存できませんでした。接続を確認して、もう一度お試しください。";
    }
  }

  function goBack() {
    if (busy || currentStep === 0) return;
    currentStep -= 1;
    renderStep({ focus: true });
  }

  function goNext() {
    if (busy) return;
    if (currentStep === steps.length - 1) {
      void completeTutorial();
      return;
    }
    currentStep += 1;
    renderStep({ focus: true });
  }

  backButton.addEventListener("click", goBack);
  nextButton.addEventListener("click", goNext);
  skipButton.addEventListener("click", () => void completeTutorial());
  document.addEventListener("keydown", (event) => {
    if (busy) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      goBack();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      goNext();
    }
  });

  steps.forEach((step) => {
    const heading = step.querySelector("h2");
    if (heading) heading.tabIndex = -1;
  });
  renderStep();
  requestAnimationFrame(focusCurrentHeading);
})();
