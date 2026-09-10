#!/usr/bin/env python3
# Stellarium Web Engine
#
# Supplement sky-i18n/zh_cn.json with a hand-curated set of SIMPLIFIED-CHINESE
# star names that were left untranslated (English identity pass-through) in the
# generated catalog.
#
# Why this is a separate, additive step:
#   sky-i18n/<lang>.json is generated (make-sky-i18n.py + make-dso-survey.py's
#   write_i18n). A handful of well-known stars ended up with a real name in
#   zh_tw.json but only the English placeholder in zh_cn.json (e.g. gamma Tau ->
#   "Prima Hyadum" instead of "毕宿四"), so they render in English under
#   Simplified Chinese. The names below are the genuine Chinese asterism (三垣二
#   十八宿 / 星官) names, ported Traditional -> Simplified from zh_tw.json. The
#   other zh_cn gaps are phonetic transliterations of foreign IAU proper names
#   (费利克斯·瓦雷拉, 腓尼基, 沙迦, ...) with no traditional Chinese name, and are
#   intentionally left alone.
#
# PURELY ADDITIVE and IDEMPOTENT: only fills a key that is missing or currently
# an identity pass-through; never overwrites a real translation. Run after the
# generators (or against the committed catalog); the compact on-disk format is
# preserved so the diff is exactly the added names.
#
# Usage:  tools/add-sky-i18n-star-names-zh.py

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "apps", "skydata", "sky-i18n", "zh_cn.json")

# English proper name -> Simplified Chinese asterism name (zh_tw form in comment).
ZH_CN_ASTERISM_NAMES = {
    "Prima Hyadum": "毕宿四",            # gamma Tau      (畢宿四)
    "Castula":      "造父五",            # upsilon2 Cas   (造父五)
    "Atik":         "卷舌四",            # omicron Per    (卷舌四)
    "Beemim":       "天园十三",          # upsilon2 Eri   (天園十三)
    "Theemin":      "天园十二",          # upsilon1 Eri   (天園十二)
    "Minelauva":    "东次相",             # delta Vir      (東次相)
    "Alnair":       "鹤一",              # alpha Gru      (鶴一)
}


def main():
    catalog = json.load(open(OUT, encoding="utf-8"))
    added = []
    for key, value in ZH_CN_ASTERISM_NAMES.items():
        old = catalog.get(key)
        if old is None or old == key:      # missing or untranslated identity
            catalog[key] = value
            added.append("%s -> %s" % (key, value))
    if added:
        json.dump(catalog, open(OUT, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
    print("zh_cn star names: +%d  %s" % (len(added), ", ".join(added) or "(none)"))


if __name__ == "__main__":
    main()
