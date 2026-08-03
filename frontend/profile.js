const $ = (id) => document.getElementById(id);

const els = {
  icon: $("profileIcon"),
  iconBtn: $("profileIconBtn"),
  iconFile: $("profileIconFile"),
  nameBtn: $("profileNameBtn"),
  nameInput: $("profileNameInput"),
  totalSaved: $("profileTotalSaved"),
  firstUsed: $("profileFirstUsed"),
  weekSaved: $("profileWeekSaved"),
  days: $("profileDays"),
  picks: $("profilePicks"),
  picksEmpty: $("profilePicksEmpty"),
  picksLimit: $("profilePicksLimit"),
  pickAdd: $("profilePickAdd"),
  pickModal: $("pickModal"),
  pickSearch: $("pickSearch"),
  pickList: $("pickList"),
  pickEmpty: $("pickEmpty"),
  pickClose: $("pickClose"),
  share: $("profileShare"),
  shareStatus: $("profileShareStatus"),
  shareModal: $("shareModal"),
  sharePreview: $("sharePreview"),
  shareClose: $("shareClose"),
};

let profile = null;
let allClips = [];
let pickSearchText = "";
let naming = false;
let shareBusy = false;

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

async function api(path, options = {}) {
  const res = await fetch(API_ROOT + path, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

function setShareStatus(msg, kind = "") {
  els.shareStatus.textContent = msg;
  els.shareStatus.className = "profile-share-status" + (kind ? " " + kind : "");
  clearTimeout(setShareStatus._timer);
  setShareStatus._timer = setTimeout(() => {
    els.shareStatus.textContent = "";
    els.shareStatus.className = "profile-share-status";
  }, 2000);
}

async function loadProfile() {
  profile = await api("/profile");
  renderProfile();
}

async function refreshProfile() {
  try {
    const data = await api("/profile");
    if (!profile) {
      profile = data;
      renderProfile();
      return;
    }
    const prevCount = profile.total_saved;
    const prevDays = profile.days_since_first;
    const prevWeek = profile.saved_last_7_days;
    const prevPicks = profile.picks.length;
    profile = data;
    if (
      profile.total_saved !== prevCount ||
      profile.days_since_first !== prevDays ||
      profile.saved_last_7_days !== prevWeek
    ) {
      els.totalSaved.textContent = String(profile.total_saved);
      els.firstUsed.textContent = `初回利用日: ${profile.first_used_at || "—"}`;
      els.days.textContent = `${profile.days_since_first}日`;
      els.weekSaved.textContent = String(profile.saved_last_7_days);
    }
    if (typeof window.initProfileSidebar === "function") window.initProfileSidebar();
    if (!naming && els.pickModal.hidden && !shareBusy && profile.picks.length !== prevPicks) {
      renderPicks();
    }
  } catch (e) {}
}

setInterval(() => {
  if (!document.hidden) refreshProfile();
}, 5000);

function renderProfile() {
  els.icon.src = profile.icon_url || "/icon.png";
  const name = profile.username || "ユーザー";
  els.nameBtn.textContent = name.length > 15 ? name.slice(0, 15) + "…" : name;
  els.totalSaved.textContent = String(profile.total_saved);
  els.firstUsed.textContent = `初回利用日: ${profile.first_used_at || "—"}`;
  els.days.textContent = `${profile.days_since_first}日`;
  els.weekSaved.textContent = String(profile.saved_last_7_days);
  renderPicks();
  if (typeof window.initProfileSidebar === "function") window.initProfileSidebar();
  document.body.classList.remove("profile-loading");
}

// ---- Icon ----

function resizeImageFile(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const max = 256;
        let { width, height } = img;
        if (width > max || height > max) {
          const scale = max / Math.max(width, height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/png"));
      };
      img.onerror = () => resolve(null);
      img.src = reader.result;
    };
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

els.iconBtn.addEventListener("click", () => els.iconFile.click());

els.iconFile.addEventListener("change", async () => {
  const file = els.iconFile.files?.[0];
  els.iconFile.value = "";
  if (!file) return;
  const dataUrl = await resizeImageFile(file);
  if (!dataUrl) {
    setShareStatus("画像を読み込めませんでした。別の画像を試してください。", "err");
    return;
  }
  try {
    profile = await api("/profile/icon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data_url: dataUrl }),
    });
    renderProfile();
    setShareStatus("アイコンを更新しました", "ok");
  } catch (e) {
    setShareStatus(`アイコンの保存に失敗しました。${e.message}`, "err");
  }
});

// ---- Username ----

function startNameEdit() {
  if (naming) return;
  naming = true;
  els.nameInput.value = profile.username || "";
  els.nameInput.hidden = false;
  els.nameBtn.hidden = true;
  els.nameInput.focus();
  els.nameInput.select();
}

async function commitName(save) {
  if (!naming) return;
  naming = false;
  const value = els.nameInput.value.trim().slice(0, 15);
  els.nameInput.hidden = true;
  els.nameBtn.hidden = false;
  if (!save || !value || value === (profile.username || "")) return;
  try {
    profile = await api("/profile/name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: value }),
    });
    renderProfile();
    setShareStatus("ユーザー名を更新しました", "ok");
  } catch (e) {
    setShareStatus(`ユーザー名の保存に失敗しました。${e.message}`, "err");
  }
}

els.nameBtn.addEventListener("click", startNameEdit);

els.nameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    commitName(true);
  } else if (e.key === "Escape") {
    e.preventDefault();
    commitName(false);
  }
});

