---
name: sparkle-plugin-author
description: Create, review, package, or update portable plugins for the Sparkle desktop app. Use when the user asks to add a Sparkle theme or an isolated feature panel.
compatibility: Works across operating systems. Use paths relative to the plugin package and discover user folders from standard environment variables.
---

# Sparkle plugin author

Create Sparkle plugins without editing or replacing Sparkle's core application files.

## Start with the plugin boundary

1. Ask what the plugin should do and whether it is a theme or a feature panel.
2. Use the versioned package format in references/plugin-format.md. Choose API v2
   when the plugin needs declarative UI contributions. Choose API v3 when it
   needs the permissioned Sparkle clip or project data bridge.
3. Make changes only inside a new plugin package directory. Do not edit Sparkle's source, app database, or another plugin.
4. Use paths relative to the plugin package. Never put a user name, drive letter, machine-specific folder, credential, API key, or absolute local path in a plugin, script, test, or README.
5. For API v2/v3 UI contributions, use only the allowlisted `contributes` fields
   and stable UI IDs in references/plugin-format.md. Do not inject CSS or JS,
   query the host DOM, or depend on a page's private markup.
6. If a request needs an integration point that the documented plugin API does not provide, explain the missing extension point and propose adding it to Sparkle's public plugin API. Do not work around the limit by patching the app.

## Build and review

- Keep theme plugins declarative: only edit the approved color tokens in theme.json.
- Keep feature code inside panel.html and files packaged beside it. The panel runs in an isolated frame and has no direct access to Sparkle's DOM, database, filesystem, or network.
- Keep API v2/v3 UI contributions declarative. A feature plugin may add its own
  sidebar entry, hide allowlisted host UI, reorder allowlisted navigation, and
  apply allowlisted style properties only through `manifest.json`.
- Treat host UI changes as reversible presentation changes. They may hide an
  existing control, but must not disable its underlying behavior, API, or data.
- Use a unique plugin ID and a declared priority when multiple plugins make UI
  contributions. Do not assume that a contribution from another plugin exists.
- Use the parent-window message bridge only for the documented notify, storage,
  clip, and project methods. Request each data permission only when the plugin
  needs that operation. Sparkle asks the user on first use and stores the
  decision per plugin; the Settings plugin manager can revoke every grant.
- Do not ask for broad file, shell, network, or database access. Clip/project
  data access is limited to the allowlisted API and never exposes a raw DB
  connection, host filesystem, or arbitrary network access.
- Validate the manifest and every relative asset path. Reject secrets, machine-specific absolute paths, and files that are not needed.
- Preserve the user's existing files and unrelated work. Do not install the plugin or modify the user's Sparkle installation while authoring it.
- Make the ZIP with manifest.json at the archive root. Keep a copy of the unpacked package so it can be reviewed.
- Report the package type, its capabilities, compatibility, files changed, and how the user can import the ZIP. Separate checks actually run from checks not run.
- Report API v2/v3 contributions explicitly, including the sidebar label/icon,
  hidden UI IDs, ordering targets, styles, and priority. Also state which
  behavior is restored when the plugin is disabled or removed. List every
  requested data permission and explain what the plugin does with the data.

## Portability rules

- Use Path.home(), os.path.expanduser, or the relevant environment variable when code truly needs a user directory. Respect CODEX_HOME, XDG_CONFIG_HOME, CLAUDE_CONFIG_DIR, and HOME where applicable.
- Use pathlib or URL-relative references instead of concatenating operating-system-specific separators.
- Do not put a machine's runtime plugin directory in the plugin package. Sparkle chooses that directory for the current installation.
- Keep SKILL.md, examples, scripts, and the generated plugin independent of a specific terminal, shell, operating system, or user account.
