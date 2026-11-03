# Sparkle plugin package format

Sparkle accepts a ZIP whose root contains `manifest.json`. The ZIP is imported
disabled. Users must enable it in Sparkle Settings.

The current contracts are API v1, API v2, and API v3:

- API v1 supports theme tokens and isolated feature panels.
- API v2 supports everything in v1 and adds the declarative UI contributions
  described below. An API v2 host treats API v1 plugins as compatible.
- API v3 supports everything in v2 and adds the permissioned clip/project data
  bridge described below. An API v3 host treats API v1 and API v2 plugins as
  compatible.
- An API v1 or v2 host treats a newer API plugin as incompatible. It keeps the package
  and private data, leaves the plugin disabled, and allows the package to be
  exported for use with a compatible Sparkle release.

Set `api_version` to the lowest API version the plugin needs. Use API v2 for a
feature plugin that declares `contributes`. Use API v3 for a plugin that
declares any clip/project data permission. A plugin that needs both uses API v3
and can still declare the API v2 UI contributions.

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
major.minor.patch. `api_version` is an integer, currently 1, 2, or 3.

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
permissions the panel uses. API v3 data permissions are opt-in and independent:

| Permission | Allows |
| --- | --- |
| `storage` | Read/write JSON values in the plugin's private namespace. |
| `notifications` | Request a Sparkle status message. |
| `ui.customize` | Use the allowlisted API v2 declarative UI contributions. |
| `clips.read` | List and read clip metadata and project associations. |
| `clips.write` | Create web clips and edit supported clip metadata. |
| `clips.delete` | Delete clips through Sparkle's clip lifecycle. |
| `projects.read` | List and read project name, description, and completion state. |
| `projects.write` | Create projects and edit name/description. |
| `projects.delete` | Delete a project grouping and detach its relationships. |

API v3 starts with no permissions granted. Sparkle asks separately the first
time an operation needs each permission and stores the decision for that
plugin on that installation. `ui.customize` is requested when the user enables
the plugin. In Settings > Plugins, `権限を削除` revokes all grants for that
plugin; the next use asks again. API v1/v2 plugins retain their existing
manifest-based grants for compatibility until the user uses this revoke
action. Importing a plugin starts disabled.

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
- clips.list: list clips; optional `filters` contains `category`, `tag`, `url`,
  `project_id`, or `exclude_project`.
- clips.get: read one clip by numeric `id`.
- clips.create: create a web clip with a JSON `payload`.
- clips.update: update a clip by numeric `id` with a JSON `payload`.
- clips.delete: delete a clip by numeric `id`.
- projects.list: list projects.
- projects.get: read one project by numeric `id`.
- projects.create: create a project with a JSON `payload`.
- projects.update: update a project by numeric `id` with a JSON `payload`.
- projects.delete: delete a project grouping by numeric `id`.

The data methods use the same request/response envelope as the storage bridge:
include a unique `requestId`, then read `ok`, `value`, and (on failure)
`error` from the response. A data request without its granted permission is
rejected; Sparkle's host panel asks for permission before retrying it.

Sparkle replies to the same frame:

~~~~js
window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  if (event.data?.type === "sparkle-plugin-context") {
    // context is { view: "list" | "detail", project_id?: number }
    return;
  }
  if (event.data?.type !== "sparkle-plugin-response") return;
  // event.data contains requestId, ok, and (for storage.get) value.
});
~~~~

The storage bridge works only when storage is declared, granted, and the plugin
is enabled. Values are isolated by plugin ID and limited to 2 MB.

### API v3 data boundary

Clip and project access is intentionally narrower than the host's own routes:

- A plugin never receives a database handle, SQL, arbitrary filesystem path, or
  network capability. It sees only the JSON returned by the methods above.
- `clips.read` and `projects.read` are separate. Reading a project's metadata
  does not implicitly grant access to its clips; a plugin must request both
  permissions when it needs both.
- `clips.write` creates web clips and edits supported metadata. Local-file clip
  creation is not available to plugins. When a new clip needs a title or
  thumbnail, Sparkle may fetch public-site metadata with its existing URL
  validation. Editing project associations also requires `projects.write`.
- `projects.write` supports project creation and name/description edits. The
  completion-state cascade is not exposed to plugins.
- `clips.delete` follows Sparkle's normal clip lifecycle. Deleting a copied
  local-file clip may remove the owned copied file; plugins cannot browse or
  select arbitrary local files.
- `projects.delete` removes the project grouping and links while preserving
  the underlying clips, notes, and tasks. It also removes project-owned AI
  history and proposals, as Sparkle does for a normal project deletion.
- Plugin removal deletes the plugin package and its grants, but does not undo
  changes already made to the user's clips or projects. Those are Sparkle data,
  so the user should review write/delete permissions before granting them.

Example API v3 manifest:

