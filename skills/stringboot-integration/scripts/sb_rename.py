"""Rename keys in local resource files so the SDKs' offline fallback keeps matching.

Android: <string name="old"> in res/values*/*.xml, plus R.string.old and @string/old references
         in .kt/.java/.xml files of the same source set.
iOS:     "old" = ...; in *.lproj/*.strings, and keys in *.xcstrings.
Web code and iOS code references are left to the agent (key-map.json), because their call
patterns vary too much for a safe mechanical rewrite.
"""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict

from sb_ios import _SKIP_DIRS


def _write_if_changed(path, old_text, new_text):
    if new_text != old_text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return 1
    return 0


def _android(mapping, res_dirs):
    changed = 0
    renames = {old: new for old, new in mapping.items() if old != new}
    if not renames:
        return 0
    # R.string.x and @string/x use the resource name with dots turned into underscores
    ref_renames = dict(renames)
    for old, new in renames.items():
        ref_renames.setdefault(old.replace(".", "_"), new)
    name_attr = re.compile(r'(<(?:string|plurals|string-array)\b[^>]*\bname=")([^"]+)(")')
    ref = re.compile(r"(?<![A-Za-z0-9_])(R\.string\.|@string/)([A-Za-z0-9_.]+)\b")
    for res in res_dirs:
        source_set = os.path.dirname(os.path.abspath(res))          # .../src/main
        module_src = os.path.dirname(source_set)                     # .../src
        for dirpath, dirnames, filenames in os.walk(module_src):
            dirnames[:] = [d for d in dirnames if d not in ("build", ".gradle")]
            for name in filenames:
                if not name.endswith((".kt", ".java", ".xml")):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                new = text
                if os.path.basename(dirpath).startswith("values") and name.endswith(".xml"):
                    new = name_attr.sub(lambda m: m.group(1) + renames.get(m.group(2), m.group(2)) + m.group(3), new)
                new = ref.sub(lambda m: m.group(1) + ref_renames.get(m.group(2), m.group(2)), new)
                changed += _write_if_changed(path, text, new)
    return changed


def _detect_encoding(raw):
    """Encoding to read and write a .strings file with, keeping its BOM. None for binary plists."""
    if raw.startswith(b"bplist"):
        return None
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"            # Python keeps the BOM on write
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if len(raw) > 1 and raw[1:2] == b"\x00":
        return "utf-16-le"
    return "utf-8"


def _escape_strings_key(key):
    return key.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _ios(mapping, roots):
    changed = 0
    renames = {old: new for old, new in mapping.items() if old != new}
    if not renames:
        return 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                path = os.path.join(dirpath, name)
                if name.endswith(".strings") and dirpath.endswith(".lproj") and name != "InfoPlist.strings":
                    with open(path, "rb") as f:
                        raw = f.read()
                    encoding = _detect_encoding(raw)
                    if encoding is None:
                        continue  # compiled binary .strings: nothing to rename
                    text = raw.decode(encoding)
                    new = text
                    for old, new_key in renames.items():
                        pattern = re.compile(r'(^|\n)(\s*)"%s"(\s*=)' % re.escape(_escape_strings_key(old)))
                        new = pattern.sub(lambda m: '%s%s"%s"%s' % (m.group(1), m.group(2), new_key, m.group(3)), new)
                    if new != text:
                        with open(path, "wb") as f:
                            f.write(new.encode(encoding))
                        changed += 1
                elif name.endswith(".xcstrings"):
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                    doc = json.loads(text, object_pairs_hook=OrderedDict)
                    strings = doc.get("strings", {})
                    renamed = OrderedDict()
                    for key, item in strings.items():
                        new_key = renames.get(key, key)
                        if new_key != key:
                            locs = item.setdefault("localizations", OrderedDict())
                            source = doc.get("sourceLanguage", "en")
                            if source not in locs:  # the old key was also the source text: keep that text
                                locs[source] = {"stringUnit": {"state": "translated", "value": key}}
                        renamed[new_key] = item
                    doc["strings"] = renamed
                    new = json.dumps(doc, indent=2, ensure_ascii=False, separators=(",", " : ")) + "\n"
                    changed += _write_if_changed(path, text, new)
    return changed


def rename_local(key_map, android_res_dirs, ios_roots):
    changed = 0
    if android_res_dirs:
        changed += _android(key_map.get("android", {}), android_res_dirs)
    if ios_roots:
        changed += _ios(key_map.get("ios", {}), ios_roots)
    return changed
