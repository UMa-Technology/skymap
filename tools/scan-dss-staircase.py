#!/usr/bin/env python3
# Stellarium Web Engine
#
# Scan the offline DSS survey's Norder4 tiles for STAIRCASE / BLOCKY plate-seam
# artifacts (sharp axis-aligned steps in the sky *background*, e.g. the gear-
# shaped seam fixed in Npix1175), and build a human-review annotation picker.
#
# Detector (calibrated on the pre-fix Npix1175, score 16966; clean tiles 0):
#   star-robust background (9px opening + blur)  ->  fine-minus-coarse residual
#   -> strong residual in DIM background = "background step" pixels
#   -> bright-star exclusion discs (halo rims ring otherwise)
#   -> keep only large, elongated connected components
#   score = sum(component area x mean |step|)
#
# Output (default --picker apps/skymap-web/public/staircase-picker):
#   candidates.json           ranked [{npix, score}] above --min-score
#   imgs/NpixN.png            x4-amplified render (raw tiles are near black)
#   imgs/NpixN_ov.png         detector-overlay render (what/where it flagged)
#   picker_annotate.html      annotation UI (deployed from the template file
#                             tools/staircase_picker_annotate.html)
#
# Workflow: run this, open http://localhost:8080/staircase-picker/picker_annotate.html
# confirm & draw a centre line + width over each artifact strip, export the
# annotations JSON, then run tools/fix-dss-strips.py with it.
#
# Usage:
#   python3 tools/scan-dss-staircase.py [--min-score 1500] [--max-tiles 400]
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.clean_dss.io import load_rgb  # noqa: E402

DSS = os.path.join(ROOT, "apps", "skydata", "surveys", "dss")
N4 = 3072  # 12 * 4^4


def tile_score(img_rgb, details=False):
    L = img_rgb.astype(np.float32).mean(2)
    op = cv2.morphologyEx(L, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    bgf = cv2.GaussianBlur(op, (0, 0), 2)
    bgc = cv2.GaussianBlur(bgf, (0, 0), 10)
    resid = bgf - bgc
    hits = (np.abs(resid) > 2.2) & (bgf < 45)
    core = (L > 90).astype(np.uint8)
    core = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)))
    hits &= core == 0
    hits[:4, :] = hits[-4:, :] = False
    hits[:, :4] = hits[:, -4:] = False
    m = cv2.morphologyEx(hits.astype(np.uint8), cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    # two anti-Milky-Way discriminators (galactic-band texture caused massive
    # false positives without them; see the v1 scan):
    #  - axis alignment: staircase edges are axis-aligned (upscaled blocks);
    #    genuine sky texture has isotropic gradient directions
    #  - whole-tile texture: seams sit in FLAT sky (texture ~0.05); the galactic
    #    band lights up everywhere (0.35-0.45) -> strong tile-level penalty
    gx = cv2.Sobel(resid, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(resid, cv2.CV_32F, 0, 1, ksize=3)
    ax, ay = np.abs(gx), np.abs(gy)
    strong = (ax + ay) > 1.5
    aligned = (np.maximum(ax, ay) > 3 * np.minimum(ax, ay)) & strong
    texture = float((np.abs(resid) > 1.5).mean())
    tex_pen = 1.0 + 40.0 * max(0.0, texture - 0.08)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    score, keep = 0.0, np.zeros_like(m)
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        w, h = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if area < 150 or (w * w + h * h) ** 0.5 < 48:
            continue
        comp = lab == i
        ns = int((comp & strong).sum())
        if ns < 30:
            continue
        af = float((comp & aligned).sum()) / ns
        if af < 0.45:
            continue
        score += area * float(np.abs(resid)[comp].mean())
        keep[comp] = 1
    score /= tex_pen
    return (score, keep) if details else score


def _score_one(npix):
    try:
        return npix, float(tile_score(load_rgb(
            f"{DSS}/Norder4/Dir0/Npix{npix}.webp")))
    except Exception:
        return npix, -1.0


def render_candidate(npix, out_dir):
    img = load_rgb(f"{DSS}/Norder4/Dir0/Npix{npix}.webp")
    _, keep = tile_score(img, details=True)
    amp = np.clip(img.astype(np.float32) * 4, 0, 255).astype(np.uint8)
    cv2.imwrite(f"{out_dir}/Npix{npix}.png", amp[..., ::-1])
    ov = amp.copy()
    edge = cv2.dilate(keep, np.ones((3, 3), np.uint8)) - keep
    ov[keep > 0] = (0.55 * ov[keep > 0] + 0.45 *
                    np.array([255, 70, 50])).astype(np.uint8)
    ov[edge > 0] = [255, 70, 50]
    cv2.imwrite(f"{out_dir}/Npix{npix}_ov.png", ov[..., ::-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=float, default=1500)
    ap.add_argument("--max-tiles", type=int, default=400)
    ap.add_argument("--picker", default=os.path.join(
        ROOT, "apps", "skymap-web", "public", "staircase-picker"))
    args = ap.parse_args()

    with ProcessPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(_score_one, range(N4), chunksize=64))
    scores = {p: s for p, s in res}
    if all(s < 0 for s in scores.values()):
        sys.exit("every tile failed to load - wrong survey path?")
    cand = sorted(((p, s) for p, s in scores.items() if s > args.min_score),
                  key=lambda t: -t[1])[:args.max_tiles]
    print(f"{len(cand)} candidates > {args.min_score} "
          f"(top: {[(p, int(s)) for p, s in cand[:12]]})")

    img_dir = os.path.join(args.picker, "imgs")
    os.makedirs(img_dir, exist_ok=True)
    for i, (p, _) in enumerate(cand):
        render_candidate(p, img_dir)
        if (i + 1) % 50 == 0:
            print(f"  rendered {i + 1}/{len(cand)}")
    json.dump([{"npix": p, "score": round(s)} for p, s in cand],
              open(os.path.join(args.picker, "candidates.json"), "w"))
    # all scores, for threshold tuning without a rescan
    json.dump(scores, open(os.path.join(args.picker, "scores.json"), "w"))
    html_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "staircase_picker_annotate.html")
    if not os.path.isfile(html_src):
        sys.exit(f"picker template missing: {html_src}")
    import shutil
    shutil.copy(html_src, os.path.join(args.picker, "picker_annotate.html"))
    print("picker ->", os.path.join(args.picker, "picker_annotate.html"))


if __name__ == "__main__":
    main()
