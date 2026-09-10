#!/usr/bin/env python3
# Stellarium Web Engine
#
# Production driver for targeted plate-SEAM feathering.
#
# Companion to clean-cast-survey.py (colour cast) for the residual, sparse,
# low-contrast plate-boundary SEAMS that survive castclean.  These cannot be
# blanket-processed: most "seam-looking" straight edges in the Milky Way band
# are REAL orange structure, and a blind pass eats the galaxy.  So detection is
# MANUAL: the user marks a box around each real seam in defect-tool.html
# (Norder3 box mode) and exports {order, boxes:{npix:[[x0,y0,x1,y1],...]}}.
#
# For each boxed region this driver detects the strongest straight step INSIDE
# the box (star-robust coarse background + Hough) and FEATHERS it: the sharp DC
# step is replaced by a smooth ramp within a +/-Wf band, per channel, touching
# nothing outside the band or the box.  Structure-safe by construction (only
# softens the marked straight edge; never raises dark sky or crushes glow).
#
# Region-coherent like clean-cast-survey.py: the four order-4 children are
# stitched into one 1024^2 image, feathered once, split back into four order-4
# children and INTER_AREA-downsampled to rebuild order-3 (order-3 ==
# downsample(order-4), seamless zoom).  Overlay output; --report before/after.
#
# Usage:
#   python tools/feather-seams.py --src apps/skydata/surveys/dss \
#       --boxes seam-boxes.json --out /tmp/dss-seam \
#       --report apps/web-frontend/public/seam-feather-review
import argparse
import json
import os
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.clean_dss.io import load_rgb, save_webp_q90
from tools.clean_dss.pyramid import child_ids

CELL = 16          # analysis cell on the 1024^2 stitch -> 64x64 grid
WF = 3             # feather half-width in coarse cells (~48 px on the stitch)
BAND = 3           # near-band for step estimation (coarse cells)


def parse_boxes(path):
    """seam-boxes.json -> (order, list of (npix, [box,...])). box = x0,y0,x1,y1 in 0..1."""
    j = json.load(open(path))
    order = int(j.get("order", 3))
    if order != 3:
        raise SystemExit("only order-3 boxes supported (mark in Norder3 mode)")
    items = []
    for k, boxes in j["boxes"].items():
        boxes = [b for b in boxes if b and len(b) == 4]
        if boxes:
            items.append((int(k), boxes))
    return order, items


def robust_bg3(img, cell=CELL, pct=35):
    a = img.astype(np.float32)
    g = img.shape[0] // cell
    out = np.empty((g, g, 3), np.float32)
    for c in range(3):
        v = a[:g * cell, :g * cell, c].reshape(g, cell, g, cell)
        out[..., c] = np.percentile(v, pct, axis=(1, 3))
    return out


