# Web (SDK 3.0.1): vanilla JS, React, Next.js, Vue

## Contents

1. Install
2. Initialize
3. Read strings
4. Converting existing code (i18next, react-intl, vue-i18n)
5. Next.js and server rendering
6. Errors, languages, FAQs, experiments
7. Upgrading 2.x
8. Troubleshooting

## 1. Install

```bash
npm install @stringboot/web-sdk@^3.0.1
```

- **Without a bundler:** `import StringBoot from 'https://cdn.jsdelivr.net/npm/@stringboot/web-sdk@3/dist/index.mjs'` in a `<script type="module">`.
- **React hooks:** `@stringboot/web-sdk/react` (React 18 or 19).
- **TypeScript:** works with every `moduleResolution`.
- **Node:** 18+ for SSR.
- **React Native:** unsupported.

The Client Token is public, so `VITE_`/`NEXT_PUBLIC_` environment variables are fine.

## 2. Initialize

Initialize once, at start-up.

- With strings stored from an earlier visit, `initialize()` resolves at once; the server check finishes in the background.
- On a first visit, it waits for the first download.
- It never rejects for network or token problems (only for invalid options).

**Vanilla:**

```js
import StringBoot from '@stringboot/web-sdk';

await StringBoot.initialize({
  apiToken: import.meta.env.VITE_STRINGBOOT_CLIENT_TOKEN,
  defaultLanguage: 'en',            // used until the user picks a language
});
```

**React:** define the config at module level, so the SDK doesn't re-initialize on every render.

```tsx
import { useStringBoot } from '@stringboot/web-sdk/react';

const config = { apiToken: import.meta.env.VITE_STRINGBOOT_CLIENT_TOKEN, defaultLanguage: 'en' };

export function App() {
  const { initialized, error } = useStringBoot(config);
  if (error) console.error('Stringboot:', error);   // rejected token; stored strings still show
  if (!initialized) return null;
  return <Routes />;
}
```

**Vue:** call `initialize()` in `main.ts` before `app.mount()`, and use the composable in section 3.

Periodic checks run every 60 seconds while the tab is visible (`refreshInterval`, minimum 60000, `0` disables).

## 3. Read strings

Every read follows: experiment variant → selected language → the App's default language → `??key??`. **The Web SDK has no local fallback**; see section 4 for keeping one.

| API | Use | Updates live |
| :--- | :--- | :--- |
| `useString('key')`, `useStrings([...])` | React components | Yes |
| `StringBoot.watch('key', cb)` | Vanilla/Vue; returns an unsubscribe function | Yes |
| `StringBoot.getCached('key')` | Synchronous; `undefined` if not in memory | No |
| `await StringBoot.get('key')` | One-shot | No |

Values can contain real line breaks (from `\n`). Render them with `white-space: pre-line`.

**Vue composable:**

```ts
import { ref, onScopeDispose } from 'vue';
import StringBoot from '@stringboot/web-sdk';

export function useString(key: string) {
  const value = ref(StringBoot.getCached(key) ?? '');
  onScopeDispose(StringBoot.watch(key, (v) => { value.value = v; }));
  return value;
}
```

**Named placeholders** (`{name}`), shared with Android and iOS:

```ts
export const fill = (s: string, args: Record<string, unknown>) =>
  s.replace(/\{(\w+)\}/g, (m, k) => (k in args ? String(args[k]) : m));
```

## 4. Converting existing code (i18next, react-intl, vue-i18n)

There's no adapter. Convert call sites to Stringboot keys from `key-map.json`. Keep the i18n library and its JSON files for what Stringboot can't serve: ICU plural/select, arrays, rich-text components. Optionally use them as the **fallback** for keys Stringboot doesn't have yet, which also covers a first visit while offline:

```tsx
import { useString } from '@stringboot/web-sdk/react';
import { useTranslation } from 'react-i18next';

/** Stringboot first; the existing i18n file while the key is missing. */
export function useText(key: string, oldKey: string, args?: Record<string, unknown>) {
  const value = useString(key);
  const { t } = useTranslation();
  const text = value === `??${key}??` ? t(oldKey) : value;
  return args ? fill(text, args) : text;
}
```

