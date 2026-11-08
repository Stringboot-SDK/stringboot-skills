# Migrating existing strings to Stringboot

Use this when the app already has localized strings: Android `res/values*/strings.xml`, iOS `*.lproj/Localizable.strings` or `Localizable.xcstrings`, or web i18n JSON (i18next, react-intl, vue-i18n, next-intl, plain key/value).

The goal: the same keys and values live in Stringboot, the code reads them through the SDK, and the local files stay as the offline fallback.

## Contents

1. Run the extractor
2. Review the report with the user
3. Upload the files
4. Rename keys locally
5. Rewrite call sites
6. Placeholders and plurals
7. What stays local

## 1. Run the extractor

The script needs only Python 3.8+ (no packages). It changes nothing in the project unless you pass `--rename-local`.

```bash
python3 <skill-dir>/scripts/extract_strings.py \
  --default-language en \
  --android app/src/main/res \
  --ios MyApp \
  --web src/locales \
  --out stringboot-migration
```

| Option | Use |
| :--- | :--- |
| `--default-language` | The App's default language in Stringboot (the user's answer). Android `values/` and iOS `Base.lproj` are read as this language. |
| `--android RES_DIR` | Each `res/` folder (repeatable; include feature modules). |
| `--ios DIR` | A folder containing `*.lproj` and/or `*.xcstrings` (repeatable). `Pods`, `Carthage`, `.build` and `DerivedData` are skipped. |
| `--web PATH` | A locale JSON file or folder. The language comes from the file name (`en.json`) or folder (`en/translation.json`; other file names become a key prefix, the namespace). |
| `--web-file LANG=PATH` | A JSON file whose name isn't a language code. |
| `--language-map FROM=TO` | Rename a language to match the App, e.g. `pt=pt-BR`, `zh-Hans=zh`. Codes must match the App exactly. |
| `--prefer android\|ios\|web` | Whose value wins when the same key has different text on two platforms (default: Android, then iOS, then web). The other platform's value is uploaded under `<key>_<platform>`. |
| `--keep-keys` | Don't normalize keys. Use only if every key is already valid on every platform. On iOS, a `Localizable` value equal to its key counts as missing for the fallback. |
| `--rename-local` | Also rename the keys in local Android/iOS resource files and Android `R.string` / `@string` references (step 4). |

It writes into `--out`:

- `upload/stringboot-upload-001.csv`, `-002.csv`, …: the files to upload, 50 rows each.
- `key-map.json`: `{platform: {old_key: new_key}}`. This drives the code rewrite.
- `android-keep.xml`: the `tools:keep` list for Android resource shrinking.
- `report.md`: renamed keys, cross-platform conflicts, what stays local and why, and values to check.

How it reads the files:

- **Android:** follows aapt's rules (quotes keep whitespace; `\'`, `\"`, `\n`, `\t`, `\@`, `\?`, `\uXXXX`; whitespace collapses outside quotes). `<xliff:g>` text is kept.
- **iOS:** reads `.strings` in UTF-8 or UTF-16. When an app uses English sentences as keys and has no English entry, the sentence becomes the English value.
- **Web:** flattens nested JSON with `.` and converts `{{name}}` to `{name}`.
- **Values:** encoded so the SDKs show them unchanged. Newlines are stored as `\n`, which the SDKs turn back into newlines.

## 2. Review the report with the user

Read `report.md` and summarize it for the user before uploading:

- **Conflicts:** same key, different text across platforms. Ask which text is right, or keep the platform-specific keys the script created.
- **Kept local:** plurals, arrays, styled/HTML strings, non-translatable constants, resource references, empty values. They stay where they are. See section 7.
- **Check these:** printf placeholders, `%%`, i18next plural forms, iOS keys whose English text must be added to `en.lproj` after renaming.
- **Languages:** every code listed will be **added and activated** in the App on upload. Make sure that's intended, and that the codes match what the apps request.

Re-run the script after any decision (for example with `--language-map` or `--prefer`). It's deterministic.

## 3. Upload the files

The user uploads them. There is no API or CLI for customers, so give clear steps:

1. Dashboard → **Strings** (under String Resources) → select the App in the app selector → **Bulk Upload**. Or: Applications → the App → **Bulk Upload**.
2. Drop `stringboot-upload-001.csv` on "Upload your file" and check the preview.
3. Under **Duplicate Handling**, choose:
   - **Skip All Duplicates** (the default) to keep values already in the dashboard, or
   - **Replace All Duplicates** to overwrite them with the app's values.
   Avoid "Detect & Review": it can hold back keys that merely look similar and never save them.
