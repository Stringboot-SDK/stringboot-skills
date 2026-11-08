# iOS / macOS (SDK 3.0.1)

## Contents

1. Install
2. Initialize
3. Read strings
4. Converting existing code
5. Languages
6. Release builds, privacy and pinning
7. FAQs and experiments
8. Upgrading an older SDK
9. Troubleshooting

## 1. Install

Requirements: iOS 15 / macOS 12 deployment target, Xcode 27 or later (older Xcode can't read the binary's Swift interface). CocoaPods isn't supported.

**Xcode project:** File → Add Package Dependencies… → `https://github.com/Stringboot-SDK/stringboot-ios-sdk` → Up to Next Major Version from `3.0.1` → add the `StringbootSDK` product to the app target. Xcode embeds and signs the binary framework automatically.

**Package.swift:**

```swift
dependencies: [
    .package(url: "https://github.com/Stringboot-SDK/stringboot-ios-sdk", from: "3.0.1")
],
targets: [
    .target(name: "MyApp", dependencies: [
        .product(name: "StringbootSDK", package: "stringboot-ios-sdk")
    ])
]
```

If you edit an `.xcodeproj` by hand-merging `project.pbxproj`, stop and ask the user to add the package in Xcode instead. Editing package references in `pbxproj` by hand is error-prone.

## 2. Initialize

Once, at launch: in the SwiftUI `App` initializer or in `application(_:didFinishLaunchingWithOptions:)`.

```swift
import StringbootSDK

@main
struct MyApp: App {
    init() {
        StringProvider.shared.initialize(
            cacheSize: 1000,
            apiToken: "sb_YOUR_CLIENT_TOKEN",
            baseURL: "https://api.stringboot.com"
        )
        FAQProvider.shared.initialize(apiToken: "sb_YOUR_CLIENT_TOKEN")  // only if the app shows FAQs
        StringProvider.shared.startPeriodicSync()                         // checks every 60 s in the foreground
    }
    var body: some Scene { WindowGroup { ContentView() } }
}
```

Keep the token in one place (an `.xcconfig` value read from `Info.plist`, or a constant). With `autoSync: true` (the default), the SDK syncs at start-up, when returning to the foreground, and when the network comes back. `startPeriodicSync()` adds a check every 60 seconds while the app is open.

State for UI and debugging: `isReady`, `initializationError`, `lastSyncError` (cleared by the next successful check), `isTokenRejected`, `currentLanguage`, `defaultLanguage`.

## 3. Read strings

Every read follows: experiment variant → selected language → default language → the app bundle's `Localizable` table, **same key** → `??key??`.

| Where | Use | Updates live |
| :--- | :--- | :--- |
| SwiftUI view | `SBText("key")` | Yes |
| SwiftUI property | `@StringbootString("key") var title: String` | Yes |
| SwiftUI modifier | `Text("").stringboot("key")`: apply styling **after** it, because it replaces the view | Yes |
| UIKit (default) | `StringProvider.shared.publisher(for: "key")` (Combine) | Yes |
| UIKit shortcut | `SBLabel(key:)`, `SBButton(key:)`, `label.setStringboot(key:)` | Only via `StringbootLanguageNotifier` |
| Synchronous | `StringProvider.shared.getCached("key")` → `String?` (stored Catalogs incl. the default language; no bundle) | No |
| Async | `await StringProvider.shared.get("key")` | No |

**UIKit: use `publisher(for:)`.** It emits the stored value at once, then on every Catalog or language change:

```swift
StringProvider.shared.publisher(for: "welcome_message")
    .receive(on: DispatchQueue.main)
    .sink { [weak self] in self?.titleLabel.text = $0 }
    .store(in: &cancellables)
```

`SBLabel`, `SBButton` and `setStringboot` load once and then react **only** to `StringbootLanguageNotifier.shared.changeLanguage(to:)`. They don't update on new Catalogs (live edits, or the first download after a fresh install), nor on `setLocale` / `changeLanguage(to:)` / `StringbootLanguageManager.setLanguage`. Use them only on screens shown after the first sync, and switch languages through `StringbootLanguageNotifier` there. Also, `setStringboot` adds an observer on every call, so never call it in reused cells.

**Table and collection cells:** set `label.text = StringProvider.shared.getCached(key) ?? NSLocalizedString(key, comment: "")` in `cellForRow`, and reload visible rows when strings or the language change:

```swift
StringProvider.shared.$lastUpdate.map { _ in () }
    .merge(with: StringProvider.shared.$currentLanguage.map { _ in () })
    .receive(on: DispatchQueue.main)
    .sink { [weak self] in self?.tableView.reloadData() }
    .store(in: &cancellables)
```

**Named placeholders** (`{name}`), for values shared with Android and web:

```swift
extension String {
    func fill(_ args: [String: CustomStringConvertible]) -> String {
        args.reduce(self) { $0.replacingOccurrences(of: "{\($1.key)}", with: $1.value.description) }
    }
}
```

For printf values (`%@`, `%lld`), keep formatting in the app: `String(format: value, arg)`.

## 4. Converting existing code

