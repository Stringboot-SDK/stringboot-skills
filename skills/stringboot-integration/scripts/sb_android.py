"""Read Android string resources (res/values*/*.xml)."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from sb_common import Entry, Skipped

_OLD_CODES = {"iw": "he", "in": "id", "ji": "yi"}
# ISO 639-1 codes (plus Android's legacy iw/in/ji). Two/three-letter folder qualifiers that aren't
# languages (values-car, values-hdr) must not become language codes.
_ISO_639_1 = set("""aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu
cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz
ia id ie ig ii ik in io is it iu iw ja ji jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln
lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt
qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts
tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu""".split())
# Three-letter codes Android accepts as old-style qualifiers
_ISO_639_3_COMMON = {"fil", "haw", "yue", "ast", "ckb", "kab", "chr", "ceb", "gsw", "nds", "sat", "mni"}
_ALLOWED_CHILD_TAGS = {"g"}  # <xliff:g> wraps placeholders; its text is kept
_XLIFF = "{urn:oasis:names:tc:xliff:document:1.2}"


def language_for_values_dir(dirname: str, default_language: str) -> Optional[str]:
    """values -> default; values-fr -> fr; values-pt-rBR -> pt-BR; values-b+sr+Latn -> sr-Latn.

    Returns None for folders whose first qualifier isn't a language (values-night, values-v21, ...).
    """
    if dirname == "values":
        return default_language
    quals = dirname.split("-")[1:]
    if not quals:
        return None
    first = quals[0]
    if first.startswith("b+"):
        parts = first[2:].split("+")
        parts[0] = _OLD_CODES.get(parts[0], parts[0])
        return "-".join(parts)
    if not (first in _ISO_639_1 or first in _ISO_639_3_COMMON):
        return None
    lang = _OLD_CODES.get(first, first)
    if len(quals) > 1 and re.fullmatch(r"r[A-Z]{2}|r\d{3}", quals[1]):
        lang += "-" + quals[1][1:]
    return lang


def decode_android(raw: str) -> str:
    """Apply aapt's rules: quotes keep whitespace, escapes \\n \\t \\' \\" \\\\ \\@ \\? \\uXXXX."""
    out = []
    quoted = False
    i = 0
    pending_space = False
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if pending_space:
                out.append(" ")
                pending_space = False
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", raw[i + 2:i + 6] or ""):
                out.append(chr(int(raw[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
            i += 1
            continue
        if ch.isspace() and not quoted:
            pending_space = bool(out)
            i += 1
            continue
        if pending_space:
            out.append(" ")
            pending_space = False
        out.append(ch)
        i += 1
    return "".join(out)


def _element_text(el: ET.Element) -> Tuple[Optional[str], Optional[str]]:
    """Raw text of a <string>, keeping <xliff:g> content. Returns (text, problem)."""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag.replace(_XLIFF, "")
        if tag not in _ALLOWED_CHILD_TAGS:
            return None, "contains markup <%s>; the SDK returns plain text" % tag
        parts.append(ET.tostring(child, encoding="unicode", method="text"))
    return "".join(parts), None


def read_android(res_dirs: List[str], default_language: str) -> Tuple[List[Entry], List[Skipped]]:
    entries: List[Entry] = []
    skipped: List[Skipped] = []
    for res in res_dirs:
        for dirname in sorted(os.listdir(res)):
            if not dirname.startswith("values"):
                continue
            folder = os.path.join(res, dirname)
            if not os.path.isdir(folder):
                continue
            lang = language_for_values_dir(dirname, default_language)
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".xml"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    raw_file = f.read()
                if "<string" not in raw_file and "<plurals" not in raw_file:
                    continue
                try:
                    root = ET.fromstring(raw_file)
                except ET.ParseError as e:
                    skipped.append(Skipped("android", "*", lang or dirname, path, "XML parse error: %s" % e))
                    continue
                html_names = {m.group(1) for m in re.finditer(
                    r'<string(?=[\s>])[^>]*\bname="([^"]+)"[^>]*>(.*?)</string>', raw_file, re.S)
                    if "<![CDATA[" in m.group(2) or "&lt;" in m.group(2)}
                seen_products = set()
                for el in root:
                    key = el.get("name", "")
                    if el.tag in ("plurals", "string-array", "array", "integer-array"):
                        skipped.append(Skipped("android", key, lang or dirname, path,
                                               "<%s> isn't supported by Stringboot; keep it local" % el.tag))
                        continue
                    if el.tag != "string":
                        continue
                    if lang is None:
                        skipped.append(Skipped("android", key, dirname, path,
                                               "folder %s is a configuration variant, not a language" % dirname))
                        continue
                    if el.get("translatable") == "false":
                        skipped.append(Skipped("android", key, lang, path, 'translatable="false"; keep it local'))
                        continue
                    if key in html_names:
                        skipped.append(Skipped("android", key, lang, path, "CDATA/escaped HTML value; keep it local"))
                        continue
                    if (key, lang) in seen_products:
                        skipped.append(Skipped("android", key, lang, path,
                                               'another product="%s" variant; only the first one is uploaded'
                                               % el.get("product", "")))
                        continue
                    seen_products.add((key, lang))
                    text, problem = _element_text(el)
                    if problem:
                        skipped.append(Skipped("android", key, lang, path, problem + "; keep it local"))
                        continue
                    stripped = (text or "").strip()
                    if stripped[:1] in ("@", "?"):
                        skipped.append(Skipped("android", key, lang, path,
                                               "references another resource (%s); keep it local" % stripped))
                        continue
                    value = decode_android(text or "")
                    entry = Entry("android", key, lang, value, path)
                    if el.get("formatted") == "false":
                        entry.notes.append('formatted="false"')
                    if "%%" in value:
                        entry.notes.append("contains %%: it shows as %% unless the app calls String.format")
                    entries.append(entry)
    return entries, skipped
