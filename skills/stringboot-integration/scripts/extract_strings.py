#!/usr/bin/env python3
"""Extract an app's existing strings into a Stringboot bulk-upload file.

Reads Android res/values*/ XML, iOS .strings/.xcstrings, and web i18n JSON; normalizes keys to
lower snake_case; merges platforms; writes:

  <out>/upload/stringboot-upload-001.csv, -002.csv, ...
                                upload each in the dashboard (Strings > Bulk Upload); at most
                                50 rows per file, default-language rows first
  <out>/key-map.json            {platform: {old_key: new_key}} for rewriting code
  <out>/report.md               what was skipped (keep local), conflicts, notes
  <out>/android-keep.xml        tools:keep list for res/raw/keep.xml (Android only)

Only Python 3.8+ standard library. Nothing is changed in the project unless --rename-local is set.

Example:
  python3 extract_strings.py --default-language en \
      --android app/src/main/res --ios MyApp --web src/locales --out stringboot-migration
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import OrderedDict, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sb_android import read_android  # noqa: E402
from sb_common import (MAX_VALUE_LENGTH, UPLOAD_ROWS_PER_FILE, Skipped, encode_for_stringboot,  # noqa: E402
                       looks_like_sentence, normalize_key, placeholder_style)
from sb_ios import read_ios  # noqa: E402
from sb_rename import rename_local  # noqa: E402
from sb_web import read_web  # noqa: E402

PLATFORM_ORDER = ["android", "ios", "web"]


def assign_keys(entries, keep_keys):
    """Give each (platform, source_key) a normalized key, unique within its platform."""
    key_map = {p: OrderedDict() for p in PLATFORM_ORDER}
    used = {p: {} for p in PLATFORM_ORDER}
    for e in entries:
        m = key_map[e.platform]
        if e.source_key not in m:
            if keep_keys:
                new = e.source_key
            else:
                new = normalize_key(e.source_key, max_words=6 if looks_like_sentence(e.source_key) else None)
            base, n = new, 2
            while new in used[e.platform] and used[e.platform][new] != e.source_key:
                new = "%s_%d" % (base, n)
                n += 1
            used[e.platform][new] = e.source_key
            m[e.source_key] = new
        e.key = m[e.source_key]
    return key_map


def merge_platforms(entries, key_map, prefer):
    """One value per (key, language). Same key with different values on two platforms -> the
    non-preferred platform gets a platform suffix so nothing is lost."""
    order = [prefer] + [p for p in PLATFORM_ORDER if p != prefer]
    by_key = defaultdict(dict)  # key -> platform -> {lang: value}
    for e in entries:
        by_key[e.key].setdefault(e.platform, {}).setdefault(e.language, e.value)
    conflicts = []
    for key, per_platform in by_key.items():
        platforms = [p for p in order if p in per_platform]
        winner = platforms[0]
        for other in platforms[1:]:
            a, b = per_platform[winner], per_platform[other]
            diff = [l for l in a if l in b and a[l] != b[l]]
            if diff:
                new = "%s_%s" % (key, other)
                for src, k in key_map[other].items():
                    if k == key:
                        key_map[other][src] = new
                for e in entries:
                    if e.platform == other and e.key == key:
                        e.key = new
                conflicts.append((key, winner, other, new, diff[0], a[diff[0]], b[diff[0]]))
    return conflicts


def build_rows(entries, language_map, skipped):
    rows = OrderedDict()
    warnings = []
    for e in entries:
        lang = language_map.get(e.language, e.language)
        if (e.key, lang) in rows:
            continue
        if not e.value.strip():
            skipped.append(Skipped(e.platform, e.source_key, lang, e.source_file,
                                   "empty value: Stringboot rejects blank values; keep it local"))
            continue
        value, warning = encode_for_stringboot(e.value)
        if len(value) > MAX_VALUE_LENGTH:
            skipped.append(Skipped(e.platform, e.source_key, lang, e.source_file,
                                   "longer than %d characters; keep it local" % MAX_VALUE_LENGTH))
            continue
        if warning:
            warnings.append((e, warning))
        if e.value != e.value.strip():
            e.notes.append("leading/trailing whitespace: the dashboard trims it on upload; keep spacing in the UI layout instead")
        style = placeholder_style(e.value)
        if style == "printf":
            e.notes.append("printf placeholders: this key is platform-specific (Android %s vs iOS %@)")
        rows[(e.key, lang)] = value
    return rows, warnings


def write_upload_files(out, rows, default_language):
    """CSV with header key,value,languageCode (RFC 4180), at most 50 rows per file.
    Default-language rows come first: the first language added to an App becomes its default."""
    folder = os.path.join(out, "upload")
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.startswith("stringboot-upload-") and old.endswith(".csv"):
            os.remove(os.path.join(folder, old))
    ordered = sorted(rows.items(), key=lambda kv: (kv[0][1] != default_language, kv[0][1], kv[0][0]))
    files = []
    for start in range(0, len(ordered), UPLOAD_ROWS_PER_FILE):
        name = "stringboot-upload-%03d.csv" % (len(files) + 1)
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["key", "value", "languageCode"])
            for (key, lang), value in ordered[start:start + UPLOAD_ROWS_PER_FILE]:
                w.writerow([key, value, lang])
        files.append(name)
    return files


def _rel(path):
    try:
        return os.path.relpath(path)
    except ValueError:
        return path


def write_outputs(out, rows, key_map, entries, skipped, conflicts, warnings, default_language):
    os.makedirs(out, exist_ok=True)
    files = write_upload_files(out, rows, default_language)
    with open(os.path.join(out, "key-map.json"), "w", encoding="utf-8") as f:
        json.dump({p: m for p, m in key_map.items() if m}, f, indent=2, ensure_ascii=False)
    android_keys = sorted({e.key for e in entries if e.platform == "android"})
    if android_keys:
        with open(os.path.join(out, "android-keep.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n'
                    '<!-- Merge into app/src/main/res/raw/keep.xml: keeps the offline fallback strings\n'
                    '     that are now read by name at runtime, so resource shrinking keeps them. -->\n'
                    '<resources xmlns:tools="http://schemas.android.com/tools"\n'
                    '    tools:keep="%s" />\n' % ",".join("@string/" + k for k in android_keys))
    langs = sorted({lang for (_, lang) in rows})
    lines = ["# Stringboot migration report", "",
             "- Strings to upload: **%d** values, **%d** keys" % (len(rows), len({k for k, _ in rows})),
             "- Languages: %s (default language given: `%s`)" % (", ".join("`%s`" % l for l in langs), default_language),
             "- Kept local (not uploaded): **%d**" % len(skipped),
             "- Upload files (%d, upload them in order): %s" % (len(files), ", ".join("`upload/%s`" % f for f in files)),
             "- New strings count toward the Stringboot plan's string limit (updating existing ones is free).",
             ""]
    renamed = [(p, s, k) for p, m in key_map.items() for s, k in m.items() if s != k]
    lines += ["## Renamed keys (%d)" % len(renamed), "",
              "Code and local resource files must use the new key. Full list: `key-map.json`.", ""]
    lines += ["- %s: `%s` → `%s`" % r for r in renamed[:200]]
    if len(renamed) > 200:
        lines.append("- … %d more in key-map.json" % (len(renamed) - 200))
    lines += ["", "## Conflicts (%d)" % len(conflicts), ""]
    lines += ["- `%s`: %s and %s differ (%s: %r vs %r); %s's version uploaded as `%s`"
              % (k, a, b, l, va, vb, b, new) for (k, a, b, new, l, va, vb) in conflicts]
    lines += ["", "## Kept local, not uploaded (%d)" % len(skipped), ""]
    lines += ["- %s `%s` [%s] %s: %s" % (s.platform, s.source_key, s.language, _rel(s.source_file), s.reason)
              for s in skipped]
    noted = [e for e in entries if e.notes]
    lines += ["", "## Check these (%d)" % (len(noted) + len(warnings)), ""]
    lines += ["- %s `%s` [%s]: %s" % (e.platform, e.key, e.language, "; ".join(dict.fromkeys(e.notes))) for e in noted]
    lines += ["- %s `%s` [%s]: %s" % (e.platform, e.key, e.language, w) for e, w in warnings]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--default-language", required=True, help="the App's default language code in Stringboot, e.g. en")
    ap.add_argument("--android", action="append", default=[], metavar="RES_DIR", help="an Android res/ directory")
    ap.add_argument("--ios", action="append", default=[], metavar="DIR", help="a folder containing *.lproj / *.xcstrings")
    ap.add_argument("--web", action="append", default=[], metavar="PATH", help="a locale JSON file or folder")
    ap.add_argument("--web-file", action="append", default=[], metavar="LANG=PATH", help="a JSON file and its language")
    ap.add_argument("--language-map", action="append", default=[], metavar="FROM=TO",
                    help="rename a language code to match the App, e.g. pt=pt-BR")
    ap.add_argument("--prefer", choices=PLATFORM_ORDER, default=None,
                    help="platform whose value wins when the same key differs (default: first platform given)")
    ap.add_argument("--keep-keys", action="store_true", help="don't normalize keys")
    ap.add_argument("--rename-local", action="store_true",
                    help="also rename keys in local Android/iOS resource files and Android R.string/@string references")
    ap.add_argument("--out", default="stringboot-migration")
    args = ap.parse_args(argv)

    if not (args.android or args.ios or args.web or args.web_file):
        ap.error("give at least one of --android, --ios, --web, --web-file")
    for p in args.android + args.ios + args.web:
        if not os.path.exists(p):
            ap.error("path not found: %s" % p)

    entries, skipped = [], []
    if args.android:
        e, s = read_android(args.android, args.default_language); entries += e; skipped += s
    if args.ios:
        e, s = read_ios(args.ios, args.default_language); entries += e; skipped += s
    if args.web or args.web_file:
        e, s = read_web(args.web, args.web_file); entries += e; skipped += s
    if not entries:
        print("No strings found. Check the paths.", file=sys.stderr)
        return 1

    prefer = args.prefer or next(p for p in PLATFORM_ORDER if any(e.platform == p for e in entries))
    key_map = assign_keys(entries, args.keep_keys)
    conflicts = merge_platforms(entries, key_map, prefer)
    language_map = dict(item.split("=", 1) for item in args.language_map)
    rows, warnings = build_rows(entries, language_map, skipped)
    write_outputs(args.out, rows, key_map, entries, skipped, conflicts, warnings, args.default_language)

    if args.default_language not in {lang for (_, lang) in rows}:
        print("Warning: no strings found in the default language %r. Check --default-language."
              % args.default_language, file=sys.stderr)
    if args.rename_local:
        changed = rename_local(key_map, args.android, args.ios)
        print("Renamed keys in %d local files." % changed)
    print("Wrote %s: %d values, %d kept local, %d conflicts. Read report.md next."
          % (args.out, len(rows), len(skipped), len(conflicts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
