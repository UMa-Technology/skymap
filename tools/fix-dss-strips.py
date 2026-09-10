#!/usr/bin/env python3
# Stellarium Web Engine
#
# Batch strip-ramp repair of DSS Norder4 staircase/plate-seam artifacts, from
# human annotations drawn in staircase-picker/picker_annotate.html.
#
# Method (generalises the hand fix of Npix1175 to any orientation): each
# annotation is a centre line (x0,y0)-(x1,y1) plus a width w, defining a strip.
# The strip interior is REBUILT as a smooth ramp between the backgrounds
# sampled just OUTSIDE its two long edges, per position along the line (the two
# sides may differ - dark sky vs Milky Way glow - so no flat fill can match
# both). Real sky texture is transplanted into the fill (mirror across the
# strip edge, star-clipped) so the grain matches; edges are feathered (12px inside the
# strip, 12px at the line's ends, 8px at tile borders so neighbouring tiles
# stay continuous). Stars inside the strip are sacrificed per project rule
# (the engine redraws catalog stars; only nebula/galaxy imagery must survive).
#
# After all tiles are patched, every affected order-3 parent is rebuilt from
# its 4 children, and every affected order-2 grandparent from ITS 4 children
# (layout [TL,TR,BL,BR] = nested children [0,2,1,3], measured in
# make-dss-lowres.py; downsample = 2x2 box mean == cv2.INTER_AREA).
#
# Usage:
#   python3 tools/fix-dss-strips.py --annotations ann.json            # preview
#   python3 tools/fix-dss-strips.py --annotations ann.json --apply
#
# ann.json = picker export: {"tiles": {"1623": [{"x0":..,"y0":..,"x1":..,
#            "y1":..,"w":160}, ...], ...}}   (coordinates in 512-tile space)
import argparse
import json
import os
import sys

import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.clean_dss.io import load_rgb, save_webp_q90  # noqa: E402

DSS = os.path.join(ROOT, "apps", "skydata", "surveys", "dss")


def strip_frame(shape, x0, y0, x1, y1, w):
    """(d, u, length, inside) for a strip over an image of `shape`."""
    H, W = shape[:2]
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    ex, ey = x1 - x0, y1 - y0
    length = max((ex * ex + ey * ey) ** 0.5, 1e-6)
    ex, ey = ex / length, ey / length
    d = (X - x0) * -ey + (Y - y0) * ex         # signed distance across strip
    u = (X - x0) * ex + (Y - y0) * ey          # position along the line
    half = w / 2.0
    inside = (np.abs(d) <= half) & (u >= -half) & (u <= length + half)
    return d, u, length, inside


