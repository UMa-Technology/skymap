#!/usr/bin/env python3
# Strip English/Latin contamination from the CJK sky-text catalogs so star / DSO
# labels show only the native name.
#
# The desktop-Stellarium-derived sky-i18n values for zh_cn / zh_tw carry three
# bad shapes (e.g. star labels showing "Procyon (南河三)" or "王良四 Mesartim"):
#   (a) "English (CJK)"          -> keep the CJK inside the parens
#   (b) "CJK (Latin/ASCII)"      -> drop the trailing "(...)"
#   (c) "CJK <Capitalised word>" -> drop the trailing Latin proper word
#
# It deliberately PRESERVES legitimate mixes: Roman numerals (仙女座 II),
# component letters (剑鱼座30 B), catalog prefixes (AFGL 333星云, Arp环), and any
# parenthetical/word that is itself CJK. Only zh_cn / zh_tw are touched (ja / ko
# use parenthetical originals as a deliberate style).
#
# Usage:
#   tools/clean-sky-i18n-latin.py            # dry-run: print proposed changes
#   tools/clean-sky-i18n-latin.py --apply    # write the files

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")
LANGS = ["zh_cn", "zh_tw"]

# MPC comet designation keys ("1P/...", "C/1995 O1 (...)") — see
# add-sky-i18n-comets.py, which owns these entries.
COMET_KEY = re.compile(r"^(\d+[PCDXAI](-[A-Z0-9]+)?/|[PCDXAI]/\d{4} )")

CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")
# A trailing Latin *proper word* glued to a native name (spaced OR not, e.g.
# "王良四 Mesartim" and "娄宿三Hamal"): the head must end in a CJK char, then an
# optional space, then a word starting uppercase and containing a lowercase
# letter (so all-caps Roman numerals / abbreviations and single component or
# exoplanet letters like "II" / "B" / "c" are left alone). Allows an internal
# hyphen/apostrophe.
TRAIL_WORD = re.compile(
    r"^(.*[㐀-鿿぀-ヿ가-힯])\s*([A-Z][A-Za-z]*[a-z][A-Za-z'\-]*)$")
# "<ascii> (<contains CJK>)"  -> the parenthetical
PAREN_CJK = re.compile(r"^[\x00-\x7F]+[（(]\s*([^）)]*?)\s*[）)]$")
# "<...CJK...> (<ascii, no CJK>)" -> strip the parenthetical
PAREN_ASCII = re.compile(r"^(.*?)\s*[（(]\s*([^）)]*)[）)]$")


def clean_value(v):
    s = v.strip()
    if not CJK.search(s):
        return v  # nothing native to protect; leave catalog/latin names as-is

    # (a) English (CJK) -> the CJK part.
    m = PAREN_CJK.match(s)
    if m and CJK.search(m.group(1)):
        return m.group(1).strip()

    # (b) CJK (Latin) -> drop the parenthetical, but only if the head has CJK and
    # the parenthetical is purely non-CJK (so we never drop a real native name).
    m = PAREN_ASCII.match(s)
    if m and CJK.search(m.group(1)) and not CJK.search(m.group(2)):
        head = m.group(1).strip()
        if head:
            s = head  # fall through so (c) can also trim a trailing word

    # (c) CJK <Capitalised Latin word> -> drop the trailing word, keeping any
    # native prefix. Repeat so "阿多尼斯 Adonis" style double tails collapse.
    while True:
        m = TRAIL_WORD.match(s)
        if not m:
            break
        head = m.group(1).strip()
        if not CJK.search(head):
            break  # would strip into a non-native remainder; stop
        s = head

    return s if s else v


def main():
    apply = "--apply" in sys.argv
    grand = 0
    for lang in LANGS:
        path = os.path.join(OUT_DIR, lang + ".json")
        cat = json.load(open(path, encoding="utf-8"))
        changes = []
        for k, v in cat.items():
            # Comet entries (keys shaped like an MPC designation) legitimately
            # mix the Latin designation with a localized name part
            # ("C/2025 A4 (泛星)", "100P/哈特雷") — never "clean" those, or
            # the designation gets stripped and different comets collide on
            # the same bare name. add-sky-i18n-comets.py owns these keys.
            if COMET_KEY.match(k):
                continue
            nv = clean_value(v)
            if nv != v:
                changes.append((k, v, nv))
        print("\n===== %s: %d changes =====" % (lang, len(changes)))
        for k, v, nv in changes:
            print("  %-24s %r -> %r" % (k, v, nv))
        grand += len(changes)
        if apply and changes:
            for k, v, nv in changes:
                cat[k] = nv
            # Preserve on-disk format: existing order, compact, non-ascii.
            json.dump(cat, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
    print("\ntotal %d changes%s" % (grand, "" if apply else " (dry-run; --apply to write)"))


if __name__ == "__main__":
    main()