| Before | After |
| :--- | :--- |
| `t('home.title')` | `useString('home_title')` (or `useText('home_title', 'home.title')`) |
| `t('home.greeting', { name })` with `{{name}}` | `fill(useString('home_greeting'), { name })`. The migration already converted `{{name}}` to `{name}`. |
| `<FormattedMessage id="cart.title" />` | `{useString('cart_title')}` |
| `intl.formatMessage({ id: 'x' }, { n })` | `fill(useString('x'), { n })`, if the message is a plain `{n}` substitution; keep ICU messages local |
| `$t('nav.home')` (vue-i18n) | `useString('nav_home')` from the composable |
| Strings outside components | `StringBoot.getCached('key') ?? fallback` |

Hooks must be called in components. In loops, read many keys with `useStrings([...])`.

## 5. Next.js and server rendering

- **Client:** a `'use client'` provider that calls `useStringBoot(config)` in the root layout, and hooks in client components only.
- **Server** (Server Components, `generateMetadata`, `getStaticProps`): create a separate instance, never the browser singleton:

```ts
import { StringProvider } from '@stringboot/web-sdk';

const server = new StringProvider();
let ready: Promise<void> | null = null;

export async function getServerStrings(lang: string, keys: string[]) {
  ready ??= server.initialize({
    apiToken: process.env.NEXT_PUBLIC_STRINGBOOT_CLIENT_TOKEN!,
    defaultLanguage: 'en',
    fetch: (url, init) => fetch(url, { ...init, cache: 'no-store' }),  // skip the Next.js fetch cache
  });
  await ready;
  await server.syncNow(lang).catch(() => undefined);
  const values = await Promise.all(keys.map((k) => server.get(k, lang)));
  return Object.fromEntries(keys.map((k, i) => [k, values[i]]));
}
```

- To avoid hydration mismatches, render string UI after `initialized`, or pass server strings as props.
- Raw values from `getCatalog()` need `unescapeString()` to match the browser. `get()` already unescapes.
- Experiment keys: the server instance buckets with its own Device-ID. Render experiment keys on the client.

## 6. Errors, languages, FAQs, experiments

- **Errors:**
  - `StringBoot.onSyncError(cb)` reports errors, including ones that arrive after `initialize()` resolved.
  - `onSyncSuccess(cb)` fires after every successful check; use it to clear an error banner.
  - `getLastError()` returns the latest error, and `getStatus()` returns `'error'` after a rejected token.
  - A rejected token and other errors that need attention are logged with `console.error`; network errors aren't (they retry).
- **Languages:**
  - `await StringBoot.changeLanguage('fr')` switches language; `useLanguage()` does the same in React.
  - `getActiveLanguages()` / `useActiveLanguages()` list the App's languages (`code`, `name`, `nativeName`, `direction`, `isDefault`).
  - Start-up picks the stored choice, then `defaultLanguage`, then the browser languages, then the App default.
  - Codes match exactly (`pt-BR`). A missing language falls back to the default.
  - Set `dir` from `direction` for RTL.
- **FAQs:** they come with the Catalog. Use `StringBoot.FAQ.getFAQs({ tag, subTags })` or `useFAQs(tag)`. Answers are Markdown: render them with `renderMarkdownToHtml(faq.answer)`, which returns sanitized HTML. Never insert `faq.answer` as HTML.
- **Experiments:** variants are served automatically. Report them with `onExposure` and `analyticsHandler.onExperimentsAssigned`, which is called with `{}` when experiments stop. Pass `deviceId` only for a stable id shared with other platforms.

## 7. Upgrading 2.x

1. `npm install @stringboot/web-sdk@^3.0.1`.
2. Use a Client Token (`sb_...`).
3. Remove `StringBoot.FAQ.initialize(...)`.
4. Code that assumed "`initialize()` resolved = synced" should `await StringBoot.waitForStartupSync()`.
5. Handle `{}` in `onExperimentsAssigned`.
6. Removed types: `MetaResponse`, `DeltaResponse`, `CatalogResponse` and the other 2.x wire types. Use `Catalog`.

## 8. Troubleshooting

| Symptom | Cause / fix |
| :--- | :--- |
| `??key??` | Key missing in the selected and default language. Keys are case-sensitive. Or a first visit while offline. |
| `INVALID_TOKEN` | Not a valid Client Token of this App. Stored strings stay; fix it and call `initialize()` again. |
| Text doesn't update on edits | You used one-shot `get()`. Switch to `useString`/`watch`. Edits take up to about two minutes. |
| `\n` shows on one line | Add `white-space: pre-line`. |
| CORS error in the console | Usually a network failure or a blocked request. Stringboot allows every origin; there's nothing to configure. |
| Hydration mismatch (Next.js) | Hooks don't run on the server; see section 5. |
