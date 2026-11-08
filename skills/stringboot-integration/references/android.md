# Android (SDK 2.1.0)

## Contents

1. Install
2. Configure and initialize
3. Read strings
4. Converting existing code
5. Languages
6. Release builds: R8 and resource shrinking
7. FAQs and experiments
8. Upgrading an older SDK
9. Troubleshooting

## 1. Install

The SDK is on Maven Central. Most projects already have `mavenCentral()` in `settings.gradle(.kts)`. Add the dependency to the app module:

```kotlin
dependencies {
    implementation("com.stringboot:stringboot-android-sdk:2.1.0")
}
```

Requirements: `minSdk` 24 or higher, Kotlin 1.9+. The SDK declares `INTERNET` and `ACCESS_NETWORK_STATE` itself and ships its own R8 rules, so add neither.

It no longer brings Material 3, Compose runtime, WorkManager, `activity-ktx` or `lifecycle-viewmodel`. If the app used them only through an older Stringboot SDK, declare them in the app.

## 2. Configure and initialize

Prefer manifest configuration, with the token injected from Gradle so it's easy to change per build:

```kotlin
// app/build.gradle.kts
android {
    defaultConfig {
        manifestPlaceholders["stringbootClientToken"] =
            (project.findProperty("STRINGBOOT_CLIENT_TOKEN") as String?) ?: "sb_YOUR_CLIENT_TOKEN"
    }
}
```

```xml
<!-- AndroidManifest.xml, inside <application> -->
<meta-data android:name="com.stringboot.api_url" android:value="https://api.stringboot.com" />
<meta-data android:name="com.stringboot.api_token" android:value="${stringbootClientToken}" />
```

Optional entries:

- `com.stringboot.cache_size`: default `1000`.
- `com.stringboot.default_locale`: the language to use until the user picks one.
- `com.stringboot.enable_ssl_pinning`: default `false`. Pinning applies only in non-debuggable builds.
- `com.stringboot.auto_sync`: default `true`.

Initialize in the `Application` class (create one and register it in the manifest if the app has none):

```kotlin
import android.app.Application
import com.stringboot.sdk.FAQProvider
import com.stringboot.sdk.StringProvider
import com.stringboot.sdk.StringbootExtensions

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!StringbootExtensions.autoInitialize(this)) {
            // No token configured: serve local strings only
            StringProvider.initialize(context = this, api = null)
        }
        FAQProvider.initialize(context = this)   // only if the app shows Stringboot FAQs
        StringProvider.startAutoRefresh()        // optional: check every 60 s while in the foreground
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        StringProvider.handleMemoryPressure(level)
    }
}
```

The SDK syncs by itself:

- once right after initialization,
- when the app returns to the foreground (at most once a minute),
- when the network returns after a failed check.

`initialize` never waits for the network. `autoSync = false` (or the manifest entry) turns automatic syncing off; then nothing syncs until `sync()` or `startAutoRefresh()` is called.

Code-only alternative, when the token comes from elsewhere:

```kotlin
import com.stringboot.sdk.api.StringbootApi

StringProvider.initialize(
    context = this,
    api = StringbootApi.create("https://api.stringboot.com", BuildConfig.STRINGBOOT_CLIENT_TOKEN),
)
```

## 3. Read strings

Every read follows: experiment variant → selected language → default language → `strings.xml` resource **with the same name** → `??key??`.

| Where | Use | Updates live |
| :--- | :--- | :--- |
| XML layout `TextView` | `android:tag="key"` + `root.applyStringbootTags()` | Yes, while attached |
| XML layout, drop-in | `<com.stringboot.sdk.views.sbTextView android:text="@string/key" />` | Yes |
| Any `TextView` in code | `textView.stringboot("key")` (`com.stringboot.sdk.views.stringboot`) | Yes, lifecycle-aware |
| Coroutine | `StringProvider.get("key")` (suspend) | No |
| Flow / Compose | `StringProvider.getFlow("key")` | Yes |

There is **no synchronous read** on Android. Don't wrap `get()` in `runBlocking` on the main thread.

```kotlin
import com.stringboot.sdk.views.applyStringbootTags

override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
    view.applyStringbootTags()   // binds every TextView whose android:tag is a key
}
```

**Compose**: a small helper keeps the local resource as the first value:

```kotlin
@Composable
fun sbString(key: String, @StringRes fallback: Int): String {
    val initial = stringResource(fallback)
    val lang = StringProvider.deviceLocale()
    val flow = remember(key, lang) { StringProvider.getFlow(key, lang) }
    return flow.collectAsState(initial = initial).value
}

Text(sbString("welcome_message", R.string.welcome_message))
```

**Named placeholders** (`{name}`), when the value is shared with iOS and web:

```kotlin
fun String.fill(vararg args: Pair<String, Any?>): String =
    args.fold(this) { acc, (k, v) -> acc.replace("{$k}", v.toString()) }

textView.text = StringProvider.get("greeting").fill("name" to user.name)
```

For printf values (`%1$s`), keep formatting in the app: `String.format(locale, value, arg)`.

## 4. Converting existing code

Use `key-map.json` from the migration. Convert the patterns below, and keep the `strings.xml` entries: they're the offline fallback, under the same names.

