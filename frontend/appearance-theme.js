(function (root, factory) {
  const api = factory();

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (!root || !root.document) return;

  // Apply the selected theme and its small wallpaper preview before stylesheets
  // paint. IndexedDB can restore the full image after the page is visible.
  api.bootstrap(root);

  const start = () => {
    const controller = api.createController(root);
    root.SparkleAppearanceTheme = controller;
    controller.ready = controller.init();
  };

  if (root.document.readyState === "loading") {
    root.document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  const SETTINGS_KEY = "sparkle.appearance.wallpaper";
  const DATABASE_NAME = "sparkle-appearance";
  const DATABASE_VERSION = 1;
  const STORE_NAME = "assets";
  const WALLPAPER_KEY = "background";
  const WALLPAPER_PREVIEW_KEY = "sparkle.appearance.wallpaper.preview";
  const MAX_PREVIEW_DATA_URL_LENGTH = 1_200_000;
  const MAX_WALLPAPER_BYTES = 25 * 1024 * 1024;
  const DEFAULT_SETTINGS = Object.freeze({
    theme: "catppuccin",
    blur: 8,
    transparency: 15,
  });
  const ALLOWED_TYPES = new Set([
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
  ]);
  const ALLOWED_EXTENSIONS = new Set([
    "avif",
    "bmp",
    "gif",
    "jpeg",
    "jpg",
    "png",
    "webp",
  ]);

  function clampInteger(value, fallback, min, max) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, Math.round(number)));
  }

  function normalizeSettings(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      theme: source.theme === "custom" ? "custom" : "catppuccin",
      blur: clampInteger(source.blur, DEFAULT_SETTINGS.blur, 0, 24),
      transparency: clampInteger(
        source.transparency,
        DEFAULT_SETTINGS.transparency,
        0,
        100
      ),
    };
  }

  function opacityFromTransparency(transparency) {
    const amount = clampInteger(transparency, DEFAULT_SETTINGS.transparency, 0, 100);
    return (100 - amount) / 100;
  }

  function isSupportedWallpaperFile(file) {
    if (!file || !Number.isFinite(Number(file.size))) return false;
    if (Number(file.size) <= 0 || Number(file.size) > MAX_WALLPAPER_BYTES) {
      return false;
    }
    const type = String(file.type || "").toLowerCase();
    const extension = String(file.name || "").split(".").pop().toLowerCase();
    return ALLOWED_TYPES.has(type) || (!type && ALLOWED_EXTENSIONS.has(extension));
  }

  function readSettings(root) {
    try {
      return normalizeSettings(
        JSON.parse(root.localStorage.getItem(SETTINGS_KEY) || "null")
      );
    } catch {
      return normalizeSettings(null);
    }
  }

  function readWallpaperPreview(root) {
    try {
      const value = root.localStorage.getItem(WALLPAPER_PREVIEW_KEY) || "";
      if (
        value.length <= MAX_PREVIEW_DATA_URL_LENGTH &&
        /^data:image\/(?:webp|png|jpeg);base64,/i.test(value)
      ) {
        return value;
      }
    } catch {
      // Fall back to the normal IndexedDB restore when local storage is unavailable.
    }
    return "";
  }

  function writeWallpaperPreview(root, value) {
    if (
      typeof value !== "string" ||
      value.length > MAX_PREVIEW_DATA_URL_LENGTH ||
      !/^data:image\/(?:webp|png|jpeg);base64,/i.test(value)
    ) {
      return false;
    }
    try {
      root.localStorage.setItem(WALLPAPER_PREVIEW_KEY, value);
      return true;
    } catch {
      return false;
    }
  }

  function removeWallpaperPreview(root) {
    try {
      root.localStorage.removeItem(WALLPAPER_PREVIEW_KEY);
    } catch {
      // Removing a cache must not block the theme reset.
    }
  }

  async function createWallpaperPreview(root, blob) {
    if (!blob || !root.createImageBitmap || !root.document?.createElement) return "";

    let bitmap;
    try {
      bitmap = await root.createImageBitmap(blob);
      const longestSide = Math.max(bitmap.width, bitmap.height);
      if (!longestSide) return "";

      for (const maxSide of [1024, 768, 512]) {
        const scale = Math.min(1, maxSide / longestSide);
        const canvas = root.document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext("2d");
        if (!context) return "";
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

        for (const quality of [0.72, 0.58]) {
          const preview = canvas.toDataURL("image/webp", quality);
          if (
            preview.length <= MAX_PREVIEW_DATA_URL_LENGTH &&
            /^data:image\/(?:webp|png|jpeg);base64,/i.test(preview)
          ) {
            return preview;
          }
        }
      }
    } catch {
      return "";
    } finally {
      try {
        bitmap?.close?.();
      } catch {
        // Bitmap cleanup is best effort.
      }
    }
    return "";
  }

  function bootstrap(root) {
    const html = root?.document?.documentElement;
    if (!html) return normalizeSettings(null);

    const settings = readSettings(root);
    if (settings.theme === "custom") {
      html.setAttribute("data-custom-wallpaper", "active");
      const preview = readWallpaperPreview(root);
      if (preview) {
        html.style.setProperty(
          "--sparkle-wallpaper-image",
          `url("${preview}")`
        );
      } else {
        html.style.removeProperty("--sparkle-wallpaper-image");
      }
      html.style.setProperty("--sparkle-wallpaper-blur", `${settings.blur}px`);
      html.style.setProperty(
        "--sparkle-wallpaper-opacity",
        String(opacityFromTransparency(settings.transparency))
      );
    } else {
      html.removeAttribute("data-custom-wallpaper");
      html.style.removeProperty("--sparkle-wallpaper-image");
      html.style.removeProperty("--sparkle-wallpaper-blur");
      html.style.removeProperty("--sparkle-wallpaper-opacity");
    }
    return settings;
  }

  function writeSettings(root, settings) {
    try {
      let revision = 0;
      try {
        const current = JSON.parse(root.localStorage.getItem(SETTINGS_KEY) || "null");
        revision = Number.isFinite(Number(current?.revision))
          ? Number(current.revision)
          : 0;
      } catch {
        revision = 0;
      }
      root.localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({ ...normalizeSettings(settings), revision: revision + 1 })
      );
      return true;
    } catch {
      return false;
    }
  }

  function removeStoredSettings(root) {
    try {
      root.localStorage.removeItem(SETTINGS_KEY);
      return true;
    } catch {
      return false;
    }
  }

  function openDatabase(root) {
    if (!root.indexedDB) {
      return Promise.reject(new Error("画像保存に対応していません。"));
    }

    return new Promise((resolve, reject) => {
      const request = root.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          database.createObjectStore(STORE_NAME);
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("画像保存を開けません。"));
    });
  }

  async function runTransaction(root, mode, operation) {
    const database = await openDatabase(root);
    return new Promise((resolve, reject) => {
      let result;
      let request;
      let settled = false;
      const fail = (error) => {
        if (settled) return;
        settled = true;
        reject(error || new Error("画像設定を保存できませんでした。"));
      };

      try {
        const transaction = database.transaction(STORE_NAME, mode);
        request = operation(transaction.objectStore(STORE_NAME));
        request.onsuccess = () => {
          result = request.result;
        };
        request.onerror = () => fail(request.error);
        transaction.oncomplete = () => {
          if (settled) return;
          settled = true;
          resolve(result);
        };
        transaction.onerror = () => fail(transaction.error);
        transaction.onabort = () => fail(transaction.error);
      } catch (error) {
        fail(error);
      }
    });
  }

  function getWallpaper(root) {
    return runTransaction(root, "readonly", (store) => store.get(WALLPAPER_KEY));
  }

  function putWallpaper(root, file) {
    return runTransaction(root, "readwrite", (store) =>
      store.put({ blob: file, name: file.name || "背景画像" }, WALLPAPER_KEY)
    );
  }

  function deleteWallpaper(root) {
    return runTransaction(root, "readwrite", (store) => store.delete(WALLPAPER_KEY));
  }

  function createController(root) {
    const document = root.document;
    const controls = {
      file: document.getElementById("appearanceBackgroundFile"),
      fileName: document.getElementById("appearanceBackgroundName"),
      themeSelect: document.getElementById("pluginThemeSelect"),
      fields: document.querySelector("[data-appearance-theme-fields]"),
      blur: document.getElementById("appearanceBackgroundBlur"),
      blurValue: document.getElementById("appearanceBackgroundBlurValue"),
      transparency: document.getElementById("appearanceBackgroundTransparency"),
      transparencyValue: document.getElementById("appearanceBackgroundTransparencyValue"),
      status: document.getElementById("appearanceBackgroundStatus"),
    };

    let settings = readSettings(root);
    let wallpaper = null;
    let appliedWallpaper = null;
    let objectUrl = "";
    let initialized = false;
    let previewGeneration = 0;

    function setStatus(message) {
      if (controls.status) controls.status.textContent = message;
    }

    function syncControls() {
      const customSelected = settings.theme === "custom";
      if (controls.themeSelect && ["catppuccin", "custom"].includes(controls.themeSelect.value)) {
        controls.themeSelect.value = settings.theme;
      }
      if (controls.fields) controls.fields.hidden = !customSelected;
      if (controls.file) controls.file.disabled = !customSelected;
      if (controls.blur) controls.blur.value = String(settings.blur);
      if (controls.blur) controls.blur.disabled = !customSelected;
      if (controls.blurValue) controls.blurValue.textContent = `${settings.blur} px`;
      if (controls.transparency) {
        controls.transparency.value = String(settings.transparency);
        controls.transparency.disabled = !customSelected;
      }
      if (controls.transparencyValue) {
        controls.transparencyValue.textContent = `${settings.transparency}%`;
      }
      if (controls.fileName) {
        controls.fileName.textContent = wallpaper?.name || "画像は選択されていません";
      }
    }

    function releaseObjectUrl() {
      if (!objectUrl) return;
      try {
        root.URL.revokeObjectURL(objectUrl);
      } catch {
        // A stale preview URL must not prevent the new theme state from applying.
      }
      objectUrl = "";
      appliedWallpaper = null;
    }

    function applyVisuals() {
      const html = document.documentElement;
      const opacity = opacityFromTransparency(settings.transparency);
      html.style.setProperty("--sparkle-wallpaper-blur", `${settings.blur}px`);
      html.style.setProperty("--sparkle-wallpaper-opacity", String(opacity));

      if (settings.theme === "custom") {
        // Keep using the same localStorage preview that bootstrap applied in
        // <head>. Replacing it with a fresh blob: URL after every page load
        // makes WebView2 decode the image again and briefly exposes the solid
        // Catppuccin underlay during navigation.
        const preview = readWallpaperPreview(root);
        if (preview) {
          releaseObjectUrl();
          const previewValue = `url("${preview}")`;
          if (html.style.getPropertyValue("--sparkle-wallpaper-image") !== previewValue) {
            html.style.setProperty("--sparkle-wallpaper-image", previewValue);
          }
          html.setAttribute("data-custom-wallpaper", "active");
          return;
        }
      }

      if (settings.theme === "custom" && wallpaper?.blob && root.URL?.createObjectURL) {
        if (appliedWallpaper !== wallpaper || !objectUrl) {
          releaseObjectUrl();
          try {
            objectUrl = root.URL.createObjectURL(wallpaper.blob);
            appliedWallpaper = wallpaper;
          } catch {
            wallpaper = null;
            html.removeAttribute("data-custom-wallpaper");
            html.style.removeProperty("--sparkle-wallpaper-image");
            setStatus("背景画像を表示できませんでした。");
            return;
          }
        }
        html.style.setProperty(
          "--sparkle-wallpaper-image",
          `url("${objectUrl}")`
        );
        html.setAttribute("data-custom-wallpaper", "active");
      } else {
        releaseObjectUrl();
        html.removeAttribute("data-custom-wallpaper");
        html.style.removeProperty("--sparkle-wallpaper-image");
      }
    }

    function persistControlValues() {
      settings = normalizeSettings({
        ...settings,
        blur: controls.blur?.value ?? settings.blur,
        transparency: controls.transparency?.value ?? settings.transparency,
      });
      syncControls();
      applyVisuals();
      if (!writeSettings(root, settings)) {
        setStatus("表示設定をこの端末に保存できませんでした。");
      }
    }

    async function restore() {
      settings = readSettings(root);
      bootstrap(root);
      let loadFailed = false;
      let nextWallpaper = null;
      if (settings.theme === "custom") {
        try {
          nextWallpaper = await getWallpaper(root);
        } catch {
          loadFailed = true;
          setStatus("保存した背景画像を読み込めませんでした。");
        }
      }

      wallpaper = nextWallpaper?.blob ? nextWallpaper : null;
      syncControls();
      if (wallpaper?.blob && !readWallpaperPreview(root)) {
        const generation = ++previewGeneration;
        const preview = await createWallpaperPreview(root, wallpaper.blob);
        if (preview && generation === previewGeneration) {
          writeWallpaperPreview(root, preview);
        }
      }
      applyVisuals();
      if (!loadFailed && controls.status) {
        setStatus(settings.theme === "custom" && !wallpaper
          ? "画像を選ぶとカスタム背景が表示されます。"
          : "");
      }
    }

    async function selectTheme(theme) {
      settings = normalizeSettings({ ...settings, theme });
      if (settings.theme === "custom" && !wallpaper) {
        try {
          const savedWallpaper = await getWallpaper(root);
          wallpaper = savedWallpaper?.blob ? savedWallpaper : null;
        } catch {
          setStatus("保存した背景画像を読み込めませんでした。");
        }
      }
      syncControls();
      applyVisuals();
      if (!writeSettings(root, settings)) {
        setStatus("テーマ設定をこの端末に保存できませんでした。");
      } else if (settings.theme === "custom" && !wallpaper) {
        setStatus("画像を選ぶとカスタム背景が表示されます。");
      } else {
        setStatus("");
      }
    }

    async function chooseWallpaper() {
      const file = controls.file?.files?.[0];
      if (!file) return;
      if (!isSupportedWallpaperFile(file)) {
        setStatus("PNG、JPG、WebP、AVIF、GIF、BMP画像（25 MB以下）を選択してください。");
        controls.file.value = "";
        return;
      }

      setStatus("背景画像を保存しています…");
      try {
        const generation = ++previewGeneration;
        const previewPromise = createWallpaperPreview(root, file);
        await putWallpaper(root, file);
        wallpaper = { blob: file, name: file.name || "背景画像" };
        const preview = await previewPromise;
        if (preview && generation === previewGeneration) {
          writeWallpaperPreview(root, preview);
        }
        const saved = writeSettings(root, settings);
        syncControls();
        applyVisuals();
        setStatus(
          saved
            ? "背景画像を保存しました。"
            : "背景画像は表示中ですが、設定を保存できませんでした。"
        );
      } catch {
        setStatus("背景画像を保存できませんでした。別の画像を選んでください。");
      } finally {
        controls.file.value = "";
      }
    }

    async function reset() {
      previewGeneration += 1;
      settings = normalizeSettings(null);
      wallpaper = null;
      syncControls();
      applyVisuals();
      const saved = removeStoredSettings(root);
      removeWallpaperPreview(root);
      try {
        await deleteWallpaper(root);
        setStatus(saved ? "背景画像と表示設定を初期状態に戻しました。" : "表示設定を初期状態に戻しました。");
      } catch {
        setStatus("表示設定を初期状態に戻しました。");
      }
    }

    let ready = Promise.resolve();

    function init() {
      if (initialized) return ready;
      initialized = true;
      controls.blur?.addEventListener("input", persistControlValues);
      controls.transparency?.addEventListener("input", persistControlValues);
      controls.blur?.addEventListener("change", () => setStatus("背景画像の表示設定を保存しました。"));
      controls.transparency?.addEventListener("change", () => setStatus("背景画像の表示設定を保存しました。"));
      controls.file?.addEventListener("change", () => void chooseWallpaper());
      root.addEventListener("storage", (event) => {
        if (event.key === SETTINGS_KEY) void restore();
      });
      ready = restore();
      return ready;
    }

    return {
      getTheme: () => settings.theme,
      init,
      reset,
      restore,
      selectTheme,
    };
  }

  return {
    DEFAULT_SETTINGS,
    MAX_WALLPAPER_BYTES,
    bootstrap,
    createController,
    isSupportedWallpaperFile,
    normalizeSettings,
    opacityFromTransparency,
  };
});