~~~~json
{
  "id": "clip-reviewer",
  "name": "Clip Reviewer",
  "version": "1.0.0",
  "api_version": 3,
  "type": "feature",
  "description": "Reviews web clips in an isolated panel.",
  "permissions": ["clips.read", "projects.read", "storage"]
}
~~~~

## API v2/v3 declarative UI contributions

UI contributions are available only to `type: "feature"` plugins on an API v2
or v3 host. They are active only while the plugin is enabled and the
`ui.customize` permission is granted. Disabling or removing the plugin removes
its sidebar entry, restores hidden UI, and restores the previous order and
styles. Existing host behavior, APIs, and data remain enabled; `hide` changes
presentation only.

Declare the UI permission and contributions in `manifest.json`:

~~~~json
{
  "id": "tetris-tool",
  "name": "Tetris Tool",
  "version": "1.0.0",
  "api_version": 2,
  "type": "feature",
  "description": "A small game in a Sparkle panel and sidebar entry.",
  "permissions": ["ui.customize"],
  "priority": 100,
  "contributes": {
    "sidebar": { "label": "テトリス", "icon": "game" },
    "project_action": { "label": "分析", "icon": "sparkles" },
    "ui": {
      "hide": ["home.sort"],
      "order": {
        "sidebar.primary": ["home", "memo", "projects", "plugin:tetris-tool"],
        "settings.categories": ["general", "theme", "connections", "ai", "advanced", "plugins"]
      },
      "styles": {
        "home.search": { "accent": "#88C0D0", "radius": "14px" }
      }
    }
  }
}
~~~~

### Sidebar entry

`contributes.sidebar` is one object, not an array. `label` is the visible
accessible name. `icon` must be one of these portable icon keys:

`home`, `tasks`, `projects`, `puzzle`, `game`, `star`, `sparkles`, `book`,
`calendar`, `calculator`, `settings`.

The entry is inserted into the primary left sidebar. Clicking it opens the
plugin's existing sandboxed `panel.html`. The fixed profile and settings
controls remain at the bottom and cannot be moved or removed by a plugin.

### Project action

`contributes.project_action` is one object with a visible `label` and an
allowlisted `icon`. Sparkle displays its button in the project list and project
detail header. Clicking it opens the plugin's isolated `panel.html` and sends a
`sparkle-plugin-context` message with `view: "list"` or `view: "detail"`; the
detail view also includes the selected `project_id`. This context contains no
project content. Reading or changing project data still requires the matching
permission and the data methods above.

### Hide targets

`contributes.ui.hide` accepts only these stable IDs:

- Sidebar: `sidebar.home`, `sidebar.memo`, `sidebar.projects`,
  `sidebar.profile`.
- Home: `home.search`, `home.sort`, `home.categories`, `home.clips`.
- Notes: `notes.status-tabs`, `notes.task-list`, `notes.memo-list`,
  `notes.new-note`.
- Projects: `projects.list`, `projects.create`.
- Profile: `profile.details`, `profile.picks`.
- Settings: `settings.category.general`, `settings.category.theme`,
  `settings.category.connections`, `settings.category.ai`,
  `settings.category.advanced`.

`sidebar.settings` and `settings.category.plugins` are protected and cannot be
hidden. Unknown IDs are rejected; a plugin cannot use a selector, arbitrary
HTML, or a script to hide other elements.

### Order targets

`contributes.ui.order` accepts these targets:

- `sidebar.primary`: an array containing only `home`, `memo`, `projects`, and
  `plugin:<plugin-id>`. The profile and settings entries stay fixed at the
  bottom.
- `settings.categories`: an array containing only `general`, `theme`,
  `connections`, `ai`, `advanced`, and `plugins`.

An order contribution reorders known entries; it cannot create a second copy of
an entry or move protected profile/settings controls. Missing entries retain
their host default position.

### Style targets and properties

`contributes.ui.styles` is an object keyed by the same allowlisted hide IDs.
Each value may specify only presentation properties supported by the host,
including color, background, border, margin, padding, width, height, radius,
font size, and opacity. Values must be simple CSS color, length, percentage, or
number forms accepted by the host. CSS text, selectors, `url()`, expressions,
animations, and JavaScript are not accepted. Styles apply only to the named
stable UI ID and are removed when the plugin is disabled.

### Contribution conflicts

`priority` is optional and must be an integer from 0 through 1000 (default 0).
The host applies contributions from lower to higher priority; equal priorities
are ordered by plugin ID ascending. Hide targets are combined as a union. When
plugins provide the same style or order value, the later contribution wins.

## Existing Sparkle features and limits

API v1 supports theme tokens and isolated feature panels. API v2 adds the
declarative UI contributions above. API v3 additionally adds the explicitly
permissioned clip/project JSON bridge. No version permits replacing or
monkey-patching existing Sparkle behavior. UI contributions can hide controls,
reorder the documented lists, and add the plugin's own sidebar or project
action buttons, but they cannot disable the underlying feature, access the
host DOM, database, filesystem, or network, or change another plugin's package.
