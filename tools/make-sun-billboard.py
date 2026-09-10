#!/usr/bin/env python3
# Stellarium Web Engine
#
# Build the Sun billboard texture (sun-disk.webp) from the full-disk photo
# sun.webp. The engine renders the Sun as a flat, camera-facing sprite (see
# planets.c planet_render_sun_disk) instead of a 3d HiPS sphere -- a sphere
# clips prominences past the limb and its fixed no-spin frame distorts the disk
# across dates. paint_texture() uses normal alpha blending, so the sprite needs
# an alpha channel: opaque over the photospheric disk (including sunspots) and
# over the prominences, transparent in the black margins so it composites over
# the sky.
#
# Input : apps/skydata/surveys/sso/sun/sun.webp     (RGB full disk, black corners)
# Output: apps/skydata/surveys/sso/sun/sun-disk.webp (RGBA billboard)
#
# Requires numpy + Pillow (webp). Run with the tools venv:
#   <ephvenv>/bin/python tools/make-sun-billboard.py

import math
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUN = os.path.join(ROOT, "apps", "skydata", "surveys", "sso", "sun")


def measure_disk(g):
    thr = g.max() * 0.15
    ys, xs = np.where(g > thr)
    cx, cy = xs.mean(), ys.mean()
    row = g[int(cy)]; col = g[:, int(cx)]
    xr = np.where(row > thr)[0]; yr = np.where(col > thr)[0]
    r = min((xr.max() - xr.min()) / 2, (yr.max() - yr.min()) / 2)
    return cx, cy, r


def main():
    rgb = np.asarray(Image.open(os.path.join(SUN, "sun.webp")).convert("RGB"),
                     dtype=np.float32)
    H, W = rgb.shape[:2]
    lum = rgb.mean(2)
    cx, cy, r = measure_disk(lum)
    print(f"disk c=({cx:.0f},{cy:.0f}) r={r:.0f}  image {W}x{H}")

    # alpha = 1 inside the photospheric disk (keeps sunspots opaque), plus a
    # luminance mask outside it so bright prominences show and pure-black margins
    # stay transparent.
    yy, xx = np.mgrid[0:H, 0:W]
    rad = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    disk = np.clip((r + 2 - rad) / 4.0, 0, 1)          # 1 inside, feather at limb
    promin = np.clip((lum - 4.0) / 12.0, 0, 1)          # black->0, faint->ramp->1
    alpha = np.maximum(disk, promin)

    out = np.dstack([rgb, alpha * 255.0]).clip(0, 255).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(os.path.join(SUN, "sun-disk.webp"),
                                      "WEBP", quality=92, method=6, exact=True)
    frac = 2 * r / W
    print(f"wrote sun-disk.webp (RGBA)  photospheric disk = {frac:.3f} of width")
    print(f"  -> set SUN_DISK_FRAC = {frac:.3f} in planets.c if it differs")


if __name__ == "__main__":
    main()
