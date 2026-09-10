#!/usr/bin/env python3
# Stellarium Web Engine
#
# Strip trailing Chinese-skyculture certainty / annotation markers from CJK sky
# names in sky-i18n, so map labels show clean names.
#
# The Chinese skyculture data (skycultures/chinese/index.json, and the desktop
# Stellarium zh_TW catalog) tags some star/asterism native names with trailing
# markers that are metadata, not part of the name:
#   *          - a source annotation             (天庾二*   -> 天庾二)
#   ?          - uncertain HIP identification     (天庾增二? -> 天庾增二)
#   [宿名]     - the lunar mansion / enclosure it belongs to
#                                                 (积尸[胃宿] -> 积尸,
#                                                  玉衡[北斗五] -> 玉衡)
# These flow through into sky-i18n/{zh_cn,zh_tw}.json (via add-chinese-star-
# names.py and the upstream zh_TW catalog) and render verbatim on the chart.
#
# This tool strips such trailing markers from every CJK catalog value. It is
# idempotent and safe: a value is only changed when stripping leaves a non-empty
# result, and only the trailing marker run is removed (never mid-name text).
#
# Run LAST, after the sky-i18n generators / patches.
#
# Usage:  tools/clean-sky-i18n-markers.py

import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(ROOT, "apps", "skydata", "sky-i18n")
LANGS = ("zh_cn", "zh_tw", "ja", "ko")

# One or more trailing markers: a [...] annotation, or a '*' / '?' flag
# (half- or full-width), plus any surrounding spaces.
TRAILING = re.compile(r"\s*(?:\[[^\]]*\]|[*?？﹖])+\s*$")

# Enclosure-wall star translations from the desktop zh catalogs carry BOTH the
# positional name and the traditional proper name, space-joined ("天市右垣七 蜀",
# "紫微左垣四 上弼"). The chart label should show just the positional name, like
# every other star of the same asterism. Only exactly this shape is touched:
# an all-CJK "<...垣><chinese numeral(s)>" head + one space + an all-CJK tail.
WALL_DOUBLE = re.compile(r"^([㐀-鿿]*垣[一二三四五六七八九十]+) [㐀-鿿]+$")


def main():
    for lang in LANGS:
        path = os.path.join(I18N, lang + ".json")
        if not os.path.isfile(path):
            continue
        cat = json.load(open(path, encoding="utf-8"))
        total, samples = 0, []
        for k, v in cat.items():
            nv = TRAILING.sub("", v)
            nv = WALL_DOUBLE.sub(r"\1", nv)
            if nv != v and nv:                       # changed and non-empty
                cat[k] = nv
                total += 1
                if len(samples) < 6:
                    samples.append("%s->%s" % (v, nv))
        json.dump(cat, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print("  %-6s cleaned %d  e.g. %s" % (lang, total, ", ".join(samples) or "(none)"))


if __name__ == "__main__":
    main()
