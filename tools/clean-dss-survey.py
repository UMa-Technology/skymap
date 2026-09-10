#!/usr/bin/env python3
# Stellarium Web Engine
#
# Semi-automatic DSS plate-seam COLOUR-BLOCK cleaner.
#
# Digitized Sky Survey (DSS2 color) tiles carry baked-in plate-seam artifacts:
# straight-edged rectangular patches where adjacent Schmidt-plate backgrounds
# don't match in brightness/colour. Fully-automatic detection of these across all
# 3840 tiles proved infeasible without also flagging real galaxies/nebulae (a
# single 512^2 tile is the wrong scale -- plate seams are a global, multi-tile
# phenomenon; see the internal design notes). So this
# tool is SEMI-automatic: you pass the tiles you've confirmed contain colour
# blocks, and it repairs only the order-3 parent regions those tiles fall in.
#
# It processes per ORDER-3 PARENT REGION, coherently: it stitches the region's
# four order-4 children into one 1024^2 image, segments the coarse background into
# colour regions (chroma k-means) and Poisson-levels the artificial casts (removing
# the straight steps while preserving stars, real gradients, and per-tile DC), then
# splits the cleaned image back into the four order-4 children and area-downsamples
# it to the order-3 tile. Cleaning the whole region at once avoids inducing a seam
# between independently-cleaned children and keeps order-3 == downsample(order-4).
# Every tile outside a cleaned region is byte-copied. Originals (--src) are never
# modified; output goes to --out.
#
# It also removes satellite/aircraft TRAILS (streaks) from confirmed tiles, by profile
# subtraction (remove each channel's own perpendicular streak profile; robust at any
# colour, preserves crossing stars). See tools/clean_dss/destreak.py.
#
# Usage:
#   python tools/clean-dss-survey.py --src SRC --out OUT \
#       [--seam-tiles 3/161 ...] [--streak-tiles 3/7 ...] [--tiles 3/7:streak 3/161:seam] \
#       [--k 6] [--report DIR]
# Each tile entry is <order>/<npix>[:class]; it maps to its order-3 parent region (an
# order-4 entry n -> region n//4). --tiles takes the picker's typed 3/N:class tokens
# (class in streak|defect|seam); --seam-tiles/--streak-tiles are shorthands. Seams are
# cleaned before streaks so a tile flagged both composes. Balanced seam strength is --k 5..7.
import argparse
import glob
import os
import shutil
import sys
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.clean_dss.io import load_rgb, save_webp_q90
from tools.clean_dss.background import coarse_bg
from tools.clean_dss.segment import segment
from tools.clean_dss.correct import correct_seam, apply_correction
from tools.clean_dss.pyramid import child_ids
from tools.clean_dss.validate import stars_preserved, streak_cleared, no_ghost_edges
from tools.clean_dss import streaks, destreak


def _npix(path):
    return int(os.path.basename(path)[4:-5])


