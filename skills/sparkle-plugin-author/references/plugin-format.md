# Sparkle plugin package format

Sparkle accepts a ZIP whose root contains `manifest.json`. The ZIP is imported
disabled. Users must enable it in Sparkle Settings.

The current contracts are API v1, API v2, API v3, API v4, and API v5:

- API v1 supports theme tokens and isolated feature panels.
- API v2 supports everything in v1 and adds the declarative UI contributions
  described below. An API v2 host treats API v1 plugins as compatible.
- API v3 supports everything in v2 and adds the permissioned clip/project data
  bridge described below. An API v3 host treats API v1 and API v2 plugins as
  compatible.
- API v4 supports everything in v3 and adds permissioned note/task CRUD, calls
  to the AI provider configured in Sparkle, and host-mediated public HTTPS
  requests. An API v4 host treats API v1, v2, and v3 plugins as compatible.
- API v5 supports everything in v4 and adds per-plugin OAuth connections. Sparkle
  runs the PKCE browser flow, stores credentials in the Windows Credential
  Manager, and makes authenticated requests only to the connection's declared
  API origin. OAuth access and refresh tokens are never returned to plugin code.
- An API v5 host treats API v1, v2, v3, and v4 plugins as compatible.
- An API v1 or v2 host treats a newer API plugin as incompatible. It keeps the package
  and private data, leaves the plugin disabled, and allows the package to be
  exported for use with a compatible Sparkle release.

Set `api_version` to the lowest API version the plugin needs. Use API v2 for a
feature plugin that declares `contributes`, API v3 for clip/project data, and
API v4 for notes/tasks, configured AI, or public HTTPS requests, and API v5 for
OAuth connections. API v4 and v5 support the earlier UI and data APIs.

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
plugin-pages.css (optional; theme plugins only)
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
major.minor.patch. `api_version` is an integer, currently 1, 2, 3, 4, or 5.

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
    "accentSoft": "#314A5D",
    "sidebarText": "#EEF2FF",
    "sidebarTextActive": "#88C0D0",
    "projectCard": "#2B3550",
    "projectCardText": "#EEF2FF",
    "projectCardMuted": "#AAB4CF",
    "homeText": "#EEF2FF",
    "homeMuted": "#AAB4CF",
    "homeCard": "#2B3550"
  },
  "icons": {
    "sidebar": "light",
    "sidebarActive": "light"
  }
}
~~~~

Every color property is optional, but at least one is required. Values must be
hex colors or simple rgb() / rgba() values. Keep `theme.json` declarative. A
theme may optionally include a root-level `plugin-pages.css` to customize the
appearance of feature-plugin pages. Sparkle loads this stylesheet into every
feature panel while that theme is active; feature plugins do not need to add
theme-specific code. The stylesheet affects only the sandboxed panel document,
not Sparkle's host UI or other plugins.

`plugin-pages.css` may use normal selectors and the theme variables listed
below. It must not contain JavaScript, CSS escapes, `@import`, `url()`,
`@font-face`, or other external resources. Keep it at or below 256 KiB. Sparkle's
panel Content Security Policy also blocks outbound connections and external
images/fonts. Theme packages never receive data permissions through this file.

Global color keys are `background`, `surface`, `surfaceRaised`, `surfaceHover`,
`surfaceActive`, `sidebar`, `border`, `borderStrong`, `text`, `muted`, `accent`,
and `accentSoft`. The following optional component keys let a theme choose
colors for legacy page layouts independently:

| Area | Keys |
| --- | --- |
| Sidebar | `sidebarText`, `sidebarTextActive`, `sidebarHover`, `sidebarActive` |
| Project cards and details | `projectCard`, `projectCardText`, `projectCardMuted`, `projectDetailText` |
| Task panel | `taskPanel`, `taskText`, `taskMuted`, `taskAccent` |
| Memo cards | `memoCard`, `memoText`, `memoMuted` |
| Notes and tasks page | `notesBackground`, `notesSidebar`, `notesPanel`, `notesCard`, `notesText`, `notesMuted`, `notesBorder`, `notesAccent` |
| Home page | `homeBackground`, `homeSidebar`, `homeSurface`, `homeText`, `homeMuted`, `homeBorder`, `homeAccent`, `homeCard`, `homeActive`, `homeActionSurface`, `homeActionText`, `homeTagText`, `homeTagBorder`, `homeTagActive`, `homeTagActiveText` |
| Filter and category controls | `controlBackground`, `controlText`, `controlHoverBackground`, `controlHoverText`, `controlActiveBackground`, `controlActiveText` |
| Action buttons | `actionButtonBackground`, `actionButtonText`, `actionButtonBorder`, `actionButtonHoverBackground`, `actionButtonHoverText`, `actionButtonHoverBorder` |
| Checkboxes | `checkboxBackground`, `checkboxBorder`, `checkboxAccent` |

