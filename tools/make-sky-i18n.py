#!/usr/bin/env python3
# Stellarium Web Engine
#
# Build per-language sky-text translation catalogs (JSON) for the web frontend
# from the desktop Stellarium `stellarium-sky` gettext domain.
#
# The engine translates every sky label per-frame via sys_translate("sky", str),
# which routes to the frontend's Module.translateFn(domain, str). This script
# produces the { "<english>": "<translated>" } maps that translateFn looks up.
#
# Usage:
#   tools/make-sky-i18n.py [STELLARIUM_MASTER_DIR]
# Default STELLARIUM_MASTER: ../stellarium-master (a sibling checkout of Stellarium)
# Output: apps/skydata/sky-i18n/<lang>.json  (served at /skydata/sky-i18n/)

import json
import os
import re
import sys

# Repo root = parent of this tools/ dir.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = sys.argv[1] if len(sys.argv) > 1 else \
    os.environ.get("STELLARIUM_MASTER", os.path.join(ROOT, "..", "stellarium-master"))
PO_DIR = os.path.join(MASTER, "po", "stellarium-sky")
OUT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")

# The 11 requested languages. Key = frontend lang code (lowercased .po basename),
# Value = the .po file basename in po/stellarium-sky/. `en` is the identity
# source (no .po, translateFn returns the English string) so it is omitted.
LANGS = {
    "zh_cn": "zh_CN", "zh_tw": "zh_TW", "pl": "pl", "fr": "fr", "de": "de",
    "ja": "ja", "ru": "ru", "it": "it", "ko": "ko", "es": "es",
}

# --- Minimal .po parser -----------------------------------------------------
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(s):
    out = []
    it = iter(range(len(s)))
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def parse_po(path):
    """Yield (msgid, msgstr, fuzzy) tuples. Concatenates continuation lines.
    Ignores msgctxt (the engine looks strings up context-free)."""
    msgid = None
    msgstr = None
    target = None          # which buffer continuation lines append to
    fuzzy = False
    entries = []

    def flush():
        if msgid:  # skip header (msgid "")
            entries.append((msgid, msgstr or "", fuzzy))

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("#"):
                if stripped.startswith("#,") and "fuzzy" in stripped:
                    fuzzy = True
                continue
            if stripped == "":
                flush()
                msgid = msgstr = target = None
                fuzzy = False
                continue
            if stripped.startswith("msgid_plural"):
                target = None            # ignore plurals for a names catalog
                continue
            if stripped.startswith("msgid "):
                # new entry begins; flush the previous one if the blank line
                # separator was missing
                if target is not None:
                    flush()
                    msgid = msgstr = None
                    fuzzy = fuzzy if target == "id" else False
                m = _STR_RE.search(stripped)
                msgid = _unescape(m.group(1)) if m else ""
                target = "id"
                continue
            if stripped.startswith("msgstr"):   # msgstr or msgstr[0]
                m = _STR_RE.search(stripped)
                msgstr = _unescape(m.group(1)) if m else ""
                target = "str"
                continue
            if stripped.startswith("msgctxt"):
                target = "ctxt"              # parsed but ignored
                continue
            # continuation line: a bare "..."
            m = _STR_RE.match(stripped)
            if m and target in ("id", "str"):
                if target == "id":
                    msgid += _unescape(m.group(1))
                else:
                    msgstr = (msgstr or "") + _unescape(m.group(1))
    flush()
    return entries


def build(lang_code, po_name):
    path = os.path.join(PO_DIR, po_name + ".po")
    if not os.path.isfile(path):
        print("  !! missing %s" % path)
        return None
    catalog = {}
    for msgid, msgstr, fuzzy in parse_po(path):
        if fuzzy or not msgstr:
            continue                       # untranslated -> English fallback
        # Keep last non-empty; identity entries are harmless but pruned to save space.
        if msgstr != msgid:
            catalog[msgid] = msgstr
    return catalog


def main():
    if not os.path.isdir(PO_DIR):
        sys.exit("po dir not found: %s" % PO_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    for lang_code, po_name in LANGS.items():
        cat = build(lang_code, po_name)
        if cat is None:
            continue
        out = os.path.join(OUT_DIR, lang_code + ".json")
        # Compact, deterministic (sorted keys) so re-runs produce stable diffs.
        with open(out, "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
        size = os.path.getsize(out)
        total += size
        sop = cat.get("String of Pearls", "(none)")
        print("  %-6s %5d strings  %6.1f KB   String of Pearls -> %s"
              % (lang_code, len(cat), size / 1024.0, sop))
    print("total catalogs: %.1f KB in %s" % (total / 1024.0, OUT_DIR))

    # A full regen wipes everything the additive patchers contributed, so
    # always run the post-build patch/cleanup chain (idempotent).
    import subprocess
    subprocess.check_call([sys.executable,
                           os.path.join(os.path.dirname(
                               os.path.abspath(__file__)),
                               "finish-sky-i18n.py")])


if __name__ == "__main__":
    main()
