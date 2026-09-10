#!/usr/bin/env python3
# Stellarium Web Engine
#
# Production driver for plate colour-cast removal (castclean).
#
# Applies tools/castclean (confirmed mode) to the human-confirmed order-3
# regions listed in a regions file (default tools/cast-regions.txt, tokens
# "3/<npix>[:no-blue]").  Like clean-dss-survey.py it processes each region
# COHERENTLY: the four order-4 children are stitched into one 1024^2 image
# (verified HiPS layout (TL,TR,BL,BR)=(c0,c2,c1,c3)), cleaned once at full
# resolution with cell=32 — so the 32x32 analysis grid has the same angular
# scale as the reviewed 512^2/cell=16 runs — then split back into the four
# order-4 children and INTER_AREA-downsampled to rebuild the order-3 tile
# (guaranteeing order-3 == downsample(order-4), seamless zoom handoff).
#
# Output is an OVERLAY tree: only cleaned tiles are written to --out
# (originals in --src are never modified).  A before/after review page is
# generated with --report.
#
# Usage:
#   make -C tools/castclean
#   python tools/clean-cast-survey.py --src apps/skydata/surveys/dss \
#       --out /tmp/dss-cast-cleaned --report apps/web-frontend/public/cast-final-review
import argparse
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.clean_dss.io import load_rgb, save_webp_q90
from tools.clean_dss.pyramid import child_ids

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "castclean", "castclean_cli")


def parse_regions(path):
    """-> list of (npix, no_blue)"""
    out = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tok, _, cls = line.partition(":")
        o, n = tok.split("/")
        if int(o) != 3:
            raise SystemExit(f"only order-3 regions supported: {line!r}")
        out.append((int(n), cls == "no-blue"))
    return out


def stitch(src, parent):
    kids = child_ids(parent)
    paths = [f"{src}/Norder4/Dir0/Npix{c}.webp" for c in kids]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"region {parent}: missing children {missing}")
    c0, c1, c2, c3 = (load_rgb(p) for p in paths)
    return np.concatenate([np.concatenate([c0, c2], axis=1),
                           np.concatenate([c1, c3], axis=1)], axis=0)


def run_castclean(img_rgb, no_blue, cell, extra=()):
    """img -> (cleaned, report dict) via the castclean CLI (PPM round trip)."""
    with tempfile.TemporaryDirectory() as td:
        pin = os.path.join(td, "in.ppm")
        pout = os.path.join(td, "out.ppm")
        cv2.imwrite(pin, cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR))
        args = [CLI, "-confirmed", "-cell", str(cell)]
        if no_blue:
            args.append("-no-blue")
        args += list(extra) + [pin, pout]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"castclean failed: {r.stderr[:300]}")
        m = re.search(r"dead=([\d.]+)%\s+mask=([\d.]+)%.*mean\|d\|=([\d.]+)",
                      r.stdout)
        cleaned = cv2.cvtColor(cv2.imread(pout), cv2.COLOR_BGR2RGB)
    return cleaned, dict(dead=float(m.group(1)), mask=float(m.group(2)),
                         diff=float(m.group(3)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--regions",
                    default=os.path.join(HERE, "cast-regions.txt"))
    ap.add_argument("--report", default=None,
                    help="write a before/after review page to this dir")
    ap.add_argument("--cell", type=int, default=32,
                    help="analysis cell on the 1024^2 stitch (32 keeps the "
                         "angular scale of the reviewed 512^2 runs)")
    ap.add_argument("--cast-thresh", type=float, default=None,
                    help="override castclean blue-cast threshold for this batch "
                         "(lower = stronger blue-cast removal; ~1.5 is the "
                         "effective floor, values below saturate)")
    args = ap.parse_args()

    if not os.path.exists(CLI):
        raise SystemExit(f"{CLI} not built — run: make -C tools/castclean")
    regions = parse_regions(args.regions)
    print(f"{len(regions)} regions")

    rows = []
    for i, (parent, no_blue) in enumerate(regions):
        big = stitch(args.src, parent)
        extra = (("-cast-thresh", str(args.cast_thresh))
                 if args.cast_thresh is not None else ())
        cleaned, rep = run_castclean(big, no_blue, args.cell, extra)
        kids = child_ids(parent)
        quads = [cleaned[:512, :512], cleaned[512:, :512],
                 cleaned[:512, 512:], cleaned[512:, 512:]]
        for c, q in zip(kids, quads):
            save_webp_q90(np.ascontiguousarray(q),
                          f"{args.out}/Norder4/Dir0/Npix{c}.webp")
        parent_img = cv2.resize(cleaned, (512, 512),
                                interpolation=cv2.INTER_AREA)
        save_webp_q90(parent_img, f"{args.out}/Norder3/Dir0/Npix{parent}.webp")
        rows.append((parent, no_blue, rep))
        print(f"[{i+1}/{len(regions)}] region {parent}"
              f"{' (no-blue)' if no_blue else ''}: dead={rep['dead']:.1f}% "
              f"mask={rep['mask']:.1f}% diff={rep['diff']:.2f}", flush=True)
        if args.report:
            os.makedirs(args.report, exist_ok=True)
            small = cv2.resize(big, (512, 512), interpolation=cv2.INTER_AREA)
            cv2.imwrite(f"{args.report}/{parent}_a.webp",
                        cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_WEBP_QUALITY, 95])
            cv2.imwrite(f"{args.report}/{parent}_b.webp",
                        cv2.cvtColor(parent_img, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_WEBP_QUALITY, 95])

    if args.report:
        rows.sort(key=lambda r: -r[2]["diff"])
        html = ['<html><head><meta charset="utf-8"><style>'
                'body{background:#111;color:#ccc;font-family:sans-serif}'
                '.t{display:inline-block;margin:6px;text-align:center}'
                'img{width:300px}</style></head><body>'
                '<h1>castclean production run — region before/after</h1>']
        for parent, no_blue, rep in rows:
            html.append(
                f'<div class="t"><div>region {parent}'
                f'{" (no-blue)" if no_blue else ""} diff={rep["diff"]:.2f} '
                f'dead={rep["dead"]:.0f}%</div>'
                f'<img src="{parent}_a.webp"> <img src="{parent}_b.webp">'
                f'</div>')
        html.append("</body></html>")
        with open(f"{args.report}/index.html", "w") as f:
            f.write("\n".join(html))
        print("report:", f"{args.report}/index.html")
    print(f"done: {len(rows)} regions -> {args.out} "
          f"({5 * len(rows)} tiles written)")


if __name__ == "__main__":
    main()
