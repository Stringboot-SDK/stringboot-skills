#!/usr/bin/env python3
"""Self-test for extract_strings.py against tests/fixture. Run: python3 tests/test_extract.py"""
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "stringboot-integration", "scripts", "extract_strings.py")


def run(work, *extra):
    cmd = [sys.executable, SCRIPT, "--default-language", "en", "--android", "app/src/main/res",
           "--ios", "ios", "--web", "web/locales", "--out", "out", *extra]
    subprocess.run(cmd, cwd=work, check=True, capture_output=True, text=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(work, "out", "upload", "*.csv"))):
        with open(f, encoding="utf-8", newline="") as fh:
            r = list(csv.reader(fh))
        assert r[0] == ["key", "value", "languageCode"], r[0]
        assert len(r) - 1 <= 50
        rows += r[1:]
    return {(k, l): v for k, v, l in rows}, rows


def main():
    work = tempfile.mkdtemp()
    shutil.copytree(os.path.join(HERE, "fixture"), work, dirs_exist_ok=True)
    values, rows = run(work)
    checks = {
        ("welcome_message", "en"): "Welcome to Demo",          # camelCase key, whitespace collapsed
        ("apostrophe", "en"): "Don't stop\\nnow",               # \' decoded, newline stored as \n
        ("ellipsis", "en"): "Loading…",                    # \u escape decoded
        ("at_sign", "en"): "@home",                             # \@ decoded
        ("greeting", "en"): "Hello, %1$s!",                     # xliff:g text kept
        ("settings_title", "en"): "Settings",                   # dotted name normalized
        ("welcome_message", "pt-BR"): "Bem-vindo",              # values-pt-rBR -> pt-BR
        ("log_in", "en"): "Log in",                             # xcstrings source text from key
        ("welcome_back", "en"): "Welcome back!",                # sentence key without en entry
        ("welcome_back", "fr"): "Bon retour !",                 # UTF-16 .strings
        ("home_subtitle", "en"): "Hi {name}",                   # {{name}} -> {name}
    }
    for k, v in checks.items():
        assert values.get(k) == v, (k, values.get(k), v)
    keys = {k for k, _ in values}
    for absent in ("app_name", "ref", "bold", "cdata", "items", "colors", "brand", "items_count", "tags",
                   "cart_summary", "count"):
        assert absent not in keys, absent
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", k) for k in keys), keys
    assert len(rows) == len(values), "duplicate key+language rows"
    assert rows[0][2] == "en", "default language must come first"
    report = open(os.path.join(work, "out", "report.md"), encoding="utf-8").read()
    assert "Conflicts (2)" in report and "printf placeholders" in report

    run(work, "--rename-local")
    main_kt = open(os.path.join(work, "app/src/main/java/com/ex/Main.kt")).read()
    layout = open(os.path.join(work, "app/src/main/res/layout/main.xml")).read()
    assert "R.string.welcome_message" in main_kt and "R.string.settings_title" in main_kt
    assert "@string/welcome_message" in layout
    fr = open(os.path.join(work, "ios/App/fr.lproj/Localizable.strings"), "rb").read().decode("utf-16")
    assert '"welcome_back" = "Bon retour !";' in fr
    xc = json.load(open(os.path.join(work, "ios/App/Localizable.xcstrings")))
    assert "log_in" in xc["strings"] and "Log in" not in xc["strings"]
    print("OK: %d rows, all checks passed" % len(rows))


if __name__ == "__main__":
    main()
