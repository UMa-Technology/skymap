#!/usr/bin/env python3
# Stellarium Web Engine
#
# Supplement the per-language sky-text catalogs with WESTERN CONSTELLATION
# names, which make-sky-i18n.py does not cover.
#
# Why this is a separate, additive step:
#   make-sky-i18n.py builds sky-i18n/<lang>.json from the desktop Stellarium
#   `stellarium-sky` gettext domain (star / DSO / planet names). Constellation
#   names live in a DIFFERENT domain, `stellarium-skycultures`, which that
#   script never reads -- so every constellation label fell back to its raw
#   Latin name (e.g. "Ursa Major") in every non-English language.
#
#   The engine renders a western constellation label by translating its NATIVE
#   Latin name via sys_translate("skyculture", "Ursa Major")
#   (src/modules/skycultures.c: skycultures_get_label -> translate_english_name).
#   The frontend's Module.translateFn ignores the domain and looks the string up
#   in the same flat skyCatalog, so dropping the skycultures translations into
#   sky-i18n/<lang>.json is all that is needed -- no engine change.
#
# This tool is PURELY ADDITIVE and IDEMPOTENT: it never removes an entry and
# never overwrites an existing real translation. It only fills a key that is
# missing or currently an identity pass-through. Existing key order and the
# compact on-disk format are preserved, so the diff is exactly the added names.
#
# Run make-sky-i18n.py first (or keep the committed catalogs), then this.
#
# Usage:
#   tools/add-sky-i18n-constellations.py [STELLARIUM_MASTER_DIR]
# Default STELLARIUM_MASTER: ../stellarium-master (a sibling checkout of Stellarium)

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = sys.argv[1] if len(sys.argv) > 1 else \
    os.environ.get("STELLARIUM_MASTER", os.path.join(ROOT, "..", "stellarium-master"))
# Constellation names live in the `stellarium-skycultures` domain.
PO_DIR = os.path.join(MASTER, "po", "stellarium-skycultures")
OUT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")
WESTERN = os.path.join(ROOT, "apps", "skydata", "skycultures", "western",
                       "index.json")

# Frontend lang code -> .po basename in po/stellarium-skycultures/.
# Matches the languages shipped in sky-i18n/ (incl. hu, ro). `en`/`pt` have no
# catalog here; `es`/`pt` are handled below (they display native Latin as-is).
LANGS = {
    "zh_cn": "zh_CN", "zh_tw": "zh_TW", "pl": "pl", "fr": "fr", "de": "de",
    "ja": "ja", "ru": "ru", "it": "it", "ko": "ko", "es": "es",
    "hu": "hu", "ro": "ro",
}

# Reuse make-sky-i18n.py's .po parser so parsing semantics stay identical
# (context-free, continuation lines, fuzzy handling). The filename has hyphens,
# so load it by path rather than importing as a module name.
_spec = importlib.util.spec_from_file_location(
    "make_sky_i18n", os.path.join(os.path.dirname(__file__), "make-sky-i18n.py"))
_make = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_make)
parse_po = _make.parse_po


def po_dict(po_name):
    """Flat {english_msgid: translation} for one language, dropping fuzzy,
    empty and identity (msgstr == msgid) entries -- same filtering as the
    make-sky-i18n.py sky catalogs. Last non-empty translation wins."""
    path = os.path.join(PO_DIR, po_name + ".po")
    if not os.path.isfile(path):
        print("  !! missing %s" % path)
        return None
    out = {}
    for msgid, msgstr, fuzzy in parse_po(path):
        if fuzzy or not msgstr or msgstr == msgid:
            continue
        out[msgid] = msgstr
    return out


def load_constellation_names():
    """(native, english) pairs for the western skyculture's 88 constellations,
    plus the set of languages that show native Latin as-is (no translation)."""
    doc = json.load(open(WESTERN, encoding="utf-8"))
    pairs = []
    for con in doc.get("constellations", []):
        cn = con.get("common_name") or {}
        pairs.append((cn.get("native"), cn.get("english")))
    prefer_native = set(doc.get("langs_use_native_names") or [])
    return pairs, prefer_native


def main():
    if not os.path.isdir(PO_DIR):
        sys.exit("skyculture po dir not found: %s" % PO_DIR)
    pairs, prefer_native = load_constellation_names()
    print("western constellations: %d  (native display for: %s)"
          % (len(pairs), ", ".join(sorted(prefer_native)) or "none"))

    for lang_code, po_name in LANGS.items():
        out_path = os.path.join(OUT_DIR, lang_code + ".json")
        if not os.path.isfile(out_path):
            print("  -- %-6s no catalog, skipped" % lang_code)
            continue
        # es/pt: engine shows the native Latin name unchanged, so translations
        # would never be queried. Leave the catalog untouched.
        if lang_code in prefer_native:
            print("  == %-6s prefer-native, constellations left as Latin"
                  % lang_code)
            continue
        tr = po_dict(po_name)
        if tr is None:
            continue

        # Preserve existing order/values; json.load keeps insertion order.
        catalog = json.load(open(out_path, encoding="utf-8"))

        def fill(key, value):
            """Set only if missing or currently an untranslated identity."""
            if not key or not value:
                return False
            old = catalog.get(key)
            if old is None or old == key:
                catalog[key] = value
                return True
            return False

        added = native_hit = gap_fill = eng_added = 0
        for native, english in pairs:
            tr_native = tr.get(native)
            tr_english = tr.get(english)
            # Native Latin name is what the engine actually translates.
            # Prefer its own translation; if absent, reuse the english-name
            # translation (same constellation -> a valid localized name).
            value = tr_native or tr_english
            if fill(native, value):
                added += 1
                if tr_native:
                    native_hit += 1
                else:
                    gap_fill += 1
            # Also cover the english name for robustness (english-name branch
            # / alternate name_format_style).
            if fill(english, tr_english):
                eng_added += 1

        json.dump(catalog, open(out_path, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print("  ++ %-6s +%3d native (%d direct, %d via-english) +%d english  "
              "e.g. Ursa Major -> %s"
              % (lang_code, added, native_hit, gap_fill, eng_added,
                 catalog.get("Ursa Major", "(none)")))


if __name__ == "__main__":
    main()