| Before | After |
| :--- | :--- |
| `<TextView android:text="@string/title" … />` | Add `android:tag="title"`; call `applyStringbootTags()` once in the Activity/Fragment. Keep `android:text` as the fallback. |
| `tv.setText(R.string.title)` / `tv.text = getString(R.string.title)` | `tv.stringboot("title")` |
| `getString(R.string.greeting, name)` (printf) | `lifecycleScope.launch { tv.text = String.format(StringProvider.get("greeting"), name) }`, or collect `getFlow` to keep it live. |
| `stringResource(R.string.title)` (Compose) | `sbString("title", R.string.title)` |
| `onBindViewHolder`: `holder.title.setText(R.string.x)` | `holder.title.stringboot("x")` |
| `hint`, `contentDescription`, menu titles, toolbar titles | Set from code with `get()`/`getFlow()` if they should be remote, else leave them. Tags and `sbTextView` set only `text`. |
| Notifications, widgets, services, non-coroutine code | Keep `getString(R.string.x)` (local), or launch a coroutine and call `get()`. |

Leave `<plurals>`, `<string-array>`, styled/HTML strings and `translatable="false"` strings as they are.

## 5. Languages

- `StringProvider.setLocale("es")` sets and persists the language. Then call `sync("es")` in a coroutine to download it if needed, and re-apply tags. Flows are bound to the language they were created with, so create new ones.
- `getAvailableLanguagesFromServer()` lists the App's active languages (`code`, `name`, `isPrimary`).
- **Limitation:** the starting language is the **language part** of the device locale (`pt`, not `pt-BR`), and codes must match exactly. If the App uses regional codes (`pt-BR`, `zh-CN`), set the language explicitly with `setLocale`, or use base codes in the App.
- A deactivated language falls back to the App's default language.
- RTL layout is the app's job (`android:supportsRtl`).

## 6. Release builds: R8 and resource shrinking

- R8: nothing to add. Don't add the 2.0.0-only `-dontwarn com.google.errorprone…` rule.
- **Resource shrinking (`isShrinkResources = true`):** the SDK reads `strings.xml` fallbacks by name at runtime. Once code stops referencing `R.string.x`, the shrinker removes those strings and the offline fallback is gone. Keep them in `app/src/main/res/raw/keep.xml`; merge with an existing file if there is one:

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:tools="http://schemas.android.com/tools"
    tools:keep="@string/welcome_message,@string/settings_title" />
```

The migration script writes the full list to `android-keep.xml`. Wildcards work (`@string/home_*`), and `@string/*` keeps all strings.

- Verify with a release build: `./gradlew :app:assembleRelease`.

## 7. FAQs and experiments

- **FAQs:** they come with the Catalog. Use `FAQProvider.getFAQs(tag, subTags)` or `getFAQsFlow`. Answers are Markdown: render them with `textView.setFAQAnswer(faq)`, or with `StringbootMarkdown.toAnnotatedString(faq.answer)` in Compose (`com.stringboot.sdk.text`). Never show raw Markdown.
- **Experiments:** no code is needed to serve variants. To report them, pass `analyticsHandler` (`StringbootAnalyticsHandler.onExperimentsAssigned(map)`; an **empty map** means experiments stopped) and/or `exposureListener` (`StringbootExposureListener`). Both are accepted by `initialize` and `autoInitialize`. Use `providedDeviceId` only for a stable per-install id.

## 8. Upgrading an older SDK

- **1.x → 2.1.0:**
  - Bump the dependency.
  - Replace the token with a Client Token (`sb_...`).
  - Remove any `X-API-Token` or `Authorization` setup.
  - `StringbootApi.create(baseUrl, clientToken)` replaces the Retrofit interface.
  - `FAQProvider.initialize(..., api)` ignores `api`.
  - Cached strings and the Device-ID survive.
- **2.0.x → 2.1.0:** no changes needed. Existing `sync()`/`startAutoRefresh()` calls are fine, because concurrent syncs are shared. A library compiled against 2.0.x that calls `initialize` with default arguments must be recompiled.
- **Pins:** if the app has its own `network_security_config.xml` pins for `api.stringboot.com`, update them from https://docs.stringboot.com/android-sdk/troubleshooting.

## 9. Troubleshooting

Turn on logs with `StringbootLogger.setDebugEnabled(true)` (logcat tag `StringbootSDK`). Check `StringProvider.getLastSyncResult()`.

| Symptom | Cause / fix |
| :--- | :--- |
| `??key??` | Key missing in Stringboot (selected and default language) and in `strings.xml`; or a first launch offline. Keys are case-sensitive. |
| `SyncResult.Unauthorized` | Not a valid Client Token of this App. Stored strings stay; fix the token and re-initialize. |
| Edits don't appear | They take up to about two minutes. The SDK checks at start-up and on returning to the foreground; add `startAutoRefresh()` for long-lived screens. |
| Shows default language | Deactivated language, or a regional code mismatch (`pt` vs `pt-BR`); see Languages. |
| Fallback strings missing only in release | Resource shrinking; add `keep.xml`. |
| View not updating after language change | Re-apply tags or create new Flows after `setLocale`. |