4. Click **Upload N Strings**. Then upload `-002.csv` and the rest, in order.

What the user should know:

- **50 strings per upload:** each file holds at most 50 rows (key + language), the dashboard's limit, so no unticking is needed.
- **Default language:** the first file starts with the default language, because the first language added to a new App becomes its default.
- **Plan limit:** new strings count toward the plan's string limit; updates to existing ones are free. If the preview says "Not enough strings left on your plan", the user must upgrade or upload fewer.
- **New languages:** every language code in a file is **added and activated** in the App, without a warning. Check the "Detected Languages" badges.
- **Trimmed values:** leading and trailing spaces in values are trimmed. The report lists affected values.
- **Display quirk:** the preview may display `&` as `&amp;`; the upload is unaffected.

The CSV format is `key,value,languageCode` with a header row (RFC 4180 quoting, UTF-8). Keys use `[A-Za-z0-9_.-]`, 1–255 characters, case-sensitive. Values are 1–10,000 characters, stored exactly as written (apart from the trimming). A file must not repeat a key + language; the script guarantees that.

To round-trip later, **Strings → Export → CSV** produces a file Bulk Upload accepts again.

## 4. Rename keys locally

Local resource keys must equal the Stringboot keys, or the offline fallback stops matching:

```bash
python3 <skill-dir>/scripts/extract_strings.py ... --rename-local
```

This renames:

- **Android:** `<string name="…">` in every `values*` folder, plus `R.string.*` and `@string/*` in `.kt`, `.java` and `.xml` files under the module's `src/` (all source sets).
- **iOS:** keys in `*.lproj/*.strings` (keeping UTF-16 files UTF-16) and in `*.xcstrings`. When a sentence key was also the English text, the English text is kept as a value.

Then handle by hand, using `key-map.json`:

- **iOS code:** `NSLocalizedString("Old key", …)`, `String(localized: "Old key")`, SwiftUI `Text("Old key")`.
- **Web code:** `t('home.title')` and similar calls.
- **Missing English entries:** add the English text to `en.lproj/Localizable.strings` for every key the report lists under "no en entry".
- **Android other modules:** references in modules you didn't pass with `--android`.

Build after renaming. Android fails the build on any missed `R.string` reference, which is a useful check.

## 5. Rewrite call sites

Convert the places that show text, using the patterns in each platform reference ("Converting existing code"). Do it file by file, and keep each change small and reviewable. Priorities:

1. UI text set from resources: layouts and `setText`, SwiftUI `Text` and UIKit labels, JSX text.
2. Text built in code: messages, dialogs, toasts.
3. Leave alone: logging, analytics event names, keys of other systems, and anything in "What stays local".

## 6. Placeholders and plurals

The SDKs never format values. They return the stored text.

**Shared values:** use named placeholders, e.g. `Hello, {name}!`, with a small helper on each platform (see the platform references). The script already turns i18next `{{name}}` into `{name}`.

**printf values** (`%1$s`, `%d` on Android; `%@`, `%lld` on iOS) stay printf. Keep calling `String.format` (Android) or `String(format:)` (iOS) on the value the SDK returns. They differ between platforms, so such a key is platform-specific; the script reports them.

**Plurals:** Stringboot has none. Either keep the plural local (simplest), or split it into keys like `cart_items_one` and `cart_items_other` and choose one in code:

```kotlin
val key = if (count == 1) "cart_items_one" else "cart_items_other"   // English rules only
```

For languages with more forms, use the platform's plural rules (Android `PluralRules`, iOS `.stringsdict`, web `Intl.PluralRules`) to pick the form name, then read `"<base>_<form>"`.

## 7. What stays local

These keep working exactly as before:

- **Android:** `<plurals>`, `<string-array>`, strings with `<b>`/`<i>`, CDATA or escaped HTML anywhere in the value, `translatable="false"`, strings that reference other resources, `values-night`/`values-car`/`values-v21`-style variants, and `product="…"` variants after the first one. Also `hint`, `contentDescription` and other non-text attributes: the SDK's tags and `sbTextView` only set text. Set them from code if they should be remote.
- **iOS:** `.stringsdict`, String Catalog plural/device variations, `shouldTranslate: false`, `InfoPlist.strings`, and tables other than `Localizable` (the SDK's fallback reads only `Localizable`, so moving them to Stringboot loses their offline fallback).
- **Web:** arrays, ICU messages with a type (`plural`, `select`, `number`, `date`), i18next formatting (`{{- name}}`, `{{date, datetime}}`), vue-i18n pipe plurals (`a | b`), non-string values. The Web SDK has no local fallback, so the i18n files can stay for these while the rest moves to Stringboot.