els.nameInput.addEventListener("blur", () => commitName(true));

// ---- Recommended clips ----

function renderPicks() {
  const picks = profile.picks || [];
  els.picksLimit.textContent = `${picks.length} / 3`;
  els.picksEmpty.hidden = picks.length > 0;
  if (!picks.length) {
    els.picks.innerHTML = "";
    return;
  }
  els.picks.innerHTML = picks.map((clip) => {
    const thumb = clip.thumbnail_url
      ? `<img class="profile-pick-thumb" src="${String(clip.thumbnail_url).replace(/"/g, "&quot;")}" alt="" />`
      : `<div class="profile-pick-thumb profile-pick-thumb-ph">🔗</div>`;
    const title = clip.title || clip.url || "(無題)";
    return `<div class="profile-pick">
      ${thumb}
      <div class="profile-pick-copy">
        <span class="profile-pick-title">${escapeHtml(title)}</span>
        <span class="profile-pick-url">${escapeHtml(clip.url || "")}</span>
      </div>
      <button class="profile-pick-remove" type="button" data-id="${clip.id}" title="おすすめから外す">×</button>
    </div>`;
  }).join("");
  els.picks.querySelectorAll(".profile-pick-remove").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        profile = await api(`/profile/picks/${button.dataset.id}`, { method: "DELETE" });
        renderPicks();
        setShareStatus("おすすめから外しました", "ok");
      } catch (e) {
        setShareStatus(`削除に失敗しました。${e.message}`, "err");
      }
    });
  });
}

function clipMatches(clip, q) {
  const haystack = [clip.title, clip.url, clip.comment, (clip.tags || []).map((t) => t.name).join(" ")]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

async function loadClips() {
  if (allClips.length) return;
  allClips = await api("/clips");
}

function renderPickList() {
  const pickedIds = new Set((profile.picks || []).map((clip) => clip.id));
  const q = pickSearchText.trim().toLowerCase();
  const list = allClips.filter((clip) => !pickedIds.has(clip.id) && (!q || clipMatches(clip, q)));
  els.pickEmpty.hidden = list.length > 0;
  els.pickList.innerHTML = list.map((clip) => {
    const thumb = clip.thumbnail_url
      ? `<img class="clip-pick-thumb" src="${String(clip.thumbnail_url).replace(/"/g, "&quot;")}" alt="" />`
      : `<div class="clip-pick-thumb clip-pick-thumb-ph">🔗</div>`;
    return `<li class="clip-pick-item" data-id="${clip.id}" role="button" tabindex="0">
      ${thumb}
      <div class="clip-pick-info">
        <span class="clip-pick-title">${escapeHtml(clip.title || "(無題)")}</span>
        <span class="clip-pick-url">${escapeHtml(clip.url || "")}</span>
      </div>
      <span class="clip-pick-add">追加</span>
    </li>`;
  }).join("");
  els.pickList.querySelectorAll(".clip-pick-item").forEach((item) => {
    const add = () => addPick(Number(item.dataset.id));
    item.addEventListener("click", add);
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        add();
      }
    });
  });
}