def fill_strip(im, x0, y0, x1, y1, w, exclude=None):
    """Rebuild one strip of `im` (float32 RGB, modified in place).
    `exclude`: bool mask of pixels never to SAMPLE from (other annotated
    strips' interiors - they may hold not-yet-repaired artifacts)."""
    H, W = im.shape[:2]
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    d, u, length, inside = strip_frame(im.shape, x0, y0, x1, y1, w)
    half = w / 2.0
    ex, ey = x1 - x0, y1 - y0
    ex, ey = ex / max(length, 1e-6), ey / max(length, 1e-6)
    nx, ny = -ey, ex

    if not inside.any():
        return
    # feather: across-strip edges (12px), line ends (12px), tile borders (8px)
    alpha = np.clip((half - np.abs(d)) / 12.0, 0, 1)
    alpha = np.minimum(alpha, np.clip((u + half) / 12.0, 0, 1))
    alpha = np.minimum(alpha, np.clip((length + half - u) / 12.0, 0, 1))
    border = np.minimum(np.minimum(X, (W - 1) - X), np.minimum(Y, (H - 1) - Y))
    alpha = alpha * inside * np.clip(border / 8.0, 0, 1)

    BINW = 8
    NB = int(2 * (H + W) / BINW)
    U0 = -(H + W)
    ub = np.clip(((u - U0) // BINW).astype(int), 0, NB - 1)
    maskA = (d >= -half - 40) & (d <= -half - 6)
    maskB = (d >= half + 6) & (d <= half + 40)
    if exclude is not None:                     # don't sample other artifacts
        maskA &= ~exclude
        maskB &= ~exclude

    def side_profile(mask):
        P = np.full((NB, 3), np.nan, np.float32)
        for b in np.unique(ub[mask]):
            sel = mask & (ub == b)
            if sel.sum() < 20:
                continue
            px = im[sel]
            keep = px.mean(1) <= np.percentile(px.mean(1), 80)  # drop stars
            P[b] = np.median(px[keep], axis=0)
        got = np.where(~np.isnan(P[:, 0]))[0]
        if len(got) == 0:                       # side fully off-tile: mirror it
            return None
        for c in range(3):
            P[:, c] = np.interp(np.arange(NB), got, P[got, c])
            P[:, c] = gaussian_filter1d(P[:, c], 2.0)
        return P

    A, B = side_profile(maskA), side_profile(maskB)
    if A is None and B is None:
        return
    if A is None:
        A = B
    if B is None:
        B = A

    # GRAIN: transplant the REAL sky texture (webp block noise + photographic
    # grain) instead of synthetic gaussian noise - synthetic fills read as
    # plastic-smooth next to the genuine sky under the x4 review stretch.
    # Source: high-frequency residual of the tile, star-clipped to +/-6 DN so
    # no ghost stars are copied; each strip pixel mirrors across its NEAR strip
    # edge into the untouched sky just outside.
    resid = im - cv2.medianBlur(im.astype(np.uint8), 5).astype(np.float32)
    np.clip(resid, -6, 6, out=resid)
    sgn = np.where(d >= 0, 1.0, -1.0).astype(np.float32)
    d_src = sgn * (2 * half + 12) - d          # reflect about d = +/-(half+6)
    Xs = np.clip(np.rint(X + (d_src - d) * nx), 0, W - 1).astype(np.int32)
    Ys = np.clip(np.rint(Y + (d_src - d) * ny), 0, H - 1).astype(np.int32)
    grain = resid[Ys, Xs]
    if exclude is not None:                    # no texture from other artifacts
        grain[exclude[Ys, Xs]] = 0.0

    t = np.clip((d + half) / w, 0, 1)
    fill = np.empty_like(im)
    for c in range(3):
        fill[..., c] = (1 - t) * A[ub, c] + t * B[ub, c] + grain[..., c]
    np.clip(fill, 0, 255, out=fill)
    im += (fill - im) * alpha[..., None]


def rebuild_parent(order, parent, apply):
    """Rebuild Norder{order}/Npix{parent} from its 4 Norder{order+1} children."""
    kids = [parent * 4 + i for i in range(4)]
    imgs = [load_rgb(f"{DSS}/Norder{order + 1}/Dir0/Npix{c}.webp") for c in kids]
    h = imgs[0].shape[0]
    big = np.zeros((2 * h, 2 * h, 3), np.uint8)   # [TL,TR,BL,BR] = kids[0,2,1,3]
    big[:h, :h], big[:h, h:] = imgs[0], imgs[2]
    big[h:, :h], big[h:, h:] = imgs[1], imgs[3]
    down = cv2.resize(big, (h, h), interpolation=cv2.INTER_AREA)
    if apply:
        save_webp_q90(np.ascontiguousarray(down),
                      f"{DSS}/Norder{order}/Dir0/Npix{parent}.webp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--preview-dir", default=os.path.join(
        ROOT, "apps", "skymap-web", "public", "staircase-picker", "preview"))
    ap.add_argument("--amp", type=float, default=4.0,
                    help="preview brightness multiplier (1 = true display)")
    args = ap.parse_args()

    ann = json.load(open(args.annotations))
    tiles = {int(k): v for k, v in ann["tiles"].items() if v}
    if not tiles:
        sys.exit("no annotated tiles in file")
    # validate EVERYTHING before writing anything (a bad entry mid-batch under
    # --apply would otherwise leave already-written children with stale parents)
    for npix, strips in tiles.items():
        if not (0 <= npix < 3072):
            sys.exit(f"tile {npix}: order-4 npix out of range [0,3072)")
        if not os.path.isfile(f"{DSS}/Norder4/Dir0/Npix{npix}.webp"):
            sys.exit(f"tile {npix}: source tile missing")
        for s in strips:
            if s["w"] < 8:                      # w=0 would NaN the ramp
                sys.exit(f"tile {npix}: strip width {s['w']} too small (<8)")

    os.makedirs(args.preview_dir, exist_ok=True)
    rows = []
    for npix in sorted(tiles):
        path = f"{DSS}/Norder4/Dir0/Npix{npix}.webp"
        im = load_rgb(path).astype(np.float32)
        before = im.copy()
        # union of ALL this tile's strip interiors: no strip may sample another
        exclude = np.zeros(im.shape[:2], bool)
        for s in tiles[npix]:
            exclude |= strip_frame(im.shape, s["x0"], s["y0"],
                                   s["x1"], s["y1"], s["w"])[3]
        for s in tiles[npix]:
            fill_strip(im, s["x0"], s["y0"], s["x1"], s["y1"], s["w"],
                       exclude=exclude)
        out = np.clip(im + 0.5, 0, 255).astype(np.uint8)
        for tag, arr in (("a", before), ("b", out)):
            amp = np.clip(arr.astype(np.float32) * args.amp, 0, 255).astype(np.uint8)
            cv2.imwrite(f"{args.preview_dir}/{npix}_{tag}.png", amp[..., ::-1])
        rows.append(npix)
        if args.apply:
            save_webp_q90(out, path)
        print(f"tile {npix}: {len(tiles[npix])} strip(s)")

    # review page
    html = ["<html><body style='background:#111;color:#ddd;font-family:sans-serif'>",
            f"<h3>strip-fix preview (x{args.amp:g} brightness) — "
            "left before / right after</h3>"]
    for p in rows:
        html.append(f"<div><b>Npix{p}</b><br>"
                    f"<img src='{p}_a.png' width=420> "
                    f"<img src='{p}_b.png' width=420></div><hr>")
    html.append("</body></html>")
    open(f"{args.preview_dir}/index.html", "w").write("\n".join(html))
    print("preview ->", f"{args.preview_dir}/index.html")

    if not args.apply:
        print("(preview only; pass --apply to write tiles + rebuild pyramid)")
        return
    parents3 = sorted({p // 4 for p in rows})
    for p3 in parents3:
        rebuild_parent(3, p3, True)
    parents2 = sorted({p // 4 for p in parents3})
    for p2 in parents2:
        rebuild_parent(2, p2, True)
    print(f"applied: {len(rows)} order-4 tiles, rebuilt order-3 {parents3} "
          f"and order-2 {parents2}")


if __name__ == "__main__":
    main()
