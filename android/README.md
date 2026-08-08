# Sparkle Android client

This module is a PC-connected client for Sparkle. The Windows app remains the
only owner of the clip database; this app keeps only the configured PC API URL,
the current in-memory response data, and the current file/share selection.
Thumbnail bytes use a bounded Android memory cache and OS-managed cache
directory; they are not a copy of the PC database.

## Connection

1. Start Sparkle on the PC.
2. Publish the localhost API through the user's existing Tailscale Serve setup.
3. In the app, enter the resulting HTTPS MagicDNS URL under **PC接続設定**.

The client intentionally accepts HTTPS URLs only. It uses the existing
`/health`, `/clips`, `/categories`, `/tags`, `/tasks`, `/notes`, and `/projects`
endpoints. URL clips use `POST /clips` and `PUT /clips/{id}`; phone file
selection and Android Sharesheet files use the existing multipart
`POST /clips/local` endpoint. Remote thumbnails use the existing
`/thumbnail-proxy` endpoint when needed.

## Android behavior

- The left drawer contains **ホーム**, **タスク・メモ**, **プロジェクト**, and
  **PC接続設定**.
- Home shows the desktop-style category row, searchable clip metadata,
  clickable tag chips, thumbnails, and a responsive two-to-four-column grid.
- The attach button selects a phone file. The Android Sharesheet can send a URL
  or file to Sparkle; the app opens the save form so comments and tags can be
  added before saving through the PC API.
- Tasks and notes are loaded from the PC; tapping a note opens its edit form.
  Project details include a PC-backed edit form.
- The app refreshes when it returns to the foreground and periodically while
  active, so PC-side edits appear without pressing the refresh button.
- Thumbnails are cached in memory (12 MiB LRU) and the Android cache directory
  (64 MiB limit, 8 MiB per entry) to reduce first-render lag without unbounded
  storage growth.

## Build

Open this `android` directory in Android Studio, let it install the configured
Gradle/SDK components, and run the `:app:assembleDebug` task from the Gradle
tool window. From PowerShell, the project wrapper can also run:

```text
.\gradlew.bat :app:assembleDebug
```

The standalone debug APK is written to:

```text
app\build\outputs\apk\debug\app-debug.apk
```