async function addPick(clipId) {
  try {
    profile = await api("/profile/picks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_id: clipId }),
    });
    renderProfile();
    renderPickList();
    setShareStatus("おすすめに追加しました", "ok");
    if ((profile.picks || []).length >= 3) closePickModal();
  } catch (e) {
    setShareStatus(e.message, "err");
  }
}

function openPickModal() {
  pickSearchText = "";
  els.pickSearch.value = "";
  els.pickModal.hidden = false;
  loadClips()
    .then(renderPickList)
    .catch(() => {
      els.pickList.innerHTML = "";
      els.pickEmpty.hidden = false;
      els.pickEmpty.textContent = "クリップ一覧を取得できませんでした。";
    });
  els.pickSearch.focus();
}

function closePickModal() {
  els.pickModal.hidden = true;
}

els.pickAdd.addEventListener("click", openPickModal);
els.pickClose.addEventListener("click", closePickModal);
els.pickModal.addEventListener("click", (e) => {
  if (e.target === els.pickModal) closePickModal();
});
els.pickSearch.addEventListener("input", () => {
  pickSearchText = els.pickSearch.value;
  if (allClips.length) renderPickList();
  else loadClips().then(renderPickList).catch(() => {});
});
els.pickSearch.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    closePickModal();
  }
});

// ---- Share image ----

