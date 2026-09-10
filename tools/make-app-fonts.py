#!/usr/bin/env python3
# Stellarium Web Engine
#
# Build the two app font files (regular + bold), each covering ALL sky-text
# scripts in one merged TTF:
#
#   Latin/Greek/Cyrillic : Alibaba Sans (full font, free for commercial use)
#   Hanzi + kana (zh/ja) : Alibaba PuHuiTi 3.0, subset to the glyphs used by
#                          the generated sky catalogs (55-Regular / 85-Bold)
#   Hangul (ko)          : Noto Sans KR (OFL), subset likewise, instanced at
#                          wght 400 / 700
#
# One file per face replaces the old scheme (Roboto Latin + on-demand CJK/KR
# subset fallbacks): the frontend now just loads SkyFont-Regular/Bold at
# startup for every language, and bold CJK text really is bold.
#
# The engine's text rasterizer is stb_truetype (nanovg/fontstash, no
# freetype): TrueType `glyf` outlines only — all sources here are glyf TTFs
# with unitsPerEm=1000, which is what makes the merge safe.
#
# Sources: Alibaba TTFs are NOT downloadable from a stable URL — they are
# the source TTFs tracked in tools/.fontcache/ (see tools/.fontcache/LICENSES.md).
# Noto Sans KR is downloaded once if absent.
#
# Prereq: run tools/make-sky-i18n.py first (this reads its output catalogs).
#
# Usage: tools/make-app-fonts.py
# Output: apps/skymap-web/public/fonts/SkyFont-Regular.ttf
#         apps/skymap-web/public/fonts/SkyFont-Bold.ttf

import json
import os
import sys
import urllib.request

from fontTools import subset
from fontTools.merge import Merger
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT_DIR = os.path.join(ROOT, "apps", "skydata", "sky-i18n")
# Install into the web layer.
OUT_DIRS = [
    os.path.join(ROOT, "apps", "skymap-web", "public", "fonts"),
]
CACHE = os.path.join(ROOT, "tools", ".fontcache")

# A None URL means local-only: it is one of the source TTFs tracked in
# tools/.fontcache/ (see tools/.fontcache/LICENSES.md).
SOURCES = {
    "AlibabaSans-Regular.ttf": None,
    "AlibabaSans-Bold.ttf": None,
    "AlibabaPuHuiTi-3-55-Regular.ttf": None,
    "AlibabaPuHuiTi-3-85-Bold.ttf": None,
    "NotoSansKR.ttf": "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf",
}
CJK_LANGS = ("zh_cn", "zh_tw", "ja", "ko")

FACES = {
    "Regular": {
        "latin": "AlibabaSans-Regular.ttf",
        "cjk": "AlibabaPuHuiTi-3-55-Regular.ttf",
        "kr_wght": 400,
    },
    "Bold": {
        "latin": "AlibabaSans-Bold.ttf",
        "cjk": "AlibabaPuHuiTi-3-85-Bold.ttf",
        "kr_wght": 700,
    },
}


def ensure_source(name):
    path = os.path.join(CACHE, name)
    if os.path.isfile(path) and os.path.getsize(path) > 100_000:
        return path
    os.makedirs(CACHE, exist_ok=True)
    url = SOURCES[name]
    if url is None:
        sys.exit("missing %s — it should be one of the source TTFs tracked "
                 "in tools/.fontcache/ (see tools/.fontcache/LICENSES.md)" % name)
    print("  downloading %s ..." % name)
    urllib.request.urlretrieve(url, path)
    if os.path.getsize(path) < 1_000_000:
        sys.exit("download failed (too small): %s" % url)
    return path


def catalog_codepoints():
    cps = set()
    for lang in CJK_LANGS:
        p = os.path.join(CAT_DIR, lang + ".json")
        if not os.path.isfile(p):
            sys.exit("missing catalog %s — run make-sky-i18n.py first" % p)
        for v in json.load(open(p, encoding="utf-8")).values():
            cps.update(ord(ch) for ch in v)
    return cps


