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

- The left drawer contains **ホーム**, **タスク・メモ**, **プロジェクト**,
  **アプリ設定**, and **PC接続設定**. App settings are limited to task and
  project behavior and are saved to the PC's existing settings store so the
  desktop app and Android use the same values.
- Home shows the desktop-style category row, searchable clip metadata,
  clickable tag chips, thumbnails, and a responsive two-to-four-column
  Masonry grid that packs cards by their measured height.
  Long-pressing a category opens a confirmation dialog for deleting that
  category through the PC API.
- Home can filter to favorites and sort clips by newest, title, recently
  opened, or a stable random order. Long-pressing a clip offers favorite and
  delete actions; both operations are sent to the PC API.
- The attach button selects a phone file. The Android Sharesheet can send a URL
  or file to Sparkle; the app opens the save form so comments and tags can be
  added before saving through the PC API.
- Tasks and notes are loaded from the PC. Each tab has All/In-progress/
  Completed filters; the add button opens a PC-backed form, tapping edits an
  item, long-pressing deletes it, and task/note forms can manage their links.
  Task due dates are selected with the native Material calendar instead of
  free-form text. Projects have the same status filters, a new/edit form, and
  separate, equally sized link buttons for clips, tasks, and notes. Long-
  pressing a project opens its delete confirmation. A full reload starts both
  screens on **進行中**; silent background refreshes preserve the user's
  selected filter.
- The app refreshes when it returns to the foreground and polls the PC every
  two seconds while active. These background refreshes are silent, so PC-side
  edits appear without pressing the refresh button or interrupting an editor.
- Home keeps the desktop-style spacing and controls, uses a packed Masonry
  layout, and scrolls back to the top when the sort mode changes. Project
  cards show a small preview stack of attached clip thumbnails. The highest
  priority unfinished task is sorted first and highlighted with a border.
- When a URL clip is saved, YouTube URLs use the video's `hqdefault.jpg`
  thumbnail. Other pages use `og:image`/Twitter image metadata when available,
  then a page favicon fallback. The image URL is stored in the PC clip record;
  the Android client does not take screenshots or create a local database copy.
- Thumbnails are cached in memory (12 MiB LRU) and the Android cache directory
  (64 MiB limit, 8 MiB per entry) to reduce first-render lag without unbounded
  storage growth.
- Local clips stay on the PC and are retrieved through `GET
  /clips/{id}/file`; the Android client never requests the PC filesystem path.
  Image, text, and video files can be previewed in the detail screen. Other
  file types are streamed into a bounded temporary cache and opened through an
  Android `FileProvider` when a compatible app is installed. Folders are shown
  as unavailable for preview/download.
- The download action saves files to the public `Downloads/Sparkle` directory
  on Android 10 and later. Older supported Android versions use the app's
  `Downloads/Sparkle` directory because the project intentionally avoids broad
  storage permissions. Temporary full-file preview data is capped at 128 MiB;
  it is cache data, not a local copy of the PC clip database.
- The launcher and round icon use the repository root `Icon.png` unchanged.

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
