![Logo](Icon.png)

# Sparkle

A local Windows application that brings your web clips, notes, tasks, and projects together in one place.

Save interesting web pages through the Chrome extension and organize them with comments, tags, and categories. All saved data is stored locally in a SQLite database on your PC, so no external cloud service is required.

> [!NOTE]
> Sparkle is currently under development. You may encounter bugs, and features or data formats may change in future versions.
> 
> **Currently, Sparkle is available in Japanese only.**

<!-- Remove the comment markers after adding a screenshot. -->

<!-- ![Sparkle home screen](docs/images/sparkle-home.png) -->

## Features

* Save web pages through the Chrome extension
* Organize clips with comments, tags, and categories
* Manage clips, notes, tasks, and projects in one place
* Search by keyword, mark items as favorites, and sort your content
* Run Sparkle from the Windows system tray
* Store all data locally on your PC
* Automatically export data as Markdown for use with AI tools

## What Makes Sparkle Different

### Local Data Storage

The database and uploaded files are stored in the following folder:

```text
%APPDATA%\Sparkle
```

Because your data is stored separately from the application itself, it remains available when Sparkle is updated or replaced.

### Integration with AI Tools

Clips, notes, tasks, and projects stored in Sparkle are automatically exported as Markdown files that are easy for AI tools to read.

```text
%USERPROFILE%\Documents\Sparkle\ai-export\
```

This folder can be used as a reference source in tools such as Claude Code and Codex. You can also upload the exported Markdown files to ChatGPT, Gemini, Claude, and other AI tools.

## System Requirements

* Windows 10 or Windows 11
* Microsoft Edge WebView2 Runtime
* Chrome or another Chromium-based browser when using the browser extension

## Installation and Usage

### Running from Source

Python 3.10 or later is required.

```powershell
git clone https://github.com/aaa-927418924/Sparkle.git
cd Sparkle

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python app_entry.py
```

You can also start Sparkle by double-clicking `start.bat`.

If `dist\Sparkle.exe` exists, the executable version will be launched. Otherwise, Sparkle will be launched from the source code using the virtual environment.

---

### Optional Remote Web Access

The default remote connection remains the existing Tailscale tailnet mode. From
Sparkle's desktop Settings, you can choose one of two authenticated Web modes
for the dedicated mobile Web UI:

* **Funnel Web** is for browsers and phones that cannot install the Tailscale
  app. It is reachable through a public Tailscale Funnel URL, but the Sparkle
  Web gateway still requires the generated access key.
* **Tailscale Serve Web** is for phones and browsers that can connect to the
  same Tailscale tailnet. It is tailnet-only and also requires the Sparkle
  access key, so a device must pass both the Tailscale and Sparkle checks.

Both modes run on a separate local gateway and do not add a login screen to the
Sparkle desktop application itself.
* The first activation shows an access key once. Share it only with intended
  users.
* On the Web login screen, Trust this device stores an opaque browser session
  token for up to 365 days. The access key itself is not stored in the
  application data.
* Rotating the access key or revoking all trusted devices invalidates existing
  Web sessions.
* Sparkle must be running after a PC restart. Enable Sparkle's existing
  Windows startup option if the remote Web entry should be available
  automatically.

Funnel Web exposes the dedicated mobile Web UI through Tailscale Funnel on
HTTPS port `443`. Serve Web / Android uses Tailscale Serve on HTTPS port `443`
and proxies the main app inside the tailnet. Remote MCP is independent: it
always uses a separate Tailscale Funnel on HTTPS port `8443`, so Serve for
Android and Funnel for MCP can run at the same time. Sparkle displays both
routes in Settings.
See the [Tailscale Serve documentation](https://tailscale.com/docs/features/tailscale-serve)
and [Tailscale Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel)
for current service limitations and plan requirements.

### Running the Windows Executable

Download and run the latest Windows executable from the [GitHub Releases page](https://github.com/aaa-927418924/Sparkle/releases/latest).

## Installing the Chrome Extension

The Chrome extension must currently be installed manually in development mode.

1. Open `chrome://extensions/` in Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the `extension` folder inside the Sparkle repository.

After installation, you can save the web page you are currently viewing directly to Sparkle through the Chrome extension.

## License

Sparkle is licensed under the [MIT License](LICENSE).
