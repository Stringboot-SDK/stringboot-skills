# Stringboot agent skills

Agent skills that help coding agents (Claude Code, Cursor, Codex, and other agents supported by [`skills`](https://www.npmjs.com/package/skills)) integrate [Stringboot](https://stringboot.com) into your apps.

## Install

```bash
npx skills add Stringboot-SDK/stringboot-skills
```

Add `-g` to install it for all your projects, or `-a <agent>` to pick the agent.

## stringboot-integration

Integrates the Stringboot SDKs and moves your existing strings to Stringboot:

- **Android** (`com.stringboot:stringboot-android-sdk` 2.1.0+), **iOS/macOS** (`StringbootSDK` 3.0.1+), **Web** (`@stringboot/web-sdk` 3.0.1+, including React, Next.js and Vue)
- Installs and initializes the SDK, and converts UI code to the SDK's reactive APIs.
- Extracts existing strings from `strings.xml`, `Localizable.strings`, String Catalogs (`.xcstrings`) and i18n JSON (i18next, react-intl, vue-i18n) into CSV files for the dashboard's **Bulk Upload**.
- Normalizes keys so the same key works on every platform, and renames them in code and resource files.
- Keeps your local resource files as the SDK's offline fallback, and sets aside what Stringboot can't serve (plurals, arrays, styled text) with a report.

Ask your agent, for example:

> Integrate Stringboot into this app. My Client Token is sb_… and the default language is English.

> Move our existing strings.xml and Localizable.strings to Stringboot.

You need a Stringboot account, an App and a **Client Token** (`sb_…`) from the [dashboard](https://dashboard.stringboot.com). Documentation: https://docs.stringboot.com

### The extractor on its own

The migration script needs only Python 3.8+:

```bash
python3 skills/stringboot-integration/scripts/extract_strings.py \
  --default-language en --android app/src/main/res --ios MyApp --web src/locales --out stringboot-migration
```

It writes upload files (50 rows each, the dashboard's limit), `key-map.json`, `android-keep.xml` and `report.md`. It changes your project only with `--rename-local`.

## Development

```bash
python3 tests/test_extract.py
```

## Support

developer@stringboot.com
