"""Read iOS/macOS strings: *.lproj/*.strings, *.xcstrings (String Catalogs), *.stringsdict."""
from __future__ import annotations

import json
import os
import re
from typing import Iterator, List, Optional, Tuple

from sb_common import Entry, Skipped

_LEGACY_LPROJ = {"english": "en", "french": "fr", "german": "de", "spanish": "es",
                 "italian": "it", "japanese": "ja", "dutch": "nl"}
_SKIP_DIRS = {"Pods", "Carthage", "DerivedData", ".build", "build", "node_modules", ".git"}


def language_for_lproj(dirname: str, default_language: str) -> str:
    name = dirname[:-len(".lproj")]
    if name == "Base":
        return default_language
    return _LEGACY_LPROJ.get(name.lower(), name.replace("_", "-"))


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(b"bplist"):
        raise ValueError("compiled binary .strings file")
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"), (b"\xef\xbb\xbf", "utf-8-sig")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc)
    if len(data) > 1 and data[1:2] == b"\x00":
        return data.decode("utf-16-le")
    return data.decode("utf-8")


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "0": "\0"}


def parse_strings_file(text: str) -> Iterator[Tuple[str, str]]:
    """Yield (key, value) pairs from a .strings file (comments, quoted/unquoted tokens, escapes)."""
    i, n = 0, len(text)

    def skip_ws(i):
        while i < n:
            if text[i].isspace():
                i += 1
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = n if end < 0 else end + 2
            elif text.startswith("//", i):
                end = text.find("\n", i)
                i = n if end < 0 else end + 1
            else:
                break
        return i

    def token(i):
        if text[i] == '"':
            out, i = [], i + 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    c = text[i + 1]
                    if c in "Uu" and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6]):
                        out.append(chr(int(text[i + 2:i + 6], 16)))
                        i += 6
                        continue
                    out.append(_ESC.get(c, c))
                    i += 2
                    continue
                out.append(text[i])
                i += 1
            return "".join(out), i + 1
        m = re.match(r"[^\s=;\"]+", text[i:])
        if not m:
            raise ValueError("unexpected character %r at offset %d" % (text[i], i))
        return m.group(0), i + len(m.group(0))

    while True:
        i = skip_ws(i)
        if i >= n:
            return
        key, i = token(i)
        i = skip_ws(i)
        if i < n and text[i] == ";":  # "key"; means value == key
            yield key, key
            i += 1
            continue
        if i >= n or text[i] != "=":
            raise ValueError("expected '=' after %r" % key)
        i = skip_ws(i + 1)
        value, i = token(i)
        i = skip_ws(i)
        if i < n and text[i] == ";":
            i += 1
        yield key, value


def _walk(root: str) -> Iterator[Tuple[str, List[str], List[str]]]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        yield dirpath, dirnames, filenames


def read_ios(roots: List[str], default_language: str) -> Tuple[List[Entry], List[Skipped]]:
    entries: List[Entry] = []
    skipped: List[Skipped] = []
    for root in roots:
        for dirpath, _, filenames in _walk(root):
            lproj = os.path.basename(dirpath) if dirpath.endswith(".lproj") else None
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if name.endswith(".xcstrings"):
                    _read_xcstrings(path, default_language, entries, skipped)
                elif name.endswith(".stringsdict"):
                    skipped.append(Skipped("ios", "*", lproj or "?", path,
                                           ".stringsdict plurals aren't supported by Stringboot; keep them local"))
                elif name.endswith(".strings") and lproj:
                    _read_strings(path, name, language_for_lproj(lproj, default_language), entries, skipped)
    _add_source_text_keys(entries, default_language)
    return entries, skipped


def _add_source_text_keys(entries, default_language):
    """Apps that use English text as keys often have no default-language .strings entry: the key
    itself is shown. Recreate that entry so the default language gets uploaded too."""
    have_default = {e.source_key for e in entries if e.platform == "ios" and e.language == default_language}
    seen = set()
    for e in list(entries):
        if e.platform != "ios" or e.source_key in have_default or e.source_key in seen:
            continue
        if re.search(r"\s", e.source_key):
            seen.add(e.source_key)
            extra = Entry("ios", e.source_key, default_language, e.source_key, e.source_file)
            extra.notes.append("no %s entry: the key text is the %s value; add it to %s.lproj/Localizable.strings "
                               "after renaming" % (default_language, default_language, default_language))
            entries.append(extra)


def _read_strings(path, name, lang, entries, skipped):
    table = name[:-len(".strings")]
    if table == "InfoPlist":
        skipped.append(Skipped("ios", "*", lang, path, "InfoPlist.strings is read by the system; keep it local"))
        return
    try:
        pairs = list(parse_strings_file(_read_text(path)))
    except ValueError as e:
        skipped.append(Skipped("ios", "*", lang, path, "couldn't parse: %s" % e))
        return
    for key, value in pairs:
        entry = Entry("ios", key, lang, value, path)
        if table != "Localizable":
            entry.notes.append("table %s: the SDK's offline fallback only reads Localizable" % table)
        entries.append(entry)


def _read_xcstrings(path, default_language, entries, skipped):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    source = doc.get("sourceLanguage", default_language)
    table = os.path.basename(path)[:-len(".xcstrings")]
    for key, item in (doc.get("strings") or {}).items():
        if item.get("shouldTranslate") is False:
            skipped.append(Skipped("ios", key, source, path, "shouldTranslate is false; keep it local"))
            continue
        locs = item.get("localizations") or {}
        if source not in locs and key:
            locs = dict(locs)
            locs[source] = {"stringUnit": {"value": key}}  # Xcode uses the key as the source text
        for lang, loc in locs.items():
            if "variations" in loc or "substitutions" in loc:
                skipped.append(Skipped("ios", key, lang, path,
                                       "plural/device variations aren't supported by Stringboot; keep them local"))
                continue
            value = (loc.get("stringUnit") or {}).get("value")
            if value is None:
                continue
            entry = Entry("ios", key, lang, value, path)
            if table != "Localizable":
                entry.notes.append("table %s: the SDK's offline fallback only reads Localizable" % table)
            entries.append(entry)
