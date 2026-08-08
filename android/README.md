# Sparkle Android client

This module is a PC-connected client for Sparkle. The Windows app remains the
only owner of the clip database; this app keeps only the configured PC API URL
and the current in-memory response data.

## Connection

1. Start Sparkle on the PC.
2. Publish the localhost API through the user's existing Tailscale Serve setup.
3. In the app, enter the resulting HTTPS MagicDNS URL under **PC接続設定**.

The client intentionally accepts HTTPS URLs only. It uses the existing
`/health`, `/clips`, `/categories`, and `/tags` endpoints, plus `POST /clips`
and `PUT /clips/{id}` for the initial create/edit flow.

## Build

Open this `android` directory in Android Studio, let it install the configured
Gradle/SDK components, and run:

```powershell
gradlew.bat :app:assembleDebug
```

The standalone debug APK is written to:

```text
app\build\outputs\apk\debug\app-debug.apk
```
