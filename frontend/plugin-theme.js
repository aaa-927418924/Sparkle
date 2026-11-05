(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (!root || !root.document) return;

  // Apply the last server-confirmed plugin theme before stylesheets paint.
  api.applyCached(root);
  root.SparklePluginTheme = {
    setPluginTheme: (theme) => api.set(root, theme),
    syncPluginTheme: () => api.sync(root),
    getPluginTheme: () => api.getPluginTheme(root),
  };
  api.sync(root);
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  const CACHE_KEY = "sparkle.plugin-theme.cache.v1";
  const properties = Object.freeze({
    background: "--bg",
    surface: "--surface",
    surfaceRaised: "--surface-raised",
    surfaceHover: "--surface-hover",
    surfaceActive: "--surface-active",
    sidebar: "--sidebar-bg",
    border: "--border",
    borderStrong: "--border-strong",
    text: "--text",
    muted: "--muted",
    accent: "--accent",
    accentSoft: "--accent-soft",
    sidebarText: "--theme-sidebar-text",
    sidebarTextActive: "--theme-sidebar-text-active",
    sidebarHover: "--theme-sidebar-hover",
    sidebarActive: "--theme-sidebar-active",
    projectCard: "--theme-project-card",
    projectCardText: "--theme-project-card-text",
    projectCardMuted: "--theme-project-card-muted",
    projectDetailText: "--theme-project-detail-text",
    taskPanel: "--theme-task-panel",
    taskText: "--theme-task-text",
    taskMuted: "--theme-task-muted",
    taskAccent: "--theme-task-accent",
    memoCard: "--theme-memo-card",
    memoText: "--theme-memo-text",
    memoMuted: "--theme-memo-muted",
    notesBackground: "--theme-notes-background",
    notesSidebar: "--theme-notes-sidebar",
    notesPanel: "--theme-notes-panel",
    notesCard: "--theme-notes-card",
    notesText: "--theme-notes-text",
    notesMuted: "--theme-notes-muted",
    notesBorder: "--theme-notes-border",
    notesAccent: "--theme-notes-accent",
    homeBackground: "--theme-home-background",
    homeSidebar: "--theme-home-sidebar",
    homeSurface: "--theme-home-surface",
    homeText: "--theme-home-text",
    homeMuted: "--theme-home-muted",
    homeBorder: "--theme-home-border",
    homeAccent: "--theme-home-accent",
    homeCard: "--theme-home-card",
    homeActive: "--theme-home-active",
    homeActionSurface: "--theme-home-action-surface",
    homeActionText: "--theme-home-action-text",
    homeTagText: "--theme-home-tag-text",
    homeTagBorder: "--theme-home-tag-border",
    homeTagActive: "--theme-home-tag-active",
    homeTagActiveText: "--theme-home-tag-active-text",
    controlBackground: "--theme-control-background",
    controlText: "--theme-control-text",
    controlHoverBackground: "--theme-control-hover-background",
    controlHoverText: "--theme-control-hover-text",
    controlActiveBackground: "--theme-control-active-background",
    controlActiveText: "--theme-control-active-text",
    actionButtonBackground: "--theme-action-button-background",
    actionButtonText: "--theme-action-button-text",
    actionButtonBorder: "--theme-action-button-border",
    actionButtonHoverBackground: "--theme-action-button-hover-background",
    actionButtonHoverText: "--theme-action-button-hover-text",
    actionButtonHoverBorder: "--theme-action-button-hover-border",
    checkboxBackground: "--theme-checkbox-background",
    checkboxBorder: "--theme-checkbox-border",
    checkboxAccent: "--theme-checkbox-accent",
  });
  const iconProperties = Object.freeze({
    sidebar: "--sidebar-icon-filter",
    sidebarActive: "--sidebar-active-icon-filter",
    action: "--action-icon-filter",
    actionActive: "--action-active-icon-filter",
    inline: "--inline-icon-filter",
  });
  const iconModes = Object.freeze({
    source: "none",
    dark: "brightness(0) saturate(100%)",
    light: "brightness(0) saturate(100%) invert(1)",
  });
  const idPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const colorPattern =
    /^(?:#[0-9a-f]{6}(?:[0-9a-f]{2})?|rgba?\(\s*(?:\d{1,3}%?\s*,\s*){2}\d{1,3}%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\))$/i;

  function normalize(theme) {
    if (!theme || typeof theme !== "object") return null;
    const id = String(theme.id || "");
    if (!idPattern.test(id)) return null;
    const source = theme.colors && typeof theme.colors === "object" ? theme.colors : {};
    const colors = {};
    for (const [key, property] of Object.entries(properties)) {
      const value = source[key];
      if (typeof value === "string" && value.length <= 40 && colorPattern.test(value.trim())) {
        colors[property] = value.trim();
      }
    }
    if (!Object.keys(colors).length) return null;
    const icons = {};
    const sourceIcons = theme.icons && typeof theme.icons === "object" ? theme.icons : {};
    for (const [key, property] of Object.entries(iconProperties)) {
      const mode = sourceIcons[key];
      if (Object.prototype.hasOwnProperty.call(iconModes, mode)) icons[property] = iconModes[mode];
    }
    return Object.keys(icons).length ? { id, colors, icons } : { id, colors };
  }

  function publicTheme(value) {
    const normalized = normalize(value);
    if (!normalized) return null;
    const source = value && typeof value === "object" ? value : {};
    const colors = {};
    for (const [key, property] of Object.entries(properties)) {
      if (Object.prototype.hasOwnProperty.call(normalized.colors, property)) {
        colors[key] = normalized.colors[property];
      }
    }
    const icons = {};
    const sourceIcons = source.icons && typeof source.icons === "object" ? source.icons : {};
    for (const key of Object.keys(iconProperties)) {
      if (Object.prototype.hasOwnProperty.call(iconModes, sourceIcons[key])) icons[key] = sourceIcons[key];
    }
    const result = { id: normalized.id, colors };
    if (typeof source.name === "string" && source.name.length <= 120) result.name = source.name;
    if (Object.keys(icons).length) result.icons = icons;
    return result;
  }

  function getPluginTheme(root) {
    const current = root?.__sparklePluginTheme;
    return current ? JSON.parse(JSON.stringify(current)) : null;
  }

  function apply(root, value) {
    const html = root.document?.documentElement;
    if (!html) return null;
    for (const property of [...Object.values(properties), ...Object.values(iconProperties)]) {
      html.style.removeProperty(property);
    }
    const theme = normalize(value);
    if (!theme) {
      html.removeAttribute("data-sparkle-plugin-theme");
      root.__sparklePluginTheme = null;
      return null;
    }
    for (const [property, color] of Object.entries(theme.colors)) {
      html.style.setProperty(property, color);
    }
    for (const [property, filter] of Object.entries(theme.icons || {})) {
      html.style.setProperty(property, filter);
    }
    html.dataset.sparklePluginTheme = theme.id;
    root.__sparklePluginTheme = publicTheme(value);
    return theme;
  }

  function storeTheme(root, value) {
    try {
      const theme = normalize(value);
      if (!theme) {
        root.localStorage.removeItem(CACHE_KEY);
        return;
      }

      const colors = {};
      for (const [key, property] of Object.entries(properties)) {
        if (Object.prototype.hasOwnProperty.call(theme.colors, property)) {
          colors[key] = theme.colors[property];
        }
      }
      const icons = {};
      for (const key of Object.keys(iconProperties)) {
        const mode = value.icons?.[key];
        if (Object.prototype.hasOwnProperty.call(iconModes, mode)) icons[key] = mode;
      }
      const cached = { id: theme.id, colors, icons };
      if (typeof value.name === "string" && value.name.length <= 120) cached.name = value.name;
      root.localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
    } catch {
      // The server response remains authoritative if storage is unavailable.
    }
  }

  function set(root, value) {
    const theme = apply(root, value);
    storeTheme(root, value);
    if (typeof root?.dispatchEvent === "function" && typeof root?.CustomEvent === "function") {
      root.dispatchEvent(new root.CustomEvent("sparkle-plugin-theme-changed", {
        detail: { theme: getPluginTheme(root) },
      }));
    }
    return theme;
  }

  function applyCached(root) {
    try {
      const cached = JSON.parse(root.localStorage.getItem(CACHE_KEY) || "null");
      return apply(root, cached);
    } catch {
      return apply(root, null);
    }
  }

  function sync(root) {
    if (!root.fetch || !root.location?.origin) return;
    root.fetch(root.location.origin + "/plugins/active-theme", {
      cache: "no-store",
      credentials: "same-origin",
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (body && Object.prototype.hasOwnProperty.call(body, "theme")) {
          set(root, body.theme);
        }
      })
      .catch(() => {});
  }

  return { apply, applyCached, getPluginTheme, normalize, properties, iconProperties, set, sync };
});
