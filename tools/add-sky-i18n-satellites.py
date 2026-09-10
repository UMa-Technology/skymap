#!/usr/bin/env python3
# Stellarium Web Engine
#
# Supplement the per-language sky-text catalogs with the SPACE-STATION names
# (ISS + the Chinese Space Station / Tiangong modules), which make-sky-i18n.py
# does not cover (satellites are not in the desktop-Stellarium sky gettext
# domain).
#
# Why this works with no engine change:
#   The on-sky satellite label is rendered through satellite_get_short_name ->
#   designation_cleanup(..., DSGN_TRANSLATE) -> sys_translate("sky", name) (see
#   src/modules/satellites.c / src/designation.c). The frontend's translateFn
#   ignores the domain and looks the string up in the flat skyCatalog, so the
#   baseline data ships ENGLISH msgids ("NAME ISS"/"NAME Tiangong"/...) and this
#   table supplies the localized strings. Keep the msgids in sync with the
#   `name` field of tools/make-tle-satellites.py.
#
# Latin-script languages (de/fr/es/it/pl/hu/ro) intentionally have no entries:
# the msgid ("ISS"/"Tiangong"/"Wentian"/"Mengtian") is already the romanized /
# international form, and translateFn's `|| str` fallback returns it verbatim.
#
# NOTE: the ja/ko/ru transliterations are reasonable defaults but should be
# confirmed by a native reviewer before a public release.
#
# This tool is PURELY ADDITIVE and IDEMPOTENT: it never removes an entry and
# never overwrites an existing translation. After adding entries, re-run
# tools/make-app-fonts.py so the CJK/Cyrillic subset includes any new glyphs.
#
# Usage: tools/add-sky-i18n-satellites.py

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")

# lang -> {english msgid -> translation}. Keys MUST match the "NAME <x>" strings
# in apps/skydata/tle_satellite_baseline.json (post 'NAME ' strip), i.e. the
# `name` field in tools/make-tle-satellites.py.
SATELLITES = {
    "zh_cn": {"ISS": "国际空间站", "Tiangong": "天宫",
              "Wentian": "问天", "Mengtian": "梦天"},
    "zh_tw": {"ISS": "國際太空站", "Tiangong": "天宮",
              "Wentian": "問天", "Mengtian": "夢天"},
    "ja":    {"ISS": "国際宇宙ステーション", "Tiangong": "天宮",
              "Wentian": "問天", "Mengtian": "夢天"},
    "ko":    {"ISS": "국제우주정거장", "Tiangong": "톈궁",
              "Wentian": "원톈", "Mengtian": "멍톈"},
    "ru":    {"ISS": "МКС", "Tiangong": "Тяньгун",
              "Wentian": "Вэньтянь", "Mengtian": "Мэнтянь"},
}


def main():
    for lang, entries in sorted(SATELLITES.items()):
        path = os.path.join(OUT_DIR, lang + ".json")
        if not os.path.isfile(path):
            print("%s: no catalog, skipped" % lang)
            continue
        cat = json.load(open(path, encoding="utf-8"))
        added = []
        for key, val in entries.items():
            if key in cat:  # never overwrite an existing real translation.
                continue
            cat[key] = val
            added.append(key)
        if added:
            # Same compact format as the other patchers; new keys append at the
            # end so the diff is exactly the added names.
            json.dump(cat, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
        print("%s: added %s" % (lang, ", ".join(added) if added else "nothing"))


if __name__ == "__main__":
    main()
