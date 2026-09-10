#!/usr/bin/env python3
# Stellarium Web Engine
#
# Supplement the per-language sky-text catalogs with the SKY LINE names
# (Meridian / Ecliptic / Equator) and the CARDINAL direction labels
# (N/E/S/W/NE/SE/SW/NW), which make-sky-i18n.py does not cover.
#
# Why this is a separate, additive step:
#   make-sky-i18n.py builds sky-i18n/<lang>.json from the desktop Stellarium
#   `stellarium-sky` gettext domain (star / DSO / planet names). The line
#   names live in the desktop `stellarium` GUI domain, which that script
#   never reads -- so the three named lines fell back to English.
#
#   The engine renders a line label via sys_translate("gui", line->name)
#   (src/modules/lines.c render_label, format 'n' lines: "Meridian",
#   "Ecliptic", "Equator"). The frontend's Module.translateFn ignores the
#   domain and looks the string up in the same flat skyCatalog, so dropping
#   these entries into sky-i18n/<lang>.json is all that is needed -- no
#   engine change.
#
#   The translations are inlined below (standard astronomy terms, aligned
#   with desktop Stellarium's GUI-domain conventions) because the desktop
#   checkout the po pipeline reads from is not always present.
#
# This tool is PURELY ADDITIVE and IDEMPOTENT: it never removes an entry and
# never overwrites an existing real translation. Existing key order and the
# compact on-disk format are preserved, so the diff is exactly the added
# names. After adding entries, re-run tools/make-app-fonts.py so the CJK
# subset includes any new glyphs.
#
# Usage: tools/add-sky-i18n-lines.py

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")

# lang -> {english line name -> translation}. Keys must match the C-side
# line->name strings in src/modules/lines.c exactly.
LINES = {
    "zh_cn": {"Meridian": "子午圈", "Ecliptic": "黄道", "Equator": "天赤道"},
    "zh_tw": {"Meridian": "子午圈", "Ecliptic": "黃道", "Equator": "天赤道"},
    "ja":    {"Meridian": "子午線", "Ecliptic": "黄道", "Equator": "天の赤道"},
    "ko":    {"Meridian": "자오선", "Ecliptic": "황도", "Equator": "적도"},
    "de":    {"Meridian": "Meridian", "Ecliptic": "Ekliptik",
              "Equator": "Äquator"},
    "fr":    {"Meridian": "Méridien", "Ecliptic": "Écliptique",
              "Equator": "Équateur"},
    "es":    {"Meridian": "Meridiano", "Ecliptic": "Eclíptica",
              "Equator": "Ecuador"},
    "it":    {"Meridian": "Meridiano", "Ecliptic": "Eclittica",
              "Equator": "Equatore"},
    "ru":    {"Meridian": "Меридиан", "Ecliptic": "Эклиптика",
              "Equator": "Экватор"},
    "pl":    {"Meridian": "Południk", "Ecliptic": "Ekliptyka",
              "Equator": "Równik"},
    "hu":    {"Meridian": "Meridián", "Ecliptic": "Ekliptika",
              "Equator": "Egyenlítő"},
    "ro":    {"Meridian": "Meridian", "Ecliptic": "Ecliptică",
              "Equator": "Ecuator"},
}

# lang -> {english cardinal -> translation}. Keys must match the C-side
# POINTS[].text strings in src/modules/cardinal.c exactly ("N", "E", "S",
# "W", "NE", "SE", "SW", "NW", rendered via sys_translate("gui", ...)).
# Localised compass abbreviations follow each language's convention (e.g. de
# Ost -> "O", fr Ouest -> "O", ru Cyrillic, hu Észak/Kelet/Dél/Nyugat). Only
# languages whose abbreviations differ from the English letters are listed;
# the rest fall through to the identity (English) form. "en" and "pl" keep the
# international N/E/S/W, so they are intentionally omitted.
CARDINALS = {
    "zh_cn": {"N": "北", "E": "东", "S": "南", "W": "西",
              "NE": "东北", "SE": "东南", "SW": "西南", "NW": "西北"},
    "zh_tw": {"N": "北", "E": "東", "S": "南", "W": "西",
              "NE": "東北", "SE": "東南", "SW": "西南", "NW": "西北"},
    "ja":    {"N": "北", "E": "東", "S": "南", "W": "西",
              "NE": "北東", "SE": "南東", "SW": "南西", "NW": "北西"},
    "ko":    {"N": "북", "E": "동", "S": "남", "W": "서",
              "NE": "북동", "SE": "남동", "SW": "남서", "NW": "북서"},
    "ru":    {"N": "С", "E": "В", "S": "Ю", "W": "З",
              "NE": "СВ", "SE": "ЮВ", "SW": "ЮЗ", "NW": "СЗ"},
    "de":    {"E": "O", "NE": "NO", "SE": "SO"},
    "fr":    {"W": "O", "SW": "SO", "NW": "NO"},
    "es":    {"W": "O", "SW": "SO", "NW": "NO"},
    "it":    {"W": "O", "SW": "SO", "NW": "NO"},
    "hu":    {"N": "É", "E": "K", "S": "D", "W": "Ny",
              "NE": "ÉK", "SE": "DK", "SW": "DNy", "NW": "ÉNy"},
    "ro":    {"W": "V", "SW": "SV", "NW": "NV"},
}

# Merge the gui-domain tables (lines + cardinals) into one per-language dict.
TERMS = {}
for _table in (LINES, CARDINALS):
    for _lang, _entries in _table.items():
        TERMS.setdefault(_lang, {}).update(_entries)


def main():
    for lang, entries in sorted(TERMS.items()):
        path = os.path.join(OUT_DIR, lang + ".json")
        if not os.path.isfile(path):
            print("%s: no catalog, skipped" % lang)
            continue
        cat = json.load(open(path, encoding="utf-8"))
        added = []
        for key, val in entries.items():
            # Never overwrite an existing entry (an identity translation is
            # legitimate here, e.g. de "Meridian" -> "Meridian").
            if key in cat:
                continue
            cat[key] = val
            added.append(key)
        if added:
            # Same compact format as the other patchers/generators; new keys
            # append at the end, so the diff is exactly the added names.
            json.dump(cat, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
        print("%s: added %s" % (lang, ", ".join(added) if added else "nothing"))


if __name__ == "__main__":
    main()
