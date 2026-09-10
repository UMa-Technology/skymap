#!/usr/bin/env python3
# Stellarium Web Engine
#
# Supplement the sky-text catalogs with COMET names, which no other generator
# covers (the engine names comets from the MPC CometEls.txt
# Designation_and_name column — English only — and the desktop-Stellarium
# gettext domains have no comet entries, so labels/cards stayed English).
#
# The naming authority is the curated table in the external App-catalog repo:
# <objects_catalogs>/names/comet_names.json (v2), with two sections:
#   "comets":     curated multilingual names for famous comets
#                 ("1P/Halley" -> 哈雷彗星 / ハレー彗星 / 핼리 혜성 ...)
#   "name_parts": per-part transliterations used to RULE-GENERATE zh names
#                 for every other comet in apps/skydata/CometEls.txt whose
#                 name parts are all known:
#                   "C/2025 K1 (ATLAS)"   -> "C/2025 K1 (阿特拉斯)"
#                   "333P/LINEAR"         -> "333P/林尼尔"
#                   "58P/Jackson-Neujmin" -> "58P/杰克逊-诺伊明"
# The same file feeds the App's objects-names.json via catalog_builder, so
# both sides stay consistent. Curated entries whose comet is not in the
# current MPC snapshot are still written (they return near perihelion).
#
# ADDITIVE + reconciling (the table is the authority for comet keys) and
# IDEMPOTENT. Runs inside tools/finish-sky-i18n.py; soft-skips when the
# objects_catalogs checkout is absent.
#
# Usage: tools/add-sky-i18n-comets.py

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(ROOT, "apps", "skydata", "sky-i18n")
COMETELS = os.path.join(ROOT, "apps", "skydata", "CometEls.txt")
SOURCE = os.environ.get("COMET_NAMES_JSON", os.path.join(ROOT, "..", "objects_catalogs", "names", "comet_names.json"))

CURATED_LANGS = ("zh_cn", "zh_tw", "ja", "ko", "ru")
GENERATED_LANGS = ("zh_cn", "zh_tw")

_NUMBERED = re.compile(r"^(\d+[PCDXAI](?:-[A-Z0-9]+)?)/(.+)$")
_PAREN = re.compile(r"^(.+\()([^)]+)(\)\s*)$")


def _translate_parts(name, parts, lang):
    out = []
    for tok in (t.strip() for t in name.split("-")):
        tr = parts.get(tok, {}).get(lang)
        if not tr:
            return None
        out.append(tr)
    return "-".join(out)


def localized_designation(desgn, parts, lang):
    m = _NUMBERED.match(desgn)
    if m:
        tr = _translate_parts(m.group(2), parts, lang)
        return "%s/%s" % (m.group(1), tr) if tr else None
    m = _PAREN.match(desgn)
    if m:
        tr = _translate_parts(m.group(2), parts, lang)
        return "%s%s%s" % (m.group(1), tr, m.group(3)) if tr else None
    return None


def cometels_designations():
    desgns = set()
    for line in open(COMETELS, encoding="utf-8", errors="replace"):
        if len(line) > 102:
            d = line[102:158].strip()
            if d:
                desgns.add(d)
    return sorted(desgns)


def main():
    if not os.path.isfile(SOURCE):
        sys.exit("missing %s — clone/update the objects_catalogs repo "
                 "(or set COMET_NAMES_JSON)" % SOURCE)
    data = json.load(open(SOURCE, encoding="utf-8"))
    curated, parts = data["comets"], data["name_parts"]

    # lang -> {designation: localized name}
    wanted = {lang: {} for lang in CURATED_LANGS}
    for desgn, tr in curated.items():
        for lang in CURATED_LANGS:
            if tr.get(lang):
                wanted[lang][desgn] = tr[lang]
    for desgn in cometels_designations():
        if desgn in curated:
            continue
        for lang in GENERATED_LANGS:
            name = localized_designation(desgn, parts, lang)
            if name:
                wanted[lang][desgn] = name

    # A key shaped like a comet designation can only have come from this
    # tool, so any such key no longer in the wanted set is stale (e.g. a
    # transliteration part later removed from the table) and gets dropped.
    comet_key = re.compile(r"^(\d+[PCDXAI](-[A-Z0-9]+)?/|[PCDXAI]/\d{4} )")

    for lang in CURATED_LANGS:
        path = os.path.join(I18N, lang + ".json")
        cat = json.load(open(path, encoding="utf-8"))
        changed = removed = 0
        for desgn in [k for k in cat
                      if comet_key.match(k) and k not in wanted[lang]]:
            del cat[desgn]
            removed += 1
        for desgn, name in sorted(wanted[lang].items()):
            if cat.get(desgn) == name:
                continue
            cat[desgn] = name
            changed += 1
        if changed or removed:
            json.dump(cat, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
        print("%s: %d comet name(s) written, %d stale removed"
              % (lang, changed, removed))


if __name__ == "__main__":
    main()
