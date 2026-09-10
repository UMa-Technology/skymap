#!/usr/bin/env python3
# Stellarium Web Engine
#
# Reconcile the zh star names against the reference list
# dev_docs/star_names.zh_CN.fab (format: `HIP|_("名字") n`, one star may list
# several names — the first is the primary; trailing [宿名]/?/* markers are
# metadata and stripped).
#
# Per product decision (2026-07-16): the .fab file is the naming authority.
# For every fab star that already has a name chain (western common_names
# "HIP n" -> english key -> sky-i18n zh value), if the current zh_cn value
# matches none of the fab names for that star, it is REPLACED by the fab
# primary name (zh_tw follows via opencc s2t). Untranslated identity entries
# (e.g. "Haedus" -> "Haedus") are filled the same way.
#
# Exceptions (fab suspected typos) keep the current value — see EXCEPTIONS.
#
# Coverage note: stars in the fab but absent from the star survey cannot be
# rendered at all and are ignored; adding NEW chains is add-chinese-star-
# names.py's job (chinese skyculture source), not this reconciler's.
#
# Idempotent. Runs inside tools/finish-sky-i18n.py after the port and before
# the cleaners.
#
# Usage: tools/apply-star-names-fab.py

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAB = os.path.join(ROOT, "dev_docs", "star_names.zh_CN.fab")
SKYCULTURE = os.path.join(ROOT, "apps", "skydata", "skycultures", "western",
                          "index.json")
I18N = os.path.join(ROOT, "apps", "skydata", "sky-i18n")

# english-key -> keep the current value (fab value considered a typo).
# Rasalhague (α Oph): the asterism is 侯; the fab writes 候.
EXCEPTIONS = {"Rasalhague"}

MARKERS = re.compile(r"\s*(?:\[[^\]]*\]|[*?？﹖])+\s*$")


def parse_fab():
    fab = {}
    for line in open(FAB, encoding="utf-8"):
        m = re.match(r'\s*(\d+)\|_\("([^"]+)"\)', line)
        if m:
            name = MARKERS.sub("", m.group(2))
            if name:
                fab.setdefault(int(m.group(1)), []).append(name)
    return fab


def main():
    from opencc import OpenCC
    s2t = OpenCC("s2t").convert

    fab = parse_fab()
    cn = json.load(open(SKYCULTURE, encoding="utf-8"))["common_names"]
    cat_cn = json.load(open(os.path.join(I18N, "zh_cn.json"),
                            encoding="utf-8"))
    cat_tw = json.load(open(os.path.join(I18N, "zh_tw.json"),
                            encoding="utf-8"))

    changed = []
    for hip, names in sorted(fab.items()):
        entry = cn.get("HIP %d" % hip)
        if not entry:
            continue
        eng = entry[0].get("english")
        if not eng or eng in EXCEPTIONS:
            continue
        cur = cat_cn.get(eng)
        if cur is not None and cur != eng and cur in names:
            continue                       # already one of the fab names
        new = names[0]
        if cur == new:
            continue
        cat_cn[eng] = new
        cat_tw[eng] = s2t(new)
        changed.append("%s: %s -> %s" % (eng, cur, new))

    if changed:
        for path, cat in ((os.path.join(I18N, "zh_cn.json"), cat_cn),
                          (os.path.join(I18N, "zh_tw.json"), cat_tw)):
            json.dump(cat, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
    print("fab reconcile: %d value(s) updated%s" % (
        len(changed), " — " + "; ".join(changed[:15]) if changed else ""))


if __name__ == "__main__":
    main()