def subset_font(src_path, unicodes, wght=None):
    """Return an in-memory TTFont subset to `unicodes` (variable fonts are
    pinned to the given weight first)."""
    font = TTFont(src_path)
    if "fvar" in font:
        font = instancer.instantiateVariableFont(
            font, {"wght": wght or 400}, inplace=False)
    opts = subset.Options()
    opts.glyph_names = False        # post format 3: drop glyph names (smaller)
    opts.hinting = False            # drop hinting (sky labels don't need it)
    opts.legacy_kern = False
    opts.name_legacy = False
    opts.layout_features = []       # no shaping needed for these name strings
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.recalc_timestamp = False
    opts.drop_tables += ["DSIG"]
    ss = subset.Subsetter(options=opts)
    ss.populate(unicodes=sorted(unicodes))
    ss.subset(font)
    strip_var_tables(font)
    # Deterministic output: don't stamp head.modified on save, so re-running
    # the (automated) chain with unchanged inputs is byte-identical and never
    # dirties the repo.
    font.recalcTimestamp = False
    return font


def strip_var_tables(font):
    """Drop variable-font leftovers the merger cannot handle (instancing a
    pinned weight can keep an HVAR/VarStore shell behind — GDEF included),
    plus OpenType layout tables: stb_truetype never reads them and they only
    add merge hazards + bytes."""
    # stb_truetype only reads head/hhea/hmtx/maxp/cmap/loca/glyf (+kern);
    # everything else is merge hazard + dead bytes. Vertical metrics and
    # hinting programs exist only in SOME sources, which trips the merger's
    # missing-table logic — dropping them everywhere sidesteps that too.
    for t in ("fvar", "avar", "gvar", "cvar", "HVAR", "VVAR", "MVAR", "STAT",
              "GDEF", "GSUB", "GPOS", "BASE", "DSIG",
              "vhea", "vmtx", "VORG", "VDMX", "cvt ", "fpgm", "prep", "gasp"):
        if t in font:
            del font[t]


def build_face(face, cfg, cps):
    latin_src = ensure_source(cfg["latin"])
    cjk_src = ensure_source(cfg["cjk"])
    kr_src = ensure_source("NotoSansKR.ttf")

    latin_cmap = set(TTFont(latin_src, lazy=True).getBestCmap().keys())
    cjk_cmap = set(TTFont(cjk_src, lazy=True).getBestCmap().keys())
    kr_cmap = set(TTFont(kr_src, lazy=True).getBestCmap().keys())

    # Each merged component keeps only what the previous ones lack, so the
    # merger never sees duplicate codepoints (first font wins anyway).
    cjk_cps = (cps & cjk_cmap) - latin_cmap
    kr_cps = ((cps - cjk_cmap) & kr_cmap) - latin_cmap
    dropped = cps - latin_cmap - cjk_cmap - kr_cmap
    if dropped:
        print("  %s: %d catalog codepoints uncovered: %s" % (
            face, len(dropped), "".join(chr(c) for c in sorted(dropped))))

    latin = TTFont(latin_src)
    strip_var_tables(latin)
    latin.recalcTimestamp = False
    tmp = []
    for i, f in enumerate([latin,
                           subset_font(cjk_src, cjk_cps),
                           subset_font(kr_src, kr_cps, cfg["kr_wght"])]):
        p = os.path.join(CACHE, "_tmp_merge_%d.ttf" % i)
        f.save(p)
        tmp.append(p)

    merged = Merger().merge(tmp)
    merged.recalcTimestamp = False
    # The merger stamps head.created/modified with the current time, which
    # would make every (automated) re-run dirty the repo; pin them to the
    # latin source's stable values instead.
    src_head = TTFont(latin_src, lazy=True)["head"]
    merged["head"].created = src_head.created
    merged["head"].modified = src_head.modified
    for p in tmp:
        os.remove(p)

    n_cmap = len(merged.getBestCmap())
    out = None
    for out_dir in OUT_DIRS:
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "SkyFont-%s.ttf" % face)
        merged.save(out)
    print("  SkyFont-%s.ttf: %6.1f KB, %d codepoints (latin full + %d CJK + "
          "%d KR subset) -> %d dirs" % (face, os.path.getsize(out) / 1024.0,
                                        n_cmap, len(cjk_cps), len(kr_cps),
                                        len(OUT_DIRS)))


def main():
    cps = catalog_codepoints()
    print("catalog codepoints: %d" % len(cps))
    for face, cfg in FACES.items():
        build_face(face, cfg, cps)


if __name__ == "__main__":
    main()
