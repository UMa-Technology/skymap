#!/usr/bin/env python3
# Stellarium Web Engine
#
# Full-sky streak scan: run tools/clean_dss/streaks.scan_image over every order-3 DSS
# tile (both polarities) and write apps/web-frontend/public/tile-streaks.json =
# {npix: {score, dense, ngroups, groups:[{p0,p1,angle,dom,fwhm,fill,score}]}}. The
# tile-picker reads this to order the scan and to overlay candidate lines. This is a
# scan aid for the human, NOT an auto-cleaner.
import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.clean_dss.io import load_rgb
from tools.clean_dss import streaks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(ROOT, "apps", "skydata", "surveys", "dss")
DEFAULT_OUT = os.path.join(ROOT, "apps", "web-frontend", "public", "tile-streaks.json")


def _json_group(g):
    return {"p0": g["p0"], "p1": g["p1"], "angle": g["angle"], "dom": g["dom"],
            "fwhm": None if g["fwhm"] != g["fwhm"] else round(g["fwhm"], 2),
            "fill": round(g["fill"], 3), "score": g["score"],
            "polarity": g.get("polarity", 1)}


def scan_one(img):
    """Best-of both polarities for one tile; returns a JSON-safe record."""
    recs = []
    for pol in (1, -1):
        s = streaks.scan_image(img, polarity=pol)
        for g in s["groups"]:
            g["polarity"] = pol
            recs.append((g, s["dense"]))
    if not recs:
        return {"score": 0.0, "dense": False, "ngroups": 0, "groups": []}
    recs.sort(key=lambda r: r[0]["score"], reverse=True)
    dense = any(d for _g, d in recs)
    groups = [_json_group(g) for g, _d in recs if g["score"] >= 1.0][:12]
    return {"score": round(float(recs[0][0]["score"]), 2), "dense": bool(dense),
            "ngroups": len(recs), "groups": groups}


def scan_tree(src, out, npix_list=None):
    base = f"{src}/Norder3/Dir0"
    if npix_list is None:
        npix_list = sorted(int(os.path.basename(p)[4:-5]) for p in glob.glob(f"{base}/*.webp"))
    data = {}
    for i, n in enumerate(npix_list):
        img = load_rgb(f"{base}/Npix{n}.webp")
        data[str(n)] = scan_one(img)
        if i % 64 == 63:
            print(f"{i + 1}/{len(npix_list)} scanned", flush=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(data, f)
    ncand = sum(1 for v in data.values() if v["score"] >= 6.0)
    print(f"wrote {out}: {len(data)} tiles, {ncand} with score>=6")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan DSS order-3 tiles for streaks -> tile-streaks.json")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    scan_tree(a.src, a.out)


if __name__ == "__main__":
    main()
