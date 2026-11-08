"""Read web i18n JSON files (i18next, react-intl, vue-i18n, next-intl, plain key/value)."""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional, Tuple

from sb_common import VUE_PIPE_PLURAL, Entry, Skipped, placeholder_style, to_named_placeholders

_LANG = re.compile(r"^[a-z]{2,3}([-_][A-Za-z]{2,4})?([-_][A-Z]{2}|[-_]\d{3})?$")
_DEFAULT_NAMESPACES = {"translation", "messages", "common", "index", "default"}
_PLURAL_SUFFIX = re.compile(r"_(zero|one|two|few|many|other)$")


def _lang_code(text: str) -> Optional[str]:
    if not _LANG.match(text):
        return None
    parts = re.split(r"[-_]", text)
    out = [parts[0].lower()]
    for p in parts[1:]:
        out.append(p.capitalize() if len(p) == 4 else p.upper())
    return "-".join(out)


def _language_and_namespace(path: str) -> Tuple[Optional[str], str]:
    """locales/en.json -> (en, ''); locales/pt-BR/checkout.json -> (pt-BR, 'checkout')."""
    stem = os.path.splitext(os.path.basename(path))[0]
    lang = _lang_code(stem)
    if lang:
        return lang, ""
    parent = _lang_code(os.path.basename(os.path.dirname(path)))
    if parent:
        return parent, "" if stem in _DEFAULT_NAMESPACES else stem
    return None, stem


def _flatten(obj, prefix, out, arrays):
    for k, v in obj.items():
        key = "%s.%s" % (prefix, k) if prefix else str(k)
        if isinstance(v, dict):
            if set(v.keys()) == {"message"} or ("message" in v and "description" in v):
                out.append((key, v.get("message")))  # Chrome-extension style {message, description}
            else:
                _flatten(v, key, out, arrays)
        elif isinstance(v, list):
            arrays.append(key)
        else:
            out.append((key, v))


def collect_web_files(paths: List[str]) -> List[str]:
    files = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "dist", "build")]
                files += [os.path.join(dirpath, f) for f in sorted(filenames) if f.endswith(".json")]
        else:
            files.append(p)
    return files


def read_web(paths: List[str], explicit: List[str]) -> Tuple[List[Entry], List[Skipped]]:
    """paths: files/dirs to scan; explicit: ["en=src/i18n/english.json", ...] for files whose name isn't a language."""
    entries: List[Entry] = []
    skipped: List[Skipped] = []
    jobs = [(f, None) for f in collect_web_files(paths)]
    for item in explicit:
        lang, _, f = item.partition("=")
        jobs.append((f, lang))
    for path, forced_lang in jobs:
        lang, namespace = _language_and_namespace(path)
        lang = forced_lang or lang
        if not lang:
            skipped.append(Skipped("web", "*", "?", path,
                                   "can't tell the language from the file name; pass --web-file LANG=PATH"))
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (ValueError, OSError) as e:
            skipped.append(Skipped("web", "*", lang, path, "couldn't read JSON: %s" % e))
            continue
        if not isinstance(doc, dict):
            skipped.append(Skipped("web", "*", lang, path, "not a JSON object of strings"))
            continue
        pairs, arrays = [], []
        _flatten(doc, namespace, pairs, arrays)
        for key in arrays:
            skipped.append(Skipped("web", key, lang, path, "arrays aren't supported by Stringboot; keep them local"))
        for key, value in pairs:
            if not isinstance(value, str):
                skipped.append(Skipped("web", key, lang, path, "not a string value"))
                continue
            style = placeholder_style(value)
            if style == "icu":
                skipped.append(Skipped("web", key, lang, path,
                                       "ICU/i18next formatting (plural, select, number, date, {{- }}); "
                                       "the SDK doesn't format; keep it local or split it into keys"))
                continue
            if VUE_PIPE_PLURAL.search(value):
                skipped.append(Skipped("web", key, lang, path,
                                       "looks like a vue-i18n pipe plural (a | b); keep it local or split it"))
                continue
            entry = Entry("web", key, lang, to_named_placeholders(value), path)
            if _PLURAL_SUFFIX.search(key):
                entry.notes.append("i18next plural form: pick the key in app code")
            if "$t(" in value or "@:" in value:
                entry.notes.append("references another key ($t()/@:): resolve it in app code")
            entries.append(entry)
    return entries, skipped
