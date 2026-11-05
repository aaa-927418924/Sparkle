const test = require("node:test");
const assert = require("node:assert/strict");

const pluginTheme = require("../frontend/plugin-theme.js");

function makeRoot() {
  const styles = new Map();
  const attributes = new Set();
  const events = [];
  const html = {
    dataset: {},
    style: {
      setProperty: (key, value) => styles.set(key, value),
      removeProperty: (key) => styles.delete(key),
    },
    removeAttribute: (key) => {
      attributes.delete(key);
      if (key === "data-sparkle-plugin-theme") delete html.dataset.sparklePluginTheme;
    },
  };
  class FakeCustomEvent {
    constructor(type, options) {
      this.type = type;
      this.detail = options?.detail;
    }
  }
  return {
    document: { documentElement: html },
    html,
    styles,
    attributes,
    events,
    CustomEvent: FakeCustomEvent,
    dispatchEvent: (event) => events.push(event),
  };
}

test("plugin themes apply only validated color tokens and clear cleanly", () => {
  const root = makeRoot();
  const applied = pluginTheme.apply(root, {
    id: "ocean-night",
    colors: {
      background: "#102030",
      accent: "rgb(80, 120, 180)",
      border: "url(https://example.invalid/theme)",
    },
  });

  assert.deepEqual(applied, {
    id: "ocean-night",
    colors: { "--bg": "#102030", "--accent": "rgb(80, 120, 180)" },
  });
  assert.equal(root.styles.get("--bg"), "#102030");
  assert.equal(root.styles.has("--border"), false);
  assert.equal(root.html.dataset.sparklePluginTheme, "ocean-night");

  pluginTheme.apply(root, null);
  assert.equal(root.styles.size, 0);
  assert.equal(root.html.dataset.sparklePluginTheme, undefined);
});

test("plugin theme ids and CSS payloads are rejected", () => {
  assert.equal(pluginTheme.normalize({ id: "../plugin", colors: { background: "#102030" } }), null);
  assert.equal(pluginTheme.normalize({ id: "unsafe", colors: { background: "red; color: blue" } }), null);
});

test("component colors and allowlisted sidebar icon modes are applied independently", () => {
  const root = makeRoot();
  const applied = pluginTheme.apply(root, {
    id: "cloudlight-teal",
    colors: {
      text: "#101713",
      homeText: "#101713",
      homeCard: "#FFFFFF",
      projectCardText: "#101713",
    },
    icons: { sidebar: "dark", sidebarActive: "dark" },
  });

  assert.equal(root.styles.get("--theme-home-text"), "#101713");
  assert.equal(root.styles.get("--theme-home-card"), "#FFFFFF");
  assert.equal(root.styles.get("--theme-project-card-text"), "#101713");
  assert.equal(root.styles.get("--sidebar-icon-filter"), "brightness(0) saturate(100%)");
  assert.equal(root.styles.get("--sidebar-active-icon-filter"), "brightness(0) saturate(100%)");
  assert.equal(applied.colors["--theme-home-text"], "#101713");

  pluginTheme.apply(root, {
    id: "lamplight-night",
    colors: { text: "#E6E3DC" },
    icons: { sidebar: "light", sidebarActive: "light" },
  });
  assert.equal(root.styles.get("--sidebar-icon-filter"), "brightness(0) saturate(100%) invert(1)");
  assert.equal(root.styles.has("--theme-home-text"), false);
});

test("unrecognized icon modes cannot become CSS values", () => {
  const root = makeRoot();
  pluginTheme.apply(root, {
    id: "unsafe-icons",
    colors: { text: "#eeeeee" },
    icons: { sidebar: "invert(1); color: red" },
  });
  assert.equal(root.styles.has("--sidebar-icon-filter"), false);
});

test("control tokens and action icon modes are sanitized and exposed to feature panels", () => {
  const root = makeRoot();
  const applied = pluginTheme.set(root, {
    id: "cloudlight-teal",
    name: "Cloudlight",
    colors: {
      controlActiveText: "#0B473A",
      actionButtonHoverBackground: "#E1EAE5",
      checkboxAccent: "#145F4D",
      unsupported: "#FFFFFF",
    },
    icons: {
      sidebar: "dark",
      action: "dark",
      actionActive: "source",
      inline: "dark",
      unsafe: "invert(1)",
    },
    privateData: "must not be forwarded",
  });

  assert.equal(applied.colors["--theme-control-active-text"], "#0B473A");
  assert.equal(root.styles.get("--theme-action-button-hover-background"), "#E1EAE5");
  assert.equal(root.styles.get("--theme-checkbox-accent"), "#145F4D");
  assert.equal(root.styles.get("--action-icon-filter"), "brightness(0) saturate(100%)");
  assert.equal(root.styles.get("--action-active-icon-filter"), "none");
  assert.equal(root.styles.get("--inline-icon-filter"), "brightness(0) saturate(100%)");
  assert.deepEqual(pluginTheme.getPluginTheme(root), {
    id: "cloudlight-teal",
    colors: {
      controlActiveText: "#0B473A",
      actionButtonHoverBackground: "#E1EAE5",
      checkboxAccent: "#145F4D",
    },
    name: "Cloudlight",
    icons: { sidebar: "dark", action: "dark", actionActive: "source", inline: "dark" },
  });
  assert.equal(root.events.at(-1).type, "sparkle-plugin-theme-changed");
  assert.deepEqual(root.events.at(-1).detail.theme, pluginTheme.getPluginTheme(root));

  const exposed = pluginTheme.getPluginTheme(root);
  exposed.colors.checkboxAccent = "#FFFFFF";
  assert.equal(pluginTheme.getPluginTheme(root).colors.checkboxAccent, "#145F4D");
});