def parse_seam_regions(entries):
    """entries: iterable of '<order>/<npix>'. Return the set of order-3 parent
    regions to clean (an order-4 entry maps to its parent npix//4)."""
    regions = set()
    for e in entries:
        try:
            o_s, n_s = e.split("/")
            o, n = int(o_s), int(n_s)
        except ValueError:
            raise SystemExit(f"bad --seam-tiles entry {e!r}; expected <order>/<npix>, e.g. 3/161")
        if o == 3:
            regions.add(n)
        elif o == 4:
            regions.add(n // 4)
        else:
            raise SystemExit(f"unsupported order in --seam-tiles entry {e!r} (only 3 or 4 are shipped)")
    return regions


VALID_CLASSES = ("streak", "defect", "seam")


def parse_typed_tiles(entries):
    """entries: iterable of '<order>/<npix>[:class]' (class in streak|defect|seam,
    default seam for back-compat). Returns {class: set(order-3 parent regions)}."""
    out = {c: set() for c in VALID_CLASSES}
    for e in entries:
        tok, _, cls = e.partition(":")
        cls = cls or "seam"
        if cls not in VALID_CLASSES:
            raise SystemExit(f"bad class {cls!r} in {e!r}; expected one of {VALID_CLASSES}")
        try:
            o_s, n_s = tok.split("/"); o, n = int(o_s), int(n_s)
        except ValueError:
            raise SystemExit(f"bad tile entry {e!r}; expected <order>/<npix>[:class], e.g. 3/7:streak")
        if o == 3:
            out[cls].add(n)
        elif o == 4:
            out[cls].add(n // 4)
        else:
            raise SystemExit(f"unsupported order in {e!r} (only 3 or 4 are shipped)")
    return out


def clean_region(src, out, parent, k, changed_o4, changed_o3, warnings):
    """Coherently clean one order-3 parent region and write its cleaned order-4
    children + rebuilt order-3 tile to `out`. Appends `parent` to `warnings` if the
    automated star-preservation guardrail trips."""
    kids = child_ids(parent)                                  # [4p, 4p+1, 4p+2, 4p+3]
    paths = [f"{src}/Norder4/Dir0/Npix{c}.webp" for c in kids]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"region {parent}: missing order-4 children {missing}")
    c0, c1, c2, c3 = (load_rgb(p) for p in paths)
    # stitch in the verified HiPS layout (TL,TR,BL,BR)=(c0,c2,c1,c3) -> 1024x1024
    big = np.concatenate([np.concatenate([c0, c2], axis=1),
                          np.concatenate([c1, c3], axis=1)], axis=0)
    bg = coarse_bg(big)
    cleaned = apply_correction(big, bg, correct_seam(bg, segment(bg, k=k)))
    # guardrail: cleaning must preserve bright stars (compared at the SAME 1024^2
    # resolution, so no rebuild-resampling confound). Warn, don't abort -- the human
    # reviews the contact sheet, but a tripped guardrail flags a region to scrutinise.
    if not stars_preserved(big, cleaned):
        warnings.append(parent)
    # split back to children in [0,1,2,3] order: [TL, BL, TR, BR]
    quads = [cleaned[:512, :512], cleaned[512:, :512], cleaned[:512, 512:], cleaned[512:, 512:]]
    for c, q in zip(kids, quads):
        dst = f"{out}/Norder4/Dir0/Npix{c}.webp"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        save_webp_q90(np.ascontiguousarray(q), dst)
        changed_o4.add(c)
    parent_img = cv2.resize(cleaned, (512, 512), interpolation=cv2.INTER_AREA)
    dst3 = f"{out}/Norder3/Dir0/Npix{parent}.webp"
    os.makedirs(os.path.dirname(dst3), exist_ok=True)
    save_webp_q90(parent_img, dst3)
    changed_o3.add(parent)


STREAK_SCORE_MIN = 6.0        # legacy scanner-score floor; superseded by the is_trail gate
                              # below (retained for reference/back-compat imports)
# Trail-vs-DSO gate: only fits the discriminator judges is_trail=True are cleaned (PER-FIT),
# so a galaxy edge / nebula filament / dense-field false positive the scanner fired on is
# kept. Faint-but-real trails (median-projection support `prom` below FAINT_PROM_THRESH, e.g.
# region 227 prom~12, 491 prom~2.6, 40 segs prom~4-10) sit below the corrector's default 2.5
# support gate, so they are cleaned with the lowered FAINT_GROW_THRESH to actually reach sky.
FAINT_PROM_THRESH = 20.0
FAINT_GROW_THRESH = 1.2


def _stitch_children(paths):
    """Stitch 4 order-4 children into the 1024^2 region (TL,TR,BL,BR)=(c0,c2,c1,c3)."""
    c0, c1, c2, c3 = (load_rgb(p) for p in paths)
    return np.concatenate([np.concatenate([c0, c2], axis=1),
                           np.concatenate([c1, c3], axis=1)], axis=0)


def clean_streak_region(src, out, parent, changed_o4, changed_o3, warnings):
    """Remove detected trails from one order-3 region (its 1024^2 4-children stitch) by
    profile subtraction, then split + rebuild. Re-detects trails on the working image
    (the human already confirmed this region; dense tiles are excluded by the human) and
    cleans each scanner fit the discriminator judges is_trail (PER-FIT gating; see the gate
    comment below and discriminate.THINSCORE_MIN). Reads a child from `out` if a prior step
    already cleaned it (seam->streak compose), else from `src`. Skips (writes nothing) if NO
    fit is is_trail. Appends `parent` to `warnings` if a guardrail trips."""
    kids = child_ids(parent)

    def pick(c):
        po = f"{out}/Norder4/Dir0/Npix{c}.webp"
        return po if os.path.exists(po) else f"{src}/Norder4/Dir0/Npix{c}.webp"

    paths = [pick(c) for c in kids]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"region {parent}: missing order-4 children {missing}")
    big = _stitch_children(paths)
    scan = streaks.scan_image(big)
    groups = scan["groups"]
    # trail-vs-DSO gate (PER-FIT): the discriminator (is_trail) is the authoritative
    # real-trail signal and supersedes the crude STREAK_SCORE_MIN score heuristic. We gate
    # each fit independently and clean exactly the is_trail fits -- NOT the whole region on
    # its top fit. Per-fit is both safer and more complete:
    #   - safe: the reject ceiling across ALL fits of every DSO/dense tile is thinscore 1.70
    #     (< THINSCORE_MIN=3.0, verified), so an individual galaxy edge / nebula filament /
    #     dense-field segment never reaches is_trail -- a DSO region simply yields zero kept
    #     fits and is skipped, so cleaning never erases real astronomy.
    #   - complete: it recovers FRAGMENTED real trails whose TOP fit is a non-trail. E.g.
    #     region 40's top fit is a vertical plate seam (thinscore 0.39, is_trail=False) while
    #     its real trail is 3 collinear segments at thinscore 3.14/3.82 -- the old top-fit
    #     gate skipped the whole region; per-fit keeps and cleans those segments. It still
    #     admits faint whole reals below the old 6.0 score floor (region 227, score ~5.5).
    # If NO fit is is_trail the region is a scanner false positive and is skipped.
    kept = [g for g in groups if g.get("is_trail")]
    if not kept:
        print(f"region {parent}: no trail to clean "
              f"({len(groups)} candidate(s) rejected as DSO/false-positive) — skipped")
        return
    fits = [g["fit"] for g in kept]
    # faint-but-real trails (median-projection support `prom` below FAINT_PROM_THRESH) get a
    # lowered support gate so the corrector actually takes them down to sky. `prom` is the
    # median-over-track Radon peak of the SAME star-suppressed high-pass the corrector's
    # grow_thresh gates on, so it directly measures how far the trail's median support sits
    # above sky: faint/dashed reals (227 prom~12, 491 prom~2.6, 40 segs prom~4-10) fall below
    # the corrector's default 2.5 gate and need the lower grow_thresh; it is the RIGHT key
    # here (exc_p90 is a p90 excess that stays HIGH for dashed reals like 491~99 and would
    # miss them).
    grow = [FAINT_GROW_THRESH if g.get("features", {}).get("prom", 99.0) < FAINT_PROM_THRESH
            else None for g in kept]
    cleaned, union, info = destreak.destreak_image(big, fits, grow_thresh=grow)
    if not stars_preserved(big, cleaned):
        warnings.append(parent)
    if not streak_cleared(big, cleaned, union) or not no_ghost_edges(big, cleaned, union):
        warnings.append(parent)
    quads = [cleaned[:512, :512], cleaned[512:, :512], cleaned[:512, 512:], cleaned[512:, 512:]]
    for c, q in zip(kids, quads):
        dst = f"{out}/Norder4/Dir0/Npix{c}.webp"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        save_webp_q90(np.ascontiguousarray(q), dst)
        changed_o4.add(c)
    parent_img = cv2.resize(cleaned, (512, 512), interpolation=cv2.INTER_AREA)
    dst3 = f"{out}/Norder3/Dir0/Npix{parent}.webp"
    os.makedirs(os.path.dirname(dst3), exist_ok=True)
    save_webp_q90(parent_img, dst3)
    changed_o3.add(parent)
    print(f"region {parent}: destreaked {len(fits)} trail(s)")


