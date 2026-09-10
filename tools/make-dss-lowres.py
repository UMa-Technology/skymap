#!/usr/bin/env python3
# Stellarium Web Engine
#
# Add a low-resolution FALLBACK BASE to the offline DSS survey by downsampling
# the shipped Norder3 tiles into Norder2, and lower hips_order_min to 2.
#
# Why: the DSS ships only orders 3-4 (make-dss-survey.py). With no lower base and
# no allsky, whenever the order-3/4 tiles for the current view aren't resident
# yet (during zoom-in, or panning to a new direction), hips_get_tile_texture()
# recurses down to order_min=3, finds nothing, returns NULL -> that patch renders
# BLACK. The Milky Way survey (hips_order=0, always resident) used to mask this,
# but once the Milky Way fades out (~25 deg FOV, see milkyway.c/dss.c) the DSS is
# exposed and the loading holes show as black at certain FOV/azimuth/altitude.
#
# Fix: give the DSS its own coarser base. Order 2 (192 tiles) is warmed early
# (the DSS prefetch starts at 40 deg FOV where the render order is ~2) so it is
# resident by the time you zoom in; the fallback chain 4->3->2 then always has
# something to draw (blurry, never black). Order 2 is only used when order 3 is
# ALSO not resident (i.e. the new-direction case), so it never degrades quality
# elsewhere. order_min is read from the properties file (src/hips.c), so this
# needs NO engine/WASM rebuild -- just regenerate + reload.
#
# Child->quadrant layout is NOT guessed: it was measured against ground truth
# (a real Norder3 tile IS the 2x downsample of its four Norder4 children) by
# brute-forcing all 24 placements; the winner (MSE 1.97, next-best 14+) is
# slots [TL,TR,BL,BR] <- nested children [0,2,1,3], i.e. child i -> col=i//2,
# row=i%2, identity (no flip). The same nested layout holds at every level, so
# it is reused here for order3 -> order2.
#
# Output: apps/skydata/surveys/dss/Norder2/Dir0/Npix{0..191}.webp  (+ patched
#         properties). Run AFTER make-dss-survey.py. Requires numpy + Pillow +
#         the libwebp cwebp CLI.
#
#   python3 tools/make-dss-lowres.py

import io
import os
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSS = os.path.join(ROOT, "apps", "skydata", "surveys", "dss")
SRC_ORDER = 3     # downsample from this order ...
DST_ORDER = 2     # ... into this one
Q = 90            # match the Q90 re-encode of the shipped orders 3-4


def tile_path(order, p):
    return os.path.join(DSS, f"Norder{order}", f"Dir{p//10000}", f"Npix{p}.webp")


def load(order, p):
    return np.asarray(Image.open(tile_path(order, p)).convert("RGB"))


def down2(img):  # 1024x1024 -> 512x512 by 2x2 block average (HiPS parent rule)
    h, w = img.shape[:2]
    return img.reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))


def encode_webp(arr_u8, dst):
    """cwebp -q Q -m 6 (PNG on stdin), matching the shipped tiles' encoder."""
    buf = io.BytesIO()
    Image.fromarray(arr_u8).save(buf, "PNG")
    enc = subprocess.run(
        ["cwebp", "-quiet", "-q", str(Q), "-m", "6", "-o", dst, "--", "-"],
        input=buf.getvalue(), capture_output=True)
    return enc.returncode == 0


def build_tile(p2):
    """Assemble order-2 pixel p2 from its four order-3 children (nested 4*p2+i).

    Placement (measured, see header): child i -> quadrant (row=i%2, col=i//2).
    """
    mosaic = np.zeros((1024, 1024, 3), dtype=np.float64)
    for i in range(4):
        child = 4 * p2 + i
        r, c = i % 2, i // 2
        mosaic[r*512:(r+1)*512, c*512:(c+1)*512] = load(SRC_ORDER, child)
    small = np.clip(np.round(down2(mosaic)), 0, 255).astype(np.uint8)
    return small


def patch_properties():
    path = os.path.join(DSS, "properties")
    with open(path) as f:
        txt = f.read()
    txt = re.sub(r"(?m)^(hips_order_min\s*=\s*).*$",
                 rf"\g<1>{DST_ORDER}", txt)
    txt = re.sub(r"(?m)^(hips_order\s*=\s*).*$",
                 r"\g<1>4", txt)  # keep max order 4
    txt = txt.replace("offline 3-4", f"offline {DST_ORDER}-4")
    txt = txt.replace("orders 3-4", f"orders {DST_ORDER}-4")
    with open(path, "w") as f:
        f.write(txt)
    print(f"patched properties: hips_order_min = {DST_ORDER}")


def main():
    if not os.path.isdir(os.path.join(DSS, f"Norder{SRC_ORDER}")):
        sys.exit(f"missing Norder{SRC_ORDER}; run make-dss-survey.py first")

    n = 12 * 4 ** DST_ORDER  # 192
    out_dir = os.path.join(DSS, f"Norder{DST_ORDER}", "Dir0")
    if os.path.isdir(os.path.join(DSS, f"Norder{DST_ORDER}")):
        shutil.rmtree(os.path.join(DSS, f"Norder{DST_ORDER}"))
    os.makedirs(out_dir, exist_ok=True)

    print(f"building Norder{DST_ORDER} ({n} tiles) from Norder{SRC_ORDER} ...")
    for p2 in range(n):
        # every order-3 child must exist
        for i in range(4):
            if not os.path.exists(tile_path(SRC_ORDER, 4 * p2 + i)):
                sys.exit(f"missing order-{SRC_ORDER} child {4*p2+i} for pix {p2}")
        tile = build_tile(p2)
        dst = os.path.join(out_dir, f"Npix{p2}.webp")
        if not encode_webp(tile, dst):
            sys.exit(f"cwebp failed for Norder{DST_ORDER} Npix{p2}")

    patch_properties()

    size = sum(os.path.getsize(os.path.join(out_dir, fn))
               for fn in os.listdir(out_dir))
    print(f"wrote {n} tiles -> {out_dir}  (+{size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
