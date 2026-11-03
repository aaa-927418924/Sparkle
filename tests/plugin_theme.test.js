const test = require("node:test");
const assert = require("node:assert/strict");

const pluginTheme = require("../frontend/plugin-theme.js");

function makeRoot() {
  const styles = new Map();
  const attributes = new Set();
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
  return {
    document: { documentElement: html },
    html,
    styles,
    attributes,
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