def _region_worker(task):
    """Top-level worker for parallel region cleaning (fork pool). Each region writes its own
    output files independently; the worker returns fresh (changed_o4, changed_o3, warnings)
    for the parent to aggregate. cv2 threads are pinned to 1 so tile-level parallelism owns
    the cores instead of oversubscribing."""
    kind, src, out, parent, k = task
    cv2.setNumThreads(1)
    o4, o3, warn = set(), set(), []
    if kind == "seam":
        clean_region(src, out, parent, k, o4, o3, warn)
    else:
        clean_streak_region(src, out, parent, o4, o3, warn)
    return o4, o3, warn


def _run_regions(kind, parents, src, out, k, jobs):
    """Clean a list of same-class regions, in parallel across `jobs` fork processes when it
    pays off, else serially. Returns aggregated (changed_o4, changed_o3, warnings). Falls back
    to serial if the pool can't start (e.g. this module was loaded under a non-importable name
    via importlib, so the worker isn't picklable) -- correctness is identical, just slower."""
    o4, o3, warnings = set(), set(), []
    tasks = [(kind, src, out, p, k) for p in parents]
    results = None
    if jobs > 1 and len(tasks) > 1:
        try:
            ctx = mp.get_context("fork")
            with ProcessPoolExecutor(max_workers=min(jobs, len(tasks)), mp_context=ctx) as ex:
                results = list(ex.map(_region_worker, tasks))
        except Exception as e:                                  # pragma: no cover - env dependent
            print(f"note: parallel pool unavailable ({type(e).__name__}); running serially",
                  file=sys.stderr)
            results = None
    if results is None:
        results = [_region_worker(t) for t in tasks]
    for c4, c3, w in results:
        o4 |= c4; o3 |= c3; warnings.extend(w)
    return o4, o3, warnings


