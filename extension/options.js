// Sparkle - options page

document.getElementById("shortcutsLink").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
});

// 現在のショートカット設定を表示
chrome.commands.getAll((commands) => {
  const cmd = commands.find((c) => c.name === "take-screenshot");
  if (cmd && cmd.shortcut) {
    document.getElementById("currentShortcut").textContent = cmd.shortcut;
  }
});
