(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (!root || !root.document) return;

  root.SparklePluginTheme = {
    setPluginTheme: (theme) => api.apply(root, theme),
    syncPluginTheme: () => api.sync(root),
  };
  api.sync(root);
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

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
    return Object.keys(colors).length ? { id, colors } : null;
  }

  function apply(root, value) {
    const html = root.document?.documentElement;
    if (!html) return null;
    for (const property of Object.values(properties)) html.style.removeProperty(property);
    const theme = normalize(value);
    if (!theme) {
      html.removeAttribute("data-sparkle-plugin-theme");
      return null;
    }
    for (const [property, color] of Object.entries(theme.colors)) {
      html.style.setProperty(property, color);
    }
    html.dataset.sparklePluginTheme = theme.id;
    return theme;
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
          apply(root, body.theme);
        }
      })
      .catch(() => {});
  }

  return { apply, normalize, properties, sync };
});
