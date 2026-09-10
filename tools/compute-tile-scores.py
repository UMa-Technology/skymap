#!/usr/bin/env python3
"""Compute a rough 'block-likelihood' score for every order-3 DSS tile, to ORDER the
visual tile-picker (candidates first). The score is a scan aid, NOT a detector: it
surfaces tiles with strong straight-edge/colour structure (plate blocks AND real
galaxies/nebulae) so the human eye can confirm blocks and skip the rest.

Writes apps/skymap-web/public/tile-scores.json: {npix: score} for Norder3.
"""
import json
import os
import sys
import glob
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.clean_dss.background import coarse_bg

DSS = os.path.join(ROOT, "apps", "skymap-web", "public", "skydata", "surveys", "dss")
OUT = os.path.join(ROOT, "apps", "skymap-web", "public", "tile-scores.json")


def _robust_poly(z, deg=2, iters=3):
    g = z.shape[0]
    ys, xs = np.mgrid[0:g, 0:g].astype(np.float64)
    xs = (xs / (g - 1)) * 2 - 1
    ys = (ys / (g - 1)) * 2 - 1
    terms = [xs ** i * ys ** j for i in range(deg + 1) for j in range(deg + 1 - i)]
    A = np.stack([t.ravel() for t in terms], 1)
    b = z.ravel()
    w = np.ones_like(b)
    for _ in range(iters):
        c, *_ = np.linalg.lstsq(A * w[:, None], b * w, rcond=None)
        r = b - A @ c
        s = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-6
        w = (np.abs(r) < 2.5 * s).astype(float)
    return (A @ c).reshape(g, g)


def block_score(img):
    """Best straight-line split of the star-robust coarse background: combined
    luminance+chroma residual gap between the two half-planes, favouring low
    within-region scatter (a clean straight step)."""
    bg = coarse_bg(img)
    g = bg.shape[0]
    R, G, B = bg[..., 0], bg[..., 1], bg[..., 2]
    lum = bg.mean(2)
    s = R + G + B + 1e-3
    feats = [lum, (R - G) / np.sqrt(s) * 8, (B - G) / np.sqrt(s) * 8]  # lum + scaled chroma
    Rs = [f - _robust_poly(f) for f in feats]
    ys, xs = np.mgrid[0:g, 0:g].astype(np.float32)
    best = 0.0
    for th in range(0, 180, 10):
        t = np.deg2rad(th)
        proj = xs * np.cos(t) + ys * np.sin(t)
        for q in np.linspace(0.3, 0.7, 7):
            rho = np.quantile(proj, q)
            side = proj > rho
            if side.sum() < 8 or (~side).sum() < 8:
                continue
            gap = sum(abs(Rr[side].mean() - Rr[~side].mean()) for Rr in Rs)
            within = max(max(Rr[side].std(), Rr[~side].std()) for Rr in Rs)
            score = gap / (within + 0.5)
            best = max(best, float(score))
    return round(best, 3)


def main():
    tiles = sorted(glob.glob(f"{DSS}/Norder3/Dir0/*.webp"),
                   key=lambda p: int(os.path.basename(p)[4:-5]))
    scores = {}
    for i, p in enumerate(tiles):
        n = int(os.path.basename(p)[4:-5])
        img = np.asarray(Image.open(p).convert("RGB"))
        scores[n] = block_score(img)
        if (i + 1) % 96 == 0:
            print(f"  {i + 1}/{len(tiles)} scored")
    with open(OUT, "w") as f:
        json.dump(scores, f)
    hi = sorted(scores.items(), key=lambda kv: -kv[1])[:15]
    print(f"wrote {len(scores)} scores -> {OUT}")
    print("top 15 by score:", [f"{n}:{s}" for n, s in hi])


if __name__ == "__main__":
    main()
