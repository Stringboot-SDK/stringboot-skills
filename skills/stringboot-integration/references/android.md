# Android (SDK 2.1.0)

## Contents

1. Install
2. Configure and initialize
3. Read strings (safe patterns)
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

It no longer brings Material/Material 3, WorkManager, `activity-ktx` or `lifecycle-viewmodel`. If the app used them only through an older Stringboot SDK, declare them in the app.

## 2. Configure and initialize

Configure through the manifest, with the token injected from Gradle:

```kotlin
// app/build.gradle.kts
android {
    defaultConfig {
        // Empty when not set: the SDK then runs offline (local strings) instead of sending a fake token
        manifestPlaceholders["stringbootClientToken"] =
            (project.findProperty("STRINGBOOT_CLIENT_TOKEN") as String?) ?: ""
    }
}
```

Put the user's real token in `gradle.properties` (`STRINGBOOT_CLIENT_TOKEN=sb_...`) or CI secrets.

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
        StringbootExtensions.autoInitialize(this)   // with no token it runs offline and still returns true
        FAQProvider.initialize(context = this)       // only if the app shows Stringboot FAQs
        StringProvider.startAutoRefresh()            // optional: check every 60 s while in the foreground
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        StringProvider.handleMemoryPressure(level)
    }
}
```

The SDK syncs by itself:

- right after initialization,
- when the app returns to the foreground (at most once a minute),
- when the network returns after a failed check.

`initialize` never waits for the network.

`autoSync = false` (or the manifest entry) turns automatic syncing off. Then nothing syncs until `sync()` or `startAutoRefresh()` is called, except that reading a never-synced language with `stringboot()` or `get(..., allowNetworkFetch = true)` still downloads it.

Code-only alternative, when the token comes from elsewhere:

```kotlin
import com.stringboot.sdk.api.StringbootApi

StringProvider.initialize(
    context = this,
    api = StringbootApi.create("https://api.stringboot.com", BuildConfig.STRINGBOOT_CLIENT_TOKEN),
)
```

## 3. Read strings (safe patterns)

Every read follows: experiment variant → selected language → default language → the `strings.xml` resource **with the same name** (dots in the key map to `_`), in the **system** locale → `??key??`.

There is **no synchronous read** on Android. Don't wrap `get()` in `runBlocking` on the main thread.

| Where | Use |
| :--- | :--- |
| XML layouts | `android:tag="key"` on each `TextView`, plus `root.applyStringbootTags()` **once** after inflating (in `onCreate` / `onViewCreated`) |
| A `TextView` created or found in code | `tv.setText(R.string.key)`, then `tv.stringboot("key")` **once** for that view |
| RecyclerView rows | Per-holder `Job`; see below |
| Coroutines / logic | `StringProvider.get("key")` (suspend, one-shot) |
| Compose | The `sbString` helper below |

**Why "once":** `TextView.stringboot(key)` (`com.stringboot.sdk.views.stringboot`) starts a collector that keeps writing to the view until the view tree's `LifecycleOwner` is destroyed. Each extra call adds another collector, so after a rebind old keys overwrite the text. Never call it in bind, observer or `onResume` code. Without a `LifecycleOwner` (for example a view not yet attached) its collector is never cancelled.

**Avoid `sbTextView` for now.** With `android:text="@string/welcome_message"` it looks up `welcome.message` (it turns `_` into `.`), so it only ever shows the local fallback. It also loads once instead of updating live, and stops working after detach (RecyclerView, ViewPager). Use tags or `stringboot()` instead.

**RecyclerView adapters:**

```kotlin
class RowHolder(view: View) : RecyclerView.ViewHolder(view) {
    val title: TextView = view.findViewById(R.id.title)
    var job: Job? = null
}

override fun onBindViewHolder(holder: RowHolder, position: Int) {
    val key = items[position].titleKey
    holder.job?.cancel()
    holder.title.setText(items[position].titleRes)        // local text right away
    holder.job = lifecycleOwner.lifecycleScope.launch {    // the Fragment's viewLifecycleOwner
        StringProvider.getFlow(key).collect { holder.title.text = it }
    }
}

override fun onViewRecycled(holder: RowHolder) {
    holder.job?.cancel()
}
```

**Compose:** keep the language in Compose state, so a language change recomposes:

```kotlin
import androidx.annotation.StringRes
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.stringResource
import com.stringboot.sdk.StringProvider

val LocalStringbootLanguage = compositionLocalOf { StringProvider.deviceLocale() }

@Composable
fun sbString(key: String, @StringRes fallback: Int): String {
    val initial = stringResource(fallback)
    if (LocalInspectionMode.current) return initial           // previews: the SDK isn't initialized
    val lang = LocalStringbootLanguage.current
    val flow = remember(key, lang) { StringProvider.getFlow(key, lang) }
    return flow.collectAsState(initial = initial).value
}

// At the root: provide the language from state the app updates when the user switches
CompositionLocalProvider(LocalStringbootLanguage provides selectedLanguage) { AppContent() }
```

Call `sbString` only after `initialize` has run. A Flow created before initialization stays on `??key??`. New compositions show the local text for a moment, then the Stringboot value.

**Named placeholders** (`{name}`), when the value is shared with iOS and web:

```kotlin
fun String.fill(vararg args: Pair<String, Any?>): String =
    args.fold(this) { acc, (k, v) -> acc.replace("{$k}", v.toString()) }