def detect_line_in_box(L, box):
    """Strongest straight step inside normalized box; -> (jump,x1,y1,x2,y2) in grid px."""
    g = L.shape[0]
    x0, y0, x1b, y1b = [int(round(v * g)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1b, y1b = min(g, x1b), min(g, y1b)
    if x1b - x0 < 4 or y1b - y0 < 4:
        return None
    mask = np.zeros((g, g), np.uint8)
    mask[y0:y1b, x0:x1b] = 1
    Ls = cv2.GaussianBlur(L, (5, 5), 0)
    gx = cv2.Sobel(Ls, cv2.CV_32F, 1, 0, 3)
    gy = cv2.Sobel(Ls, cv2.CV_32F, 0, 1, 3)
    mag = np.hypot(gx, gy) * mask
    if not (mask > 0).any():
        return None
    thr = max(np.percentile(mag[mask > 0], 80), 0.3)
    edges = (mag > thr).astype(np.uint8) * 255
    minlen = max(6, int(min(x1b - x0, y1b - y0) * 0.5))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=8,
                            minLineLength=minlen, maxLineGap=4)
    if lines is None:
        return None
    yy, xx = np.mgrid[0:g, 0:g]
    best = None
    for a, b, cc, d in np.asarray(lines).reshape(-1, 4):
        dx, dy = cc - a, d - b
        Ln = np.hypot(dx, dy)
        if Ln < 1:
            continue
        nx, ny = -dy / Ln, dx / Ln
        tx, ty = dx / Ln, dy / Ln
        sd = (xx - a) * nx + (yy - b) * ny
        s = (xx - a) * tx + (yy - b) * ty
        onseg = (s >= -2) & (s <= Ln + 2) & (mask > 0)
        pos = (sd > 0.5) & (sd < BAND + 0.5) & onseg
        neg = (sd < -0.5) & (sd > -BAND - 0.5) & onseg
        if pos.sum() < 6 or neg.sum() < 6:
            continue
        jump = abs(np.median(L[pos]) - np.median(L[neg]))
        if best is None or jump > best[0]:
            best = (float(jump), float(a), float(b), float(cc), float(d))
    return best


def feather_stitch(img, boxes):
    """Feather every boxed seam in a 1024^2 stitch. -> (out, [(box,jump)...])."""
    g = img.shape[0] // CELL
    bg = robust_bg3(img)
    L = bg.mean(2)
    yy, xx = np.mgrid[0:g, 0:g].astype(np.float32)
    Cg = np.zeros((g, g, 3), np.float32)
    dets = []
    for box in boxes:
        det = detect_line_in_box(L, box)
        if det is None:
            dets.append((box, 0.0))
            continue
        jump, x1, y1, x2, y2 = det
        dx, dy = x2 - x1, y2 - y1
        Ln = np.hypot(dx, dy)
        nx, ny = -dy / Ln, dx / Ln
        sd = (xx - x1) * nx + (yy - y1) * ny
        bx0, by0, bx1, by1 = (box[0] * g, box[1] * g, box[2] * g, box[3] * g)
        inbox = (xx >= bx0) & (xx < bx1) & (yy >= by0) & (yy < by1)
        band = (np.abs(sd) < WF) & inbox
        for c in range(3):
            Bc = bg[..., c]
            farhi = (sd >= WF) & (sd < 2 * WF) & inbox
            farlo = (sd <= -WF) & (sd > -2 * WF) & inbox
            if farhi.sum() < 4 or farlo.sum() < 4:
                continue
            Vhi = np.median(Bc[farhi])
            Vlo = np.median(Bc[farlo])
            t = np.clip((sd + WF) / (2 * WF), 0, 1)
            target = Vlo + (Vhi - Vlo) * t
            Cg[..., c] = np.where(band, target - Bc, Cg[..., c])
        dets.append((box, jump))
    Cg = cv2.GaussianBlur(Cg, (0, 0), 1.0)
    Cfull = cv2.resize(Cg, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    out = np.clip(img.astype(np.float32) + Cfull, 0, 255).astype(np.uint8)
    return out, dets


def stitch(src, parent):
    kids = child_ids(parent)
    paths = [f"{src}/Norder4/Dir0/Npix{c}.webp" for c in kids]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"region {parent}: missing children {missing}")
    c0, c1, c2, c3 = (load_rgb(p) for p in paths)
    return np.concatenate([np.concatenate([c0, c2], axis=1),
                           np.concatenate([c1, c3], axis=1)], axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--boxes", required=True, help="seam-boxes.json from defect-tool")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    _, items = parse_boxes(args.boxes)
    print(f"{len(items)} boxed regions")
    rows = []
    for i, (parent, boxes) in enumerate(items):
        big = stitch(args.src, parent)
        out, dets = feather_stitch(big, boxes)
        kids = child_ids(parent)
        quads = [out[:512, :512], out[512:, :512], out[:512, 512:], out[512:, 512:]]
        for c, q in zip(kids, quads):
            save_webp_q90(np.ascontiguousarray(q), f"{args.out}/Norder4/Dir0/Npix{c}.webp")
        parent_img = cv2.resize(out, (512, 512), interpolation=cv2.INTER_AREA)
        save_webp_q90(parent_img, f"{args.out}/Norder3/Dir0/Npix{parent}.webp")
        jumps = [round(j, 1) for _, j in dets]
        diff = float(np.abs(out.astype(float) - big.astype(float)).mean())
        rows.append((parent, jumps, diff))
        print(f"[{i+1}/{len(items)}] region {parent}: {len(boxes)} box(es) "
              f"jumps={jumps} meanDiff={diff:.2f}", flush=True)
        if args.report:
            os.makedirs(args.report, exist_ok=True)
            small = cv2.resize(big, (512, 512), interpolation=cv2.INTER_AREA)
            for tag, im in (("a", small), ("b", parent_img)):
                cv2.imwrite(f"{args.report}/{parent}_{tag}.webp",
                            cv2.cvtColor(im, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_WEBP_QUALITY, 95])

    if args.report:
        rows.sort(key=lambda r: -r[2])
        html = ['<html><head><meta charset="utf-8"><style>'
                'body{background:#111;color:#ccc;font-family:sans-serif}'
                '.t{display:inline-block;margin:6px;text-align:center;font-size:12px}'
                'img{width:340px;image-rendering:pixelated}</style></head><body>'
                '<h1>plate-seam feathering — region before/after (×same tone)</h1>'
                '<p>left = original, right = feathered. Only marked seams softened.</p>']
        for parent, jumps, diff in rows:
            html.append(f'<div class="t"><div>Npix{parent} jumps={jumps} '
                        f'meanDiff={diff:.2f}</div>'
                        f'<img src="{parent}_a.webp"> <img src="{parent}_b.webp"></div>')
        html.append("</body></html>")
        open(f"{args.report}/index.html", "w").write("\n".join(html))
        print("report:", f"{args.report}/index.html")
    print(f"done: {len(rows)} regions -> {args.out} ({5 * len(rows)} tiles)")


if __name__ == "__main__":
    main()