def copy_untouched(src, out, order, changed, jobs=1):
    """Copy every source tile not in `changed` into the staging tree. Parallelised over a
    thread pool (I/O bound) for large trees; serial for small sets / jobs<=1."""
    paths = [p for p in sorted(glob.glob(f"{src}/Norder{order}/Dir0/*.webp")) if _npix(p) not in changed]
    os.makedirs(f"{out}/Norder{order}/Dir0", exist_ok=True)

    def _cp(p):
        shutil.copy2(p, f"{out}/Norder{order}/Dir0/Npix{_npix(p)}.webp")

    if jobs > 1 and len(paths) > 64:
        with ThreadPoolExecutor(max_workers=min(jobs * 4, 32)) as ex:
            list(ex.map(_cp, paths))
    else:
        for p in paths:
            _cp(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Semi-automatic DSS artifact cleaner (plate seams + trails)")
    ap.add_argument("--src", required=True, help="source survey tree (never modified)")
    ap.add_argument("--out", required=True, help="output (staging) survey tree")
    ap.add_argument("--seam-tiles", nargs="+", default=[], metavar="ORDER/NPIX",
                    help="tiles confirmed to contain colour blocks, e.g. 3/161")
    ap.add_argument("--streak-tiles", nargs="+", default=[], metavar="ORDER/NPIX",
                    help="tiles confirmed to contain satellite/aircraft trails, e.g. 3/7")
    ap.add_argument("--tiles", nargs="+", default=[], metavar="ORDER/NPIX:CLASS",
                    help="typed flags straight from the picker, e.g. 3/7:streak 3/161:seam")
    ap.add_argument("--k", type=int, default=6, help="seam colour clusters per region (5-7 balanced)")
    ap.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1,
                    help="parallel worker processes for region cleaning (default: all CPU cores)")
    ap.add_argument("--report", default=None, help="write before/after contact sheets here")
    a = ap.parse_args(argv)

    typed = parse_typed_tiles(list(a.tiles)
                              + [e if ":" in e else f"{e}:seam" for e in a.seam_tiles]
                              + [e if ":" in e else f"{e}:streak" for e in a.streak_tiles])
    if not (typed["seam"] or typed["streak"] or typed["defect"]):
        raise SystemExit("nothing to do: pass --seam-tiles, --streak-tiles, and/or --tiles")
    if typed["defect"]:
        print(f"NOTE: defect tiles {sorted(typed['defect'])} are out of scope for this tool version — ignored")

    jobs = max(1, a.jobs)
    changed_o4, changed_o3, warnings = set(), set(), []
    # seams first (a streak region may compose on a seam-cleaned parent), then streaks;
    # regions within a class are independent (disjoint children) so they run in parallel.
    for kind in ("seam", "streak"):
        o4, o3, w = _run_regions(kind, sorted(typed[kind]), a.src, a.out, a.k, jobs)
        changed_o4 |= o4; changed_o3 |= o3; warnings.extend(w)

    copy_untouched(a.src, a.out, 4, changed_o4, jobs)
    copy_untouched(a.src, a.out, 3, changed_o3, jobs)
    if os.path.exists(f"{a.src}/properties"):
        shutil.copy2(f"{a.src}/properties", f"{a.out}/properties")

    print(f"cleaned {len(typed['seam'])} seam + {len(typed['streak'])} streak region(s): "
          f"{len(changed_o4)} order-4 + {len(changed_o3)} order-3 tiles changed")
    if warnings:
        print(f"WARNING: guardrail tripped for region(s) {sorted(set(warnings))}; inspect their contact sheets")
    if a.report:
        from tools.clean_dss.report import write_contact_sheet
        write_contact_sheet(a.src, a.out, changed_o4, a.report)
        print(f"contact sheets -> {a.report}")
    return changed_o4


if __name__ == "__main__":
    main()
