#!/usr/bin/env python3
# Stellarium Web Engine
#
# Run EVERY post-build patch / cleanup pass for the sky-text data, in order.
# make-sky-i18n.py and make-dso-survey.py call this automatically at the end,
# so no fix depends on anyone remembering a manual step. History shows why:
# survey rebuilds silently lost the manual LMC injection (254fd4bc) and
# resurrected dirty zh names ("太子Pherkad", "天市右垣七 蜀", "玉衡[北斗五]")
# because the patch/cleanup passes were memory-driven.
#
# Every step is PURELY ADDITIVE and IDEMPOTENT, so running this chain after
# any build (or standalone) is always safe.
#
# Steps that need resources beyond the repo are SOFT: they are skipped with a
# loud warning when their inputs are absent, instead of failing the build —
# the committed data already contains their last output, and additive patches
# survive both generators (which never delete keys).
#
# Usage: tools/finish-sky-i18n.py

import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
MASTER = os.environ.get("STELLARIUM_MASTER",
                        "/Users/larry/code/stellarium-master")

# (script, args, hard, precondition-or-None)
# hard=True: repo-self-contained, a failure fails the build.
# hard=False: depends on external inputs; warn + continue on failure.
STEPS = [
    # Port 星官 names (chinese skyculture -> western common_names + zh
    # catalogs). Needs the python `opencc` package for s2t. NOTE: this one
    # is dry-run by default — forgetting --apply here once left 2658 names
    # unapplied while the chain looked green.
    ("add-chinese-star-names.py", ["--apply"], False, None),
    # Reconcile zh star names against the dev_docs/star_names.zh_CN.fab
    # reference (the naming authority per product decision). Needs opencc.
    ("apply-star-names-fab.py", [], False, None),
    # Fill zh_cn star names that only exist in zh_tw (hand-curated list).
    ("add-sky-i18n-star-names-zh.py", [], True, None),
    # Meridian / Ecliptic / Equator line names (inlined, 12 languages).
    ("add-sky-i18n-lines.py", [], True, None),
    # Space-station names (ISS + CSS/Tiangong modules), inlined per language.
    ("add-sky-i18n-satellites.py", [], True, None),
    # Comet names from the curated table in the objects_catalogs repo
    # (the same source that feeds the App's objects-names.json).
    ("add-sky-i18n-comets.py", [], False, None),
    # Western constellation names from the desktop-Stellarium po checkout.
    ("add-sky-i18n-constellations.py", [], False,
     os.path.join(MASTER, "po", "stellarium-skycultures")),
    # Strip Latin tails ("太子Pherkad") and English (CJK) wrappers.
    ("clean-sky-i18n-latin.py", ["--apply"], True, None),
    # Strip trailing markers ("玉衡[北斗五]", "天庾二*") and enclosure-wall
    # double names ("天市右垣七 蜀").
    ("clean-sky-i18n-markers.py", [], True, None),
    # Refresh the merged app fonts for the (possibly changed) glyph set.
    # Needs fonttools+brotli and the Alibaba TTFs in tools/.fontcache/.
    ("make-app-fonts.py", [], False, None),
]


def main():
    failed_soft = []
    for script, args, hard, precondition in STEPS:
        if precondition and not os.path.isdir(precondition):
            print("== %s: SKIPPED (missing %s)" % (script, precondition))
            failed_soft.append(script)
            continue
        print("== %s" % script)
        ret = subprocess.call([sys.executable,
                               os.path.join(TOOLS, script)] + args)
        if ret != 0:
            if hard:
                sys.exit("finish-sky-i18n: %s failed (exit %d)" % (script, ret))
            failed_soft.append(script)
            print("WARNING: %s failed (exit %d) — continuing; the committed "
                  "data keeps its last output. Fix its inputs and re-run "
                  "tools/finish-sky-i18n.py." % (script, ret))
    if failed_soft:
        print("finish-sky-i18n: done with %d skipped/failed soft step(s): %s"
              % (len(failed_soft), ", ".join(failed_soft)))
    else:
        print("finish-sky-i18n: all steps done")


if __name__ == "__main__":
    main()
