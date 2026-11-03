# Sparkle plugin package format

Sparkle plugin API version 1 accepts a ZIP whose root contains manifest.json.
The ZIP is imported disabled. Users must enable it in Sparkle Settings.

## Update compatibility

Sparkle keeps a plugin API version stable across app updates that do not declare
an API break. A breaking change requires a new `api_version`. If an installed
plugin is not compatible with the current API, Sparkle leaves its package and
private data in place, keeps it disabled, and allows the package to be exported
for backup or use with a compatible Sparkle release. Removing a plugin removes
only that package and its explicitly selected plugin-owned data.

## Theme plugin

Files:

~~~~text
manifest.json
theme.json
~~~~

manifest.json:

~~~~json
{
  "id": "ocean-night",
  "name": "Ocean Night",
  "version": "1.0.0",
  "api_version": 1,
  "type": "theme",
  "description": "A deep blue theme.",
  "permissions": []
}
~~~~

The id uses lowercase letters, numbers, and single hyphens. The version uses
major.minor.patch. The current Sparkle release supports API version 1.

theme.json:

~~~~json
{
  "colors": {
    "background": "#20263A",
    "surface": "#252D44",
    "surfaceRaised": "#2B3550",
    "surfaceHover": "#34405E",
    "surfaceActive": "#3C4A6B",
    "sidebar": "#1C2235",
    "border": "#46516C",
    "borderStrong": "#596684",
    "text": "#EEF2FF",
    "muted": "#AAB4CF",
    "accent": "#88C0D0",
    "accentSoft": "#314A5D"
  }
}
~~~~

Every color property is optional, but at least one is required. Values must be
hex colors or simple rgb() / rgba() values. Do not add CSS or executable code
to a theme package.

## Feature panel plugin

Files:

~~~~text
manifest.json
panel.html
assets/...
~~~~

Set type to feature, include panel.html at the package root, and list only the
permissions the panel uses. The optional storage permission enables plugin-owned
JSON values. notifications allows the panel to request a Sparkle status
message. No permission grants access to Sparkle's database or filesystem.

The panel is loaded only after the user clicks its Open button. It runs in a
sandboxed frame with no direct Sparkle DOM access and no network access. Local
assets can be referenced relative to panel.html.

### Host message bridge

Send a request to the parent frame using postMessage. Use * as the target
because the sandboxed frame has an opaque origin. Sparkle validates that the
message came from the active plugin's own frame.

~~~~js
const requestId = crypto.randomUUID();
window.parent.postMessage(
  {
    type: "sparkle-plugin-request",
    requestId,
    method: "notify",
    message: "Ready"
  },
  "*"
);
~~~~

Supported methods:

- notify: { method: "notify", message: "..." }
- storage.get: { method: "storage.get", key: "..." }
- storage.set: { method: "storage.set", key: "...", value: <JSON value> }

Sparkle replies to the same frame:

~~~~js
window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  if (event.data?.type !== "sparkle-plugin-response") return;
  // event.data contains requestId, ok, and (for storage.get) value.
});
~~~~

The storage bridge works only when storage is declared in the manifest and the
plugin is enabled. Values are isolated by plugin ID and limited to 2 MB.

## Existing Sparkle features

API version 1 supports theme tokens and isolated feature panels. It does not
provide hooks to replace or monkey-patch existing Sparkle behavior. If a plugin
needs a supported action or UI extension point, describe the required hook
without changing Sparkle's core files.