Use `key-map.json` from the migration. Keep `Localizable.strings` / `Localizable.xcstrings` as the offline fallback, with keys renamed to the Stringboot keys (`--rename-local` does this).

| Before | After |
| :--- | :--- |
| `Text("welcome_message")` (a localized key) | `SBText("welcome_message")` |
| `Text("Welcome back!")` (English text as the key) | `SBText("welcome_back")` (the new key from key-map.json) |
| `Text(NSLocalizedString("x", comment: ""))` | `SBText("x")` |
| `label.text = NSLocalizedString("x", comment: "")` | A `publisher(for: "x")` subscription (or `setStringboot(key:)` on screens shown after the first sync) |
| `String(localized: "x")` / `NSLocalizedString` in logic | `StringProvider.shared.getCached("x") ?? NSLocalizedString("x", comment: "")` |
| `String(format: NSLocalizedString("greeting", comment: ""), name)` | `String(format: StringProvider.shared.getCached("greeting") ?? NSLocalizedString("greeting", comment: ""), name)` |

Leave alone:

- `.stringsdict` plurals and String Catalog variations;
- `InfoPlist.strings`;
- strings from other tables (the SDK's fallback reads only `Localizable`);
- `LocalizedStringResource` used by App Intents or widgets, unless the user asks.

The bundle fallback uses the **app's** current locale, not the language selected in the SDK, so don't rely on it for in-app language switching. It also treats a `Localizable` value equal to its key as missing, which matters only with `--keep-keys` when keys are English text.

## 5. Languages

- The SDK starts in:
  1. the language the user last chose (saved by `setLocale`, `changeLanguage(to:)` or `StringbootLanguageManager.setLanguage`);
  2. otherwise the device's preferred language (exact code, then the language part);
  3. otherwise the App's default.
- `StringProvider.shared.clearLanguageOverride()` returns to automatic selection, for example from a "Use device language" option.
- `StringbootLanguageManager` (SwiftUI) switches language; `SBText`, `@StringbootString`, `.stringboot()` and `publisher(for:)` follow. In UIKit, `SBLabel`/`SBButton`/`setStringboot` follow only `StringbootLanguageNotifier.shared.changeLanguage(to:)`.
- Active languages: `StringbootLanguageManager().availableLanguages` or `await StringProvider.shared.getAvailableLanguagesFromServer()` (`code`, `name`, `nativeName`, `isRightToLeft`). Codes match exactly (`pt-BR`).

## 6. Release builds, privacy and pinning

- **App Store privacy:** the SDK ships a privacy manifest. The user must declare the **Device ID** the SDK creates in their App Store privacy answers: collected for app functionality, not linked to the user, not used for tracking. Tell them.
- **Pinning:** `enableCertificatePinning: true` applies in every build configuration, including Debug, so pass `false` in Debug if the developer uses a proxy (`#if DEBUG`).
- **Logging:** `StringbootLogger.isLoggingEnabled = true; StringbootLogger.logLevel = .debug` in Debug only.

## 7. FAQs and experiments

- **FAQs:** they come with the Catalog. Use `await FAQProvider.shared.getFAQs(tag:subTags:)` or `observeFAQs(tag:)`. Answers are Markdown: render them with `SBFAQAnswerText(faq)` (SwiftUI) or `StringbootMarkdown.attributedString(faq.answer, font:)` (UIKit). Never show raw Markdown.
- **Experiments:** no code is needed to serve variants. To report them, implement `StringbootAnalyticsHandler` (`onExperimentsAssigned(experiments:)`, where an **empty dictionary** means experiments stopped or the language has none; and optionally `onExperimentExposure(_:)`), and pass it as `analyticsHandler:`.

## 8. Upgrading an older SDK

- **1.x/2.x → 3.0.1:**
  - Change the package URL to `https://github.com/Stringboot-SDK/stringboot-ios-sdk`, from `3.0.1`.
  - Raise the deployment target to iOS 15 / macOS 12, and use Xcode 27.
  - Use a Client Token (`sb_...`).
  - Keep `FAQProvider.shared.initialize(...)`, but drop separate FAQ syncs.
  - Cached strings, FAQs and the Device-ID migrate automatically.
  - Removed: `FAQSyncClient`, the Core Data classes, and the old wire models.
- **3.0.0 → 3.0.1:** no code changes. Language choices are now saved, and a token change keeps the stored strings until the new token works.

## 9. Troubleshooting

| Symptom | Cause / fix |
| :--- | :--- |
| `??key??` | Key missing in Stringboot (selected and default language) and in `Localizable`; or a first launch offline. Keys are case-sensitive. |
| `isTokenRejected` / `.invalidToken` | Not a valid Client Token of this App. Stored strings stay; fix the token and call `initialize` again. |
| Edits don't appear | They take up to about two minutes. Call `startPeriodicSync()` for long-lived screens; `await refreshFromNetwork()` checks now. |
| UIKit text doesn't update (edits, first download, or language change) | `setStringboot`/`SBLabel` only react to `StringbootLanguageNotifier`. Use `publisher(for:)`. |
| `.stringboot()` loses its font/colour | Apply modifiers after `.stringboot(...)`. |
| Requests fail through Charles/Proxyman | Pinning is on. Pass `false` in Debug. |
