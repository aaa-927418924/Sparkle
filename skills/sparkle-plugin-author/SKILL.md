---
name: sparkle-plugin-author
description: Create only ZIP-importable plugins for Sparkle. Never modify or build Sparkle itself.
---

# Sparkle plugin author

Create only portable plugins that Sparkle can import from a ZIP with `manifest.json` at the archive root. The ZIP plugin is the deliverable; keep its unpacked package only as a reviewable source copy.

## Non-negotiable scope

- Do not modify, patch, build, repackage, or replace Sparkle itself. Do not edit Sparkle source, frontend/backend files, its database, installed application files, or another plugin. Do not run Sparkle application build scripts such as `build_exe.bat`.
- Keep every implementation change inside the new plugin package. Any asset compilation must also write only into that package. The final distributable must be an importable plugin ZIP, never a modified Sparkle executable or installer.
- Use only the documented plugin API. If the requested behavior needs an API, permission, event, or host integration that plugins do not have, do not start implementing a workaround or edit the app.
- Before implementation, honestly identify what cannot be done with the current plugin API and why. Offer practical alternatives with their limitations, then wait for the user's choice or explicit approval. If the user chooses a plugin-compatible alternative, implement that choice as a ZIP plugin. If they request a Sparkle core/API change, treat it as a separate, explicitly authorized task outside this plugin-only workflow; never bundle core changes into a plugin task.

## Start with the plugin boundary

1. Ask what the plugin should do and whether it is a theme or a feature panel.
2. Use the versioned package format in references/plugin-format.md. Choose API v2
   when the plugin needs declarative UI contributions, API v3 for clip/project
   data, API v4 for notes/tasks, configured AI, or public HTTPS requests, and
   API v5 for host-mediated OAuth connections.
3. Make changes only inside a new plugin package directory. Do not edit Sparkle's source, app database, or another plugin.
4. Use paths relative to the plugin package. Never put a user name, drive letter, machine-specific folder, credential, API key, or absolute local path in a plugin, script, test, or README.
5. For API v2/v3/v4/v5 UI contributions, use only the allowlisted `contributes` fields
   and stable UI IDs in references/plugin-format.md. Feature plugins must not
   inject styles or scripts into Sparkle's host UI, query the host DOM, or depend
   on a page's private markup. Theme plugins may use the documented
   `plugin-pages.css` only to style sandboxed feature-panel documents.
6. If a request needs an integration point that the documented plugin API does not provide, follow the pre-implementation reporting rule above. Never work around the limit by patching the app.

## Implement and package the plugin ZIP

- Build or package only the plugin. Never build Sparkle itself.
- Keep `theme.json` declarative and use only its approved color tokens and icon modes. Sparkle automatically applies those tokens to common controls in every feature panel, so individual feature plugins do not need theme-specific code. A theme may add a root-level `plugin-pages.css` for broader styling across sandboxed panels; it cannot modify Sparkle's host UI or another plugin's code.
- Keep feature code inside panel.html and files packaged beside it. The panel runs in an isolated frame and has no direct access to Sparkle's DOM, database, filesystem, or direct network APIs.
- Sparkle applies the active theme's validated common colors to each feature panel and loads its optional `plugin-pages.css` automatically. A panel may also handle the sanitized `sparkle-plugin-theme` message at load and when the theme changes for plugin-specific behavior; `theme: null` means no plugin theme is active. This styling grants no data or network permission and does not expose host markup. See `references/plugin-format.md`.
- Choose the feature panel's host presentation with `panel_display`: `dialog` (the default) opens a modal, while `page` opens in the app's main content area with a host-provided Back button. Both modes use the same isolated `panel.html` and permission bridge.
- Keep API v2/v3/v4 UI contributions declarative. A feature plugin may add its own
  sidebar entry, hide allowlisted host UI, reorder allowlisted navigation, and
  apply allowlisted style properties only through `manifest.json`.
- Treat host UI changes as reversible presentation changes. They may hide an
  existing control, but must not disable its underlying behavior, API, or data.
- Use a unique plugin ID and a declared priority when multiple plugins make UI
  contributions. Do not assume that a contribution from another plugin exists.
- Use the parent-window message bridge only for the documented notify, storage,
  clip, project, note, task, AI, and network methods. Request each permission only when the plugin
  needs that operation. Sparkle asks the user on first use and stores the
  decision per plugin; the Settings plugin manager can revoke every grant.
- Do not ask for file, shell, or database access. Sparkle mediates AI calls and
  outbound requests; external network access is limited to public HTTPS hosts
  and never exposes a raw DB connection or host filesystem. Explain what data
  the plugin sends to an AI provider or network destination.
- Validate the manifest and every relative asset path. Reject secrets, machine-specific absolute paths, and files that are not needed.
- Preserve the user's existing files and unrelated work. Do not install the plugin or modify the user's Sparkle installation while authoring it.
- Make the ZIP with manifest.json at the archive root. Keep a copy of the unpacked package so it can be reviewed.
- Report the package type, its capabilities, compatibility, files changed, and how the user can import the ZIP. Separate checks actually run from checks not run.
- Report API v2/v3/v4 contributions explicitly, including the sidebar label/icon,
  hidden UI IDs, ordering targets, styles, and priority. Also state which
  behavior is restored when the plugin is disabled or removed. List every
  requested data permission and explain what the plugin does with the data.

## Theme contrast and component colors

Theme colors are selected by the plugin author. The host exposes global and
component-specific color tokens as CSS variables; it does not automatically
derive a light or dark palette. When changing global `text` and `surface`, also
review the sidebar, home cards, project cards and details, task panels, memo
cards, filter controls, action buttons, and checkboxes. Those views have
separate optional tokens because their layouts may not use only the global
palette. Use the full list and icon modes documented in
`references/plugin-format.md`.

Before packaging, calculate the contrast of each visible text/background pair
and check normal, active, hover, and completed states. Aim for at least 4.5:1
for regular text and 3:1 for large text and icons. Fix the selected values in
theme.json. For feature-panel components that need more than the common
automatic styling, use only the theme's optional `plugin-pages.css` and follow
the restricted resource rules in `references/plugin-format.md`.

## Portability rules

- Keep the skill and plugin package portable across operating systems. Use paths relative to the package; never assume a drive letter or user name.
- Use Path.home(), os.path.expanduser, or the relevant environment variable when code truly needs a user directory. Respect CODEX_HOME, XDG_CONFIG_HOME, CLAUDE_CONFIG_DIR, and HOME where applicable.
- Use pathlib or URL-relative references instead of concatenating operating-system-specific separators.
- Do not put a machine's runtime plugin directory in the plugin package. Sparkle chooses that directory for the current installation.
- Keep SKILL.md, examples, scripts, and the generated plugin independent of a specific terminal, shell, operating system, or user account.