In `plugin-pages.css`, a color key such as `surfaceRaised` is available as
`var(--sparkle-theme-surface-raised)`. All color keys use the same
camelCase-to-kebab-case mapping. Icon modes are available as
`--sparkle-theme-sidebar-icon-filter`, `--sparkle-theme-sidebar-active-icon-filter`,
`--sparkle-theme-action-icon-filter`, `--sparkle-theme-action-active-icon-filter`,
and `--sparkle-theme-inline-icon-filter`. Sparkle also applies the theme's
background/text tokens to the panel body and its control tokens to common
buttons, pressed tabs, inputs, selects, textareas, and checkboxes automatically.
Theme CSS is loaded after the panel content so it can provide broader or more
specific rules for plugins that use custom components.

Every component key is optional. When omitted, that component keeps its normal
palette behavior. For light themes, set dark foreground colors for home cards,
project cards, task text, and sidebar labels wherever needed. Check the actual
foreground/background pairs and active states before exporting the ZIP.

The optional `icons` object supports `sidebar`, `sidebarActive`, `action`,
`actionActive`, and `inline` keys. Each accepts `source` (use the SVG's original
color), `dark` (black), or `light` (white). `sidebar` and `sidebarActive`
control navigation icons; `action` and `actionActive` control card/action
buttons; `inline` controls small metadata icons such as project counts. Set
these explicitly when the source color would disappear on the chosen surface.
Other values and fields are rejected.

## Feature panel plugin

Files:

~~~~text
manifest.json
panel.html
assets/...
~~~~

Set type to feature, include panel.html at the package root, and list only the
permissions the panel uses. Data and capability permissions are opt-in and
independent:

`panel_display` is optional for feature plugins. Omit it or set it to `dialog`
to open the panel in the existing modal. Set it to `page` to open the same
sandboxed `panel.html` in Sparkle's main content area, with a host-provided
Back button. The sidebar and window title bar remain available. This choice
does not require `ui.customize` and does not change the panel's permissions or
message bridge. Theme plugins must not set `panel_display`.

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
| `notes.read` | List and read note text, completion state, dates, and relationship IDs. Linked clip objects are omitted. |
| `notes.write` | Create or edit notes. Adding project/clip relationships also requires the matching project/clip write permission. |
| `notes.delete` | Delete notes through Sparkle's normal note lifecycle. |
| `tasks.read` | List and read task title, status, due date, priority, and relationship IDs. Linked clip objects are omitted. |
| `tasks.write` | Create or edit tasks. Adding project/clip relationships also requires the matching project/clip write permission. |
| `tasks.delete` | Delete tasks through Sparkle's normal task lifecycle. |
| `ai.request` | Send plugin-supplied prompts to the active AI provider configured in Sparkle and receive a response. Provider credentials stay in Sparkle. |
| `network.request` | Make bounded HTTPS requests to public hosts through Sparkle. Private/local addresses and redirects are not followed. |
| `auth.oauth` | Start PKCE OAuth connections, check/disconnect a plugin-owned connection, and make authenticated HTTPS requests to its fixed API origin. Tokens remain in Sparkle's credential store. |

API v3, v4, and v5 start with no permissions granted. Sparkle asks separately the first
time an operation needs each permission and stores the decision for that
plugin on that installation. `ui.customize` is requested when the user enables
the plugin. In Settings > Plugins, `権限を削除` revokes all grants for that
plugin; the next use asks again. API v1/v2 plugins retain their existing
manifest-based grants for compatibility until the user uses this revoke
action. Importing a plugin starts disabled.

