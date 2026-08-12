// Sparkle - options page

const MAX_TEMPLATES = 4;
const DEFAULT_TEMPLATE_OPTIONS = {
  includeComment: false,
  autoSave: false,
};

const els = {
  shortcutsLink: document.getElementById("shortcutsLink"),
  currentShortcut: document.getElementById("currentShortcut"),
  templateIncludeComment: document.getElementById("templateIncludeComment"),
  templateAutoSave: document.getElementById("templateAutoSave"),
  templateCount: document.getElementById("templateCount"),
  templateList: document.getElementById("templateList"),
  templateStatus: document.getElementById("templateStatus"),
};

let templates = [];
let templateOptions = { ...DEFAULT_TEMPLATE_OPTIONS };

function normalizeTagKey(value) {
  return String(value || "")
    .trim()
    .normalize("NFKC")
    .toLocaleLowerCase();
}

function cleanTags(values) {
  const seen = new Set();
  const result = [];
  for (const value of Array.isArray(values) ? values : []) {
    const tag = String(value || "").trim();
    const key = normalizeTagKey(tag);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(tag);
  }
  return result;
}

function normalizeTemplate(value) {
  if (!value || typeof value !== "object") return null;
  const title = String(value.title || "").trim().slice(0, 40);
  const category = String(value.category || "").trim();
  const tags = cleanTags(value.tags);
  const comment = String(value.comment || "").trim();
  if (!title || (!category && !tags.length)) return null;
  return {
    id: String(value.id || ""),
    title,
    category,
    tags,
    comment,
  };
}

function setStatus(message, kind = "ok") {
  els.templateStatus.textContent = message || "";
  els.templateStatus.hidden = !message;
  els.templateStatus.style.color = kind === "err" ? "#fca5a5" : "#6ee7a8";
}

function renderTemplates() {
  els.templateList.replaceChildren();
  els.templateCount.textContent = `テンプレート：${templates.length} / ${MAX_TEMPLATES}`;

  if (!templates.length) {
    const empty = document.createElement("div");
    empty.className = "template-empty";
    empty.textContent = "保存したテンプレートはありません。";
    els.templateList.appendChild(empty);
    return;
  }

  templates.forEach((template, index) => {
    const item = document.createElement("div");
    item.className = "template-item";

    const main = document.createElement("div");
    main.className = "template-item-main";

    const title = document.createElement("div");
    title.className = "template-item-title";
    title.textContent = `${index + 1}. ${template.title}`;
    main.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "template-item-meta";
    const parts = [];
    if (template.category) parts.push(`カテゴリ：${template.category}`);
    if (template.tags.length) parts.push(`タグ：${template.tags.join(", ")}`);
    if (template.comment) parts.push("コメントあり");
    meta.textContent = parts.join("　");
    main.appendChild(meta);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "template-delete";
    remove.textContent = "削除";
    remove.setAttribute("aria-label", `テンプレート「${template.title}」を削除`);
    remove.addEventListener("click", () => deleteTemplate(template));

    item.append(main, remove);
    els.templateList.appendChild(item);
  });
}

async function loadTemplateState() {
  try {
    const data = await chrome.storage.local.get(["clipTemplates", "templateOptions"]);
    templates = Array.isArray(data.clipTemplates)
      ? data.clipTemplates
          .map(normalizeTemplate)
          .filter(Boolean)
          .slice(0, MAX_TEMPLATES)
      : [];

    const savedOptions = data.templateOptions;
    templateOptions = {
      ...DEFAULT_TEMPLATE_OPTIONS,
      ...(savedOptions && typeof savedOptions === "object" ? savedOptions : {}),
      includeComment: !!(savedOptions && savedOptions.includeComment),
      autoSave: !!(savedOptions && savedOptions.autoSave),
    };
    els.templateIncludeComment.checked = templateOptions.includeComment;
    els.templateAutoSave.checked = templateOptions.autoSave;
  } catch (e) {
    templates = [];
    templateOptions = { ...DEFAULT_TEMPLATE_OPTIONS };
  }
  els.templateIncludeComment.disabled = false;
  els.templateAutoSave.disabled = false;
  renderTemplates();
}

async function saveTemplateOptions() {
  templateOptions = {
    includeComment: els.templateIncludeComment.checked,
    autoSave: els.templateAutoSave.checked,
  };
  try {
    await chrome.storage.local.set({ templateOptions });
    setStatus("設定を保存しました");
  } catch (e) {
    setStatus("設定を保存できませんでした。", "err");
  }
}

async function deleteTemplate(template) {
  if (!confirm(`テンプレート「${template.title}」を削除しますか？`)) return;

  const nextTemplates = templates.filter((item) => item.id !== template.id);
  try {
    await chrome.storage.local.set({ clipTemplates: nextTemplates });
    templates = nextTemplates;
    renderTemplates();
    setStatus(`テンプレート「${template.title}」を削除しました`);
  } catch (e) {
    setStatus("テンプレートを削除できませんでした。", "err");
  }
}

els.shortcutsLink.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
});

els.templateIncludeComment.addEventListener("change", saveTemplateOptions);
els.templateAutoSave.addEventListener("change", saveTemplateOptions);

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;

  if (changes.clipTemplates) {
    templates = Array.isArray(changes.clipTemplates.newValue)
      ? changes.clipTemplates.newValue
          .map(normalizeTemplate)
          .filter(Boolean)
          .slice(0, MAX_TEMPLATES)
      : [];
    renderTemplates();
  }
  if (changes.templateOptions) {
    const next = changes.templateOptions.newValue;
    templateOptions = {
      ...DEFAULT_TEMPLATE_OPTIONS,
      ...(next && typeof next === "object" ? next : {}),
      includeComment: !!(next && next.includeComment),
      autoSave: !!(next && next.autoSave),
    };
    els.templateIncludeComment.checked = templateOptions.includeComment;
    els.templateAutoSave.checked = templateOptions.autoSave;
  }
});

// 現在のショートカット設定を表示
chrome.commands.getAll((commands) => {
  const cmd = commands.find((c) => c.name === "take-screenshot");
  if (cmd && cmd.shortcut) {
    els.currentShortcut.textContent = cmd.shortcut;
  }
});

loadTemplateState();