lifecycleScope.launch {
    greeting.text = StringProvider.get("greeting").fill("name" to user.name)
}
```

For printf values (`%1$s`), keep formatting in the app: `String.format(locale, value, arg)`.

## 4. Converting existing code

Use `key-map.json` from the migration. Keep the `strings.xml` entries: they're the offline fallback, under the same names.

| Before | After |
| :--- | :--- |
| `<TextView android:text="@string/title" … />` | Add `android:tag="title"`; call `applyStringbootTags()` once after inflating. Keep `android:text`. |
| `tv.setText(R.string.title)` in `onCreate` / `onViewCreated` | Keep it, and add `tv.stringboot("title")` right after, once. |
| Text set repeatedly (observers, `onResume`, state updates) | `lifecycleScope.launch { tv.text = StringProvider.get("title") }` at that point (one-shot); don't add `stringboot()` there. |
| `getString(R.string.greeting, name)` (printf) | `lifecycleScope.launch { tv.text = String.format(StringProvider.get("greeting"), name) }` |
| `stringResource(R.string.title)` (Compose) | `sbString("title", R.string.title)` |
| `onBindViewHolder`: `holder.title.setText(R.string.x)` | The per-holder `Job` pattern above. |
| `hint`, `contentDescription`, menu and toolbar titles | Set from code with `get()` if they should be remote, else leave them. Tags only set `text`. |
| Notifications, widgets, services, non-coroutine code | Keep `getString(R.string.x)` (local), or launch a coroutine and call `get()`. |

Leave `<plurals>`, `<string-array>`, styled/HTML strings and `translatable="false"` strings as they are.

## 5. Languages

**Switching language, View-based UI:** the simplest correct approach is to restart the screen. Collectors keep the language they were created with, so re-applying tags would leave old collectors running.

```kotlin
lifecycleScope.launch {
    StringProvider.setLocale("es")   // persisted across restarts
    StringProvider.sync("es")        // download it if needed
    recreate()
}
```

**Compose:** update the state that feeds `LocalStringbootLanguage`, after `setLocale` and `sync`.

Other language rules:

- `getAvailableLanguagesFromServer()` lists the App's active languages (`code`, `name`, `isPrimary`).
- **Regional codes:** the starting language is the **language part** of the device locale (`pt`, not `pt-BR`), and codes must match exactly. If the App uses regional codes, call `setLocale("pt-BR")` yourself, or use base codes in the App.
- **Legacy codes:** Android can report `iw`, `in` and `ji` for Hebrew, Indonesian and Yiddish. Map them to `he`, `id` and `yi` before `setLocale` if the App uses the modern codes.
- The `strings.xml` fallback follows the system/app locale, not the SDK's selected language.
- A deactivated language falls back to the App's default language.
- RTL layout is the app's job (`android:supportsRtl`).

## 6. Release builds: R8 and resource shrinking

- R8: nothing to add.
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
- **Experiments:** no code is needed to serve variants. To report them, pass `analyticsHandler` (`StringbootAnalyticsHandler.onExperimentsAssigned(map)`; an **empty map** means experiments stopped) and/or `exposureListener`. Both are accepted by `initialize` and `autoInitialize`. Use `providedDeviceId` only for a stable per-install id.

## 8. Upgrading an older SDK

- **1.x → 2.1.0:**
  - Bump the dependency.
  - Use a Client Token (`sb_...`).
  - Remove any `X-API-Token` or `Authorization` setup.
  - `StringbootApi.create(baseUrl, clientToken)` replaces the Retrofit interface.
  - `FAQProvider.initialize(..., api)` ignores `api`.
  - Cached strings and the Device-ID survive.
- **2.0.x → 2.1.0:** no changes needed. Existing `sync()`/`startAutoRefresh()` calls are fine. A library compiled against 2.0.x that calls `initialize` with default arguments must be recompiled.
- **Pins:** if the app pins `api.stringboot.com` in its own `network_security_config.xml`, update the pins from https://docs.stringboot.com/android-sdk/troubleshooting.

## 9. Troubleshooting

Turn on logs with `StringbootLogger.setDebugEnabled(true)` (logcat tag `StringbootSDK`). Check `StringProvider.getLastSyncResult()`.

| Symptom | Cause / fix |
| :--- | :--- |
| `??key??` | Key missing in Stringboot (selected and default language) and in `strings.xml`; or a first launch offline. Keys are case-sensitive. |
| `SyncResult.Unauthorized` | Not a valid Client Token of this App. Stored strings stay; fix the token and re-initialize. |
| Edits don't appear | They take up to about two minutes. The SDK checks at start-up and on returning to the foreground; add `startAutoRefresh()` for long-lived screens. |
| Wrong text in list rows | `stringboot()` called in `onBindViewHolder`. Use the per-holder `Job` pattern. |
| `sbTextView` shows only local text | It maps `_` to `.` in keys. Use tags or `stringboot()`. |
| Shows default language | Deactivated language, a regional code mismatch (`pt` vs `pt-BR`), or a legacy code (`iw`). |
| Fallback strings missing only in release | Resource shrinking; add `keep.xml`. |
| Mixed languages after switching | Old collectors are still running; `recreate()` after `setLocale` + `sync`. |