The panel is loaded only after the user clicks its Open button. It runs in a
sandboxed frame with no direct Sparkle DOM access or direct network access.
Local assets can be referenced relative to panel.html. API v4 network requests
go through Sparkle's parent bridge and require `network.request`. API v5 OAuth
requests use a separate `auth.oauth` permission and never expose bearer tokens.

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

Use a request ID to pair asynchronous responses. The sandboxed frame has an
opaque origin, so validate `event.source` against `window.parent`:

~~~~js
const pending = new Map();

window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  const message = event.data;
  if (message?.type !== "sparkle-plugin-response") return;
  const request = pending.get(message.requestId);
  if (!request) return;
  pending.delete(message.requestId);
  if (message.ok) request.resolve(message.value);
  else request.reject(new Error(message.error || "Sparkle request failed"));
});

function sparkleRequest(method, values = {}) {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    window.parent.postMessage(
      { type: "sparkle-plugin-request", requestId, method, ...values },
      "*"
    );
  });
}

const { response } = await sparkleRequest("ai.generate", {
  system_prompt: "Answer briefly.",
  prompt: "Summarize the data I collected.",
});
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
- notes.list: list notes; optional `filters` contains `project_id` or `exclude_project`.
- notes.get: read one note by numeric `id`.
- notes.create: create a note with a JSON `payload`.
- notes.update: update a note by numeric `id` with a JSON `payload`.
- notes.delete: delete a note by numeric `id`.
- tasks.list: list tasks; optional `filters` contains `done`, `project_id`, or `exclude_project`.
- tasks.get: read one task by numeric `id`.
- tasks.create: create a task with a JSON `payload`.
- tasks.update: update a task by numeric `id` with a JSON `payload`.
- tasks.delete: delete a task by numeric `id`.
- ai.generate: send `{ system_prompt?, prompt }` to the active configured AI provider. The result contains `response`, `provider`, and `model`.
- network.request: send `{ url, requestMethod?, headers?, body? }` to a public HTTPS URL on port 443. The result contains `status`, a small response header set, and text `body`.
- oauth.connect: send `{ connection: OAuthConnection }` to start a browser-based authorization code + PKCE connection. It returns status only; tokens are not returned.
- oauth.status: send `{ connection_id }` to read whether the plugin-owned connection is pending or connected.
- oauth.disconnect: send `{ connection_id }` to delete the connection's locally stored tokens.
- oauth.request: send `{ connection_id, url, requestMethod?, headers?, body? }` to make an authenticated HTTPS request. `url` must use the connection's declared `api_origin`; Sparkle injects the bearer token and refreshes it when supported.

An OAuth connection config contains `connection_id`, `name`, `authorization_url`,
`token_url`, `client_id`, `scopes`, and `api_origin`. Optional fields include
`resource`, `issuer`, `jwks_url`, `agent_name_hint`, `authorization_params`, and
`token_params`. Set `reauthorize: true` on `oauth.connect` after refresh fails to
start a new browser flow while retaining the issued OAuth client ID. The
`agent_name_hint` defaults to `Sparkle`; dynamic client
registration sends it only with the initial registration request. Sparkle keeps
a stable host ID for that plugin across disconnects and permission re-grants.
OAuth endpoints and API origins must be public HTTPS hosts on port 443. Redirects,
loopback/private destinations, client secrets, and token access from plugin code
are not supported. If the provider returns an ID token, it is validated when
`issuer` and `jwks_url` are provided; requesting the `openid` scope requires both.
Authenticated requests return the complete response body, up to 1 MB. For SSE,
the bridge waits for the response to finish and returns the event stream text; it
does not forward events to the plugin incrementally.

For the open-source Sign in with ChatGPT flow that can authorize eligible
ChatGPT-plan Responses API usage, use the plugin-owned connection below. This is
separate from Sparkle's AI provider selector and from the user's local Codex CLI
or Codex app session:

~~~~js
const connection = {
  connection_id: "codex-plan",
  name: "Codex subscription",
  authorization_url: "https://auth.openai.com/api/accounts/authorize",
  token_url: "https://auth.openai.com/api/accounts/oauth/token",
  client_id: "dynamic_agent_client",
  dynamic_registration: true,
  agent_name_hint: "Sparkle",
  scopes: ["openid", "profile", "email", "offline_access", "resource.invoke", "chatgpt.tokens.use.direct"],
  resource: "https://api.openai.com/v1",
  api_origin: "https://api.openai.com",
  issuer: "https://auth.openai.com",
  jwks_url: "https://auth.openai.com/.well-known/jwks.json",
};

await sparkleRequest("oauth.connect", { connection });
const result = await sparkleRequest("oauth.request", {
  connection_id: "codex-plan",
  url: "https://api.openai.com/v1/responses",
  requestMethod: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ model: "gpt-6.1-sol", input: "Hello", store: false, stream: true }),
});
~~~~

The plugin supplies the UI, prompt, model choice, and response parsing. Check
`oauth.status.scopes` for `chatgpt.tokens.use.direct` before offering plan-based
inference. For streamed Responses API output, parse the returned SSE text after
the request completes. Sparkle owns the browser callback, PKCE/state/nonce
checks, secure token storage, refresh, and API-origin restriction. The plugin
must explain what data its request sends to the external provider.

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
  if (event.data?.type === "sparkle-plugin-theme") {
    // theme is null or { id, name?, colors, icons? }; values are allowlisted.
    // Apply the colors and icon modes to this panel's own elements.
    return;
  }
  if (event.data?.type !== "sparkle-plugin-response") return;
  // event.data contains requestId, ok, and (for storage.get) value.
});
~~~~

Sparkle sends `sparkle-plugin-theme` after the panel loads and whenever the
active plugin theme changes. The payload contains only the active theme's ID,
optional name, validated color tokens, and allowlisted icon modes; it never
contains host markup or data permissions. A `null` theme means no plugin theme
is active. Sparkle automatically applies the validated colors to common panel
elements and loads the active theme's optional `plugin-pages.css`. The panel may
still handle the message to style custom behavior in its own document, without
querying the Sparkle page.

The storage bridge works only when storage is declared, granted, and the plugin
is enabled. Values are isolated by plugin ID and limited to 2 MB.

### API v3/v4 data boundary

Clip and project access is intentionally narrower than the host's own routes:

- A plugin never receives a database handle, SQL, or arbitrary filesystem
  path. It sees only the JSON returned by the methods above.
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
- `notes.read` and `tasks.read` do not grant clip content access. Returned
  records omit linked clip objects; use the separate clip API and permission
  if that content is needed.
- `notes.write` and `tasks.write` do not bypass project or clip permissions
  when changing those relationships. Deletes are separate permissions and
  changes to Sparkle data remain after the plugin is removed.
- `ai.request` uses the active provider selected in Sparkle Settings and does
  not give the plugin its API key. The plugin controls the prompt, so any
  Sparkle data it includes is sent to that provider. Sparkle has no built-in
  Sign in with ChatGPT provider and does not expose the local Codex CLI or app
  session. A plugin that implements an external OAuth
  integration uses its own `auth.oauth` connection; Sparkle retains the tokens
  and the plugin chooses how to use the authenticated response.
- `network.request` supports public HTTPS on port 443 only, limits request and
  response sizes, blocks private/local addresses, and does not follow redirects.
  It is not a general-purpose proxy for Sparkle's local server or local network.
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
  "panel_display": "page",
  "permissions": ["clips.read", "projects.read", "storage"]
}
~~~~

## API v2/v3/v4 declarative UI contributions

UI contributions are available only to `type: "feature"` plugins on an API v2
or newer host. They are active only while the plugin is enabled and the
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
  "panel_display": "page",
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
permissioned clip/project JSON bridge. API v4 adds note/task CRUD, configured
AI calls, and permissioned HTTPS requests through Sparkle. API v5 adds OAuth
connections and authenticated requests bound to a single API origin. No version permits replacing or
monkey-patching existing Sparkle behavior. UI contributions can hide controls,
reorder the documented lists, and add the plugin's own sidebar or project
action buttons, but they cannot disable the underlying feature, access the
host DOM, database, or filesystem, or change another plugin's package. Plugins
have no direct network access; API v4's network bridge and API v5's authenticated
request bridge are limited to public HTTPS destinations and are permission-gated.