function loadCardImage(src) {
  if (!src) return Promise.resolve(null);
  const sameOrigin =
    src.startsWith("/") ||
    src.startsWith(window.location.origin) ||
    src.startsWith("data:");
  const url = sameOrigin ? src : `${API_ROOT}/thumbnail-proxy?url=${encodeURIComponent(src)}`;
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

function truncate(text, max) {
  const value = String(text || "");
  return value.length > max ? value.slice(0, max) + "…" : value;
}

async function buildShareCanvas() {
  const W = 800;
  const H = 480;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  const gradient = ctx.createLinearGradient(0, 0, 0, H);
  gradient.addColorStop(0, "#1c2033");
  gradient.addColorStop(1, "#262b45");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "600 18px system-ui, sans-serif";
  ctx.fillText("SPARKLE", 40, 44);

  const avatar = await loadCardImage(profile.icon_url || "/icon.png");
  const avatarSize = 88;
  const avatarX = 40;
  const avatarY = 84;
  ctx.save();
  ctx.beginPath();
  ctx.arc(avatarX + avatarSize / 2, avatarY + avatarSize / 2, avatarSize / 2, 0, Math.PI * 2);
  ctx.clip();
  if (avatar) {
    const ratio = avatar.naturalWidth / Math.max(avatar.naturalHeight, 1);
    let drawW = avatarSize;
    let drawH = avatarSize;
    if (ratio > 1) {
      drawW = avatarSize * ratio;
    } else {
      drawH = avatarSize / ratio;
    }
    ctx.drawImage(
      avatar,
      avatarX + (avatarSize - drawW) / 2,
      avatarY + (avatarSize - drawH) / 2,
      drawW,
      drawH
    );
  } else {
    ctx.fillStyle = "#4f46e5";
    ctx.fillRect(avatarX, avatarY, avatarSize, avatarSize);
  }
  ctx.restore();

  ctx.fillStyle = "#ffffff";
  ctx.font = "700 32px system-ui, sans-serif";
  ctx.fillText(truncate(profile.username || "ユーザー", 18), avatarX + avatarSize + 24, avatarY + 54);

  const stats = [
    ["累計保存クリップ", `${profile.total_saved}件`],
    ["一週間の保存クリップ", `${profile.saved_last_7_days}件`],
    ["登録からの日数", `${profile.days_since_first}日`],
  ];
  const statY = avatarY + avatarSize + 42;
  stats.forEach(([label, value], i) => {
    const statX = 40 + i * 250;
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "500 15px system-ui, sans-serif";
    ctx.fillText(label, statX, statY);
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 24px system-ui, sans-serif";
    ctx.fillText(value, statX, statY + 30);
  });

  const picks = profile.picks || [];
  const sectionY = statY + 82;
  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.font = "700 20px system-ui, sans-serif";
  ctx.fillText("おすすめのクリップ", 40, sectionY);

  const cardW = 228;
  const cardH = 150;
  const gap = 16;
  const cardY = sectionY + 18;
  const pickColors = ["#4f46e5", "#0e9488", "#c2410c"];
  for (let i = 0; i < 3; i++) {
    const cardX = 40 + i * (cardW + gap);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.roundRect(cardX, cardY, cardW, cardH, 14);
    ctx.fill();

    const clip = picks[i];
    if (!clip) continue;

    const thumbH = 92;
    const thumbPad = 8;
    const thumbAreaH = thumbH - thumbPad;
    const thumb = await loadCardImage(clip.thumbnail_url);
    ctx.save();
    ctx.beginPath();
    ctx.rect(cardX, cardY, cardW, thumbH);
    ctx.clip();
    if (thumb) {
      const ratio = thumb.naturalWidth / Math.max(thumb.naturalHeight, 1);
      let drawW = cardW;
      let drawH = cardW / Math.max(ratio, 0.01);
      if (drawH > thumbAreaH) {
        drawH = thumbAreaH;
        drawW = thumbAreaH * ratio;
      }
      ctx.drawImage(
        thumb,
        cardX + (cardW - drawW) / 2,
        cardY + thumbPad + (thumbAreaH - drawH) / 2,
        drawW,
        drawH
      );
    } else {
      ctx.fillStyle = pickColors[i % pickColors.length];
      ctx.fillRect(cardX, cardY, cardW, thumbH);
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.font = "600 34px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("🔗", cardX + cardW / 2, cardY + 60);
      ctx.textAlign = "left";
    }
    ctx.restore();

    ctx.fillStyle = "#ffffff";
    ctx.font = "600 15px system-ui, sans-serif";
    ctx.fillText(truncate(clip.title || clip.url || "(無題)", 24), cardX + 12, cardY + thumbH + 26);
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "500 12px system-ui, sans-serif";
    ctx.fillText(truncate(clip.url || "", 34), cardX + 12, cardY + thumbH + 46);
  }

  return canvas;
}

async function copyToClipboard(blob) {
  const dataUrl = await new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
  if (dataUrl) {
    try {
      await api("/clipboard/image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_url: dataUrl }),
      });
      return true;
    } catch (e) {}
  }
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch (e) {}
  return false;
}

els.share.addEventListener("click", async () => {
  if (shareBusy) return;
  shareBusy = true;
  els.share.disabled = true;
  setShareStatus("画像を生成しています…");
  try {
    const canvas = await buildShareCanvas();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("画像を生成できませんでした");
    if (await copyToClipboard(blob)) {
      setShareStatus("共有画像をクリップボードにコピーしました", "ok");
    } else {
      els.sharePreview.src = canvas.toDataURL("image/png");
      els.shareModal.hidden = false;
      setShareStatus("画像を表示しました。右クリックから保存できます。", "ok");
    }
  } catch (e) {
    setShareStatus(`共有画像の生成に失敗しました。${e.message}`, "err");
  } finally {
    shareBusy = false;
    els.share.disabled = false;
  }
});

els.shareClose.addEventListener("click", () => {
  els.shareModal.hidden = true;
});
els.shareModal.addEventListener("click", (e) => {
  if (e.target === els.shareModal) els.shareModal.hidden = true;
});

loadProfile().catch((e) => {
  setShareStatus(`プロフィールを読み込めませんでした。${e.message}`, "err");
});
