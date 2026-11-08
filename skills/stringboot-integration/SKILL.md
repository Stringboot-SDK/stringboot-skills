---
name: stringboot-integration
description: Integrate the Stringboot SDK (remote-managed strings, FAQs and copy A/B tests) into Android, iOS/macOS and web apps (React, Next.js, Vue, vanilla JS), and migrate an app's existing strings (strings.xml, Localizable.strings, String Catalogs, i18next/react-intl/vue-i18n JSON) into Stringboot. Use this whenever the user mentions Stringboot, a Stringboot Client Token (sb_...), @stringboot/web-sdk, com.stringboot:stringboot-android-sdk or StringbootSDK, or wants to move their app's text, translations or localization files to Stringboot, update copy without app releases via Stringboot, or upgrade from an older Stringboot SDK, even if they don't say "integrate".
---

# Stringboot integration

Stringboot serves an App's strings, FAQs and running copy experiments to apps from one downloaded **Catalog** per language. The SDK stores it on the device and serves it offline-first. Edits in the dashboard reach running apps within about two minutes. There is no push.

Current SDKs (use these or later):

| Platform | Package | Minimum |
| :--- | :--- | :--- |
| Android | `com.stringboot:stringboot-android-sdk:2.1.0` (Maven Central) | Android 7.0 (API 24), Kotlin 1.9 |
| iOS / macOS | Swift package `https://github.com/Stringboot-SDK/stringboot-ios-sdk`, from `3.0.1`, product `StringbootSDK` | iOS 15 / macOS 12, Xcode 27 |
| Web | `@stringboot/web-sdk@^3.0.1` (npm) | Chrome 87+, Firefox 78+, Safari 14+, Edge 88+; Node 18+ for SSR |

Older SDKs (Android 1.x, iOS 1.x/2.x, Web 2.x) no longer receive updates: Stringboot answers them with `426 Upgrade Required`. If you find one, upgrade it as part of the job.

React Native, Flutter and other cross-platform runtimes aren't supported. Say so instead of improvising.

## Before you start

Ask the user for what you can't find in the project. Don't invent values:

1. **Client Token** (starts with `sb_`). It's created in the Stringboot dashboard (API Tokens → New Token → type Client Token) and shown only once. It's public by design, so it may live in client config, but keep it out of logs. Any other token type (for example a Figma Plugin Token) is rejected with `401`.
2. **The App's languages and default language.** The default is the first language activated in the dashboard. Language codes must match exactly what the app requests (`pt-BR` is not `pt`).
3. **Which targets to integrate**, when the repo has several (app module, extension, web package).

Work in a clean git state, so the user can review the diff. Run the project's build or tests after each platform.

## Workflow

### 1. Inspect the project

Find the platforms and how strings are handled today:

- **Android:** `build.gradle(.kts)` files, `res/values*/strings.xml`, `getString(R.string.*)`, `@string/` in layouts, `stringResource(` in Compose, `isShrinkResources`.
- **iOS:** `*.xcodeproj` / `Package.swift`, `*.lproj/Localizable.strings`, `*.xcstrings`, `NSLocalizedString(`, `String(localized:`, SwiftUI `Text("…")` with literal keys.
- **Web:** `package.json` (framework, any i18n library: i18next, react-intl, vue-i18n, next-intl), locale JSON folders, SSR (Next.js).
- **Existing Stringboot:** the SDK version, if any. Anything older than the table above needs the upgrade steps in the platform reference.

Tell the user what you found and what you plan to change before large edits.

### 2. Install and initialize the SDK

Read the platform reference and follow it:

- Android: [references/android.md](references/android.md)
- iOS / macOS: [references/ios.md](references/ios.md)
- Web (vanilla, React, Next.js, Vue): [references/web.md](references/web.md)

Initialize once, at app start-up. Prefer the reactive APIs (Android `getFlow` / `TextView.stringboot()` / tags; iOS `SBText` / `@StringbootString` / `publisher`; web `useString` / `watch`). They show the first sync and live edits without a restart, while one-shot reads don't update.

### 3. Migrate existing strings (if the app has any)

Follow [references/migration.md](references/migration.md). In short:

1. Run `scripts/extract_strings.py` on the project's string files. It writes the bulk-upload files (50 rows each), a key map, an Android keep file and a report.
2. Review `report.md` with the user: conflicts, items kept local, and values to check.
3. Have the user upload the files in order in the dashboard (Strings → Bulk Upload). There's no API or CLI for this, so you can't upload them for them.
4. Rename keys in local files (`--rename-local`), then rewrite call sites to read through the SDK, using `key-map.json`.
5. Keep the local resource files. They're the SDK's offline fallback on Android and iOS.

### 4. Verify

Check each item and report the results to the user:

- [ ] The project builds (Android release build with minify and shrink if the app uses them; iOS Release; web production build and SSR if used).
- [ ] The Client Token starts with `sb_` and isn't logged.
- [ ] A fresh install or first visit online shows real strings, not `??key??`.
- [ ] Offline after the first sync, strings still show.
- [ ] Android with `isShrinkResources = true`: `res/raw/keep.xml` keeps every string read by name (see the Android reference).
- [ ] Every key the code reads exists in the upload file or the dashboard, in the App's default language at least.
- [ ] Multi-line values render: web elements use `white-space: pre-line`.

Tell the user which checks you couldn't run (for example, a device test) instead of claiming them.

## Rules that apply everywhere

- **Lookup order:** experiment variant → selected language → the App's default language → local resources (Android `strings.xml`, iOS `Localizable` table; web has none) → `??key??`. `??key??` on screen means the key is missing from all of these.
- **Keys:** use lower snake_case, `[a-z0-9_]`, starting with a letter. Stringboot accepts `[A-Za-z0-9_.-]`, 1–255 characters, case-sensitive. But Android resource names can't contain dots or hyphens, or start with digits, and the Android/iOS fallbacks look up the local resource by the **same** key. So a key must be identical in Stringboot and in the local files.
- **Values** are 1–10,000 characters and can't be blank.
- **No formatting in the SDKs:** they return the stored text. The app formats it. For values shared by all platforms, use named placeholders like `{name}` and a tiny replace helper (in each platform reference). printf values (`%1$s` on Android, `%@` on iOS) can't be shared across platforms, so keep those keys platform-specific.
- **Escapes:** the SDKs turn `\n`, `\t`, `\r`, `\"`, `\'`, `\\` in values into the characters. FAQ text is Markdown and isn't unescaped.
- **Not supported by Stringboot, keep local:** plurals (Android `<plurals>`, `.stringsdict`, String Catalog variations, ICU plural/select), string arrays, HTML or styled strings, non-translatable constants, `InfoPlist.strings`. To manage a plural remotely, split it into keys such as `items_one` / `items_other` and pick one in code.
- **Errors:** a rejected token (`401`) stops syncing but keeps showing stored strings. Offline and server errors retry by themselves. Never block app start-up on Stringboot.
- **Experiments** are bucketed on the device. Stringboot records nothing. Report assignments and exposures to the app's own analytics if the user wants them, and handle the empty assignments callback (experiments stopped).
- **Don't** wrap Android `get()` in `runBlocking` on the main thread, poll faster than every 60 seconds, put large blobs in values, or send the token in a header (the SDKs handle transport).

## Documentation

Public docs: https://docs.stringboot.com (Quickstart, per-SDK guides, Core Concepts, Dashboard guides). Link the user to the relevant page when you explain a choice.
