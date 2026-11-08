"""Shared helpers for extract_strings.py: records, key normalization, value encoding."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

MAX_KEY_LENGTH = 255      # Stringboot key limit (keys: [A-Za-z0-9_.-], 1-255 chars)
MAX_VALUE_LENGTH = 10000  # Stringboot value limit; values must not be blank
UPLOAD_ROWS_PER_FILE = 50 # Bulk Upload accepts at most 50 rows (key + language) per file


@dataclass
class Entry:
    """One string value found in a project file."""
    platform: str          # "android" | "ios" | "web"
    source_key: str        # key as written in the project
    language: str          # Stringboot language code, e.g. "en", "pt-BR"
    value: str             # display text (escapes already decoded)
    source_file: str
    key: str = ""          # normalized Stringboot key (filled later)
    notes: List[str] = field(default_factory=list)


@dataclass
class Skipped:
    """Something that must stay a local resource, with the reason."""
    platform: str
    source_key: str
    language: str
    source_file: str
    reason: str


_TRANSLIT = str.maketrans({"ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE",
                           "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "þ": "th", "ð": "d"})
_CAMEL_1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_NON_KEY = re.compile(r"[^a-z0-9]+")


def normalize_key(raw: str, max_words: Optional[int] = None) -> str:
    """Lower snake_case: [a-z0-9_], starts with a letter, at most MAX_KEY_LENGTH chars.

    Works on every platform: Android resource names allow [a-z0-9_], and iOS/Web accept any key.
    max_words shortens sentence-like keys (iOS apps often use the English text as the key).
    """
    s = raw.translate(_TRANSLIT)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")  # über -> uber
    s = _CAMEL_2.sub(r"\1_\2", s)
    s = _CAMEL_1.sub(r"\1_\2", s)
    s = s.lower()
    s = _NON_KEY.sub("_", s).strip("_")
    if max_words:
        s = "_".join(s.split("_")[:max_words])
    if not s:
        s = "key_" + _short_hash(raw)
    if not s[0].isalpha():
        s = "s_" + s
    if len(s) > MAX_KEY_LENGTH:
        s = s[: MAX_KEY_LENGTH - 9].rstrip("_") + "_" + _short_hash(raw)
    return s


def looks_like_sentence(key: str) -> bool:
    """True for keys that are really English text ("Welcome back!", "Log in")."""
    return bool(re.search(r"\s", key)) or bool(re.search(r"[^\w.\-]", key))


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# Stringboot SDKs unescape, in this order: \n \t \r \" \' \\
_UNREPRESENTABLE_AFTER_BACKSLASH = set("ntr")   # a literal backslash before these can't survive
_DOUBLE_BEFORE = set("\"'\\")                    # a literal backslash before these is stored doubled


def encode_for_stringboot(display: str) -> (str, Optional[str]):
    """Encode display text so the SDKs show it unchanged after unescaping.

    Returns (stored_value, warning). Newlines/tabs/CRs become \\n \\t \\r. A literal backslash
    before a quote, apostrophe or backslash is doubled so it survives. A literal backslash before
    n, t or r can't be represented; it's kept and a warning is returned for a human to check.
    """
    warning = None
    out = []
    for i, ch in enumerate(display):
        if ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\\":
            nxt = display[i + 1] if i + 1 < len(display) else ""
            if nxt and nxt in _UNREPRESENTABLE_AFTER_BACKSLASH:
                warning = "contains a literal backslash before n/t/r, which the SDKs turn into a control character"
                out.append(ch)
            elif nxt and nxt in _DOUBLE_BEFORE:
                out.append("\\\\")
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out), warning


PRINTF = re.compile(r"%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?(?:hh|h|ll|l|L|q|j|z|t)?[@dDiuUxXoOfFeEgGcCsSaAp%]")
NAMED = re.compile(r"\{\{?\s*([A-Za-z_][\w.]*)\s*\}?\}")
# ICU arguments with a type ({n, plural, ...}, {d, date}, {a, number, ::currency/EUR}) and i18next
# formatting ({{- name}}, {{date, datetime}}) need a formatter the SDKs don't have.
ICU_COMPLEX = re.compile(r"\{\s*[A-Za-z_][\w.]*\s*,\s*[A-Za-z]")
I18NEXT_COMPLEX = re.compile(r"\{\{\s*-|\{\{\s*[\w.]+\s*,")
VUE_PIPE_PLURAL = re.compile(r"\s\|\s")


def placeholder_style(value: str) -> Optional[str]:
    """'printf', 'named', 'icu' (plural/select), or None."""
    if ICU_COMPLEX.search(value) or I18NEXT_COMPLEX.search(value):
        return "icu"
    if any(m.group(0) != "%%" for m in PRINTF.finditer(value)):
        return "printf"
    if NAMED.search(value):
        return "named"
    return None


def to_named_placeholders(value: str) -> str:
    """{{name}} (i18next) -> {name}. ICU {name} is already in the shared style."""
    return re.sub(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}", r"{\1}", value)
