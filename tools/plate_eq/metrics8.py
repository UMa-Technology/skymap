#!/usr/bin/env python
"""metrics8.py -- QA harness for the DSS starless / background pipeline.

Hard requirements checked (starless_design.md Stage 0 item 4):
  1. dso_zero_change      : |after-before| inside the protection mask. Must be
                            bit-level ZERO when mask-and-composite is correct.
  2. sky_texture          : skyMAD (robust MAD of luminance minus its 15px
                            median blur) + banding amplitude p95 (directional
                            33x1 / 1x33 median of the residual), both measured
                            outside protection+star masks, before vs after.
  3. flux_conservation    : mean luminance change outside the star mask
                            (catches background level shifts).
  4. residual_point_sources: residual star count on the 'after' image via
                            star_detect.detect_stars (optional module, written
                            in parallel); None when unavailable.

CLI: python metrics8.py <before.webp> <after.webp> [--npix N --order 4]
     Generates the protection mask internally from the BEFORE image (with a
     real-neighbour apron when --npix is given).
"""
import os
import sys

import numpy as np
import scipy.ndimage as ndi

PEQ = os.path.dirname(os.path.abspath(__file__))
if PEQ not in sys.path:
    sys.path.insert(0, PEQ)

LUMW = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _lum(img):
    img = np.asarray(img, np.float32)
    return img @ LUMW if img.ndim == 3 else img


# ---------------------------------------------------------------------------
def dso_zero_change(before, after, protect_mask):
    """Max & mean |after-before| (DN, over all channels) inside the protection
    mask. Hard requirement: exactly 0 when compositing respects the mask."""
    protect_mask = np.asarray(protect_mask, bool)
    n = int(protect_mask.sum())
    if n == 0:
        return dict(max_abs=0.0, mean_abs=0.0, n_px=0)
    d = np.abs(np.asarray(after, np.float32) - np.asarray(before, np.float32))
    if d.ndim == 3:
        dm = d.max(axis=-1)
        dmean = d.mean(axis=-1)
    else:
        dm = dmean = d
    return dict(max_abs=float(dm[protect_mask].max()),
                mean_abs=float(dmean[protect_mask].mean()),
                n_px=n)


def _texture_stats(lum, sky):
    resid = lum - ndi.median_filter(lum, size=15)
    r = resid[sky]
    mad = 1.4826 * float(np.median(np.abs(r - np.median(r))))
    # webp flattens quiet sky blocks exactly -> MAD can hit 0; p90 keeps the
    # metric sensitive there
    p90 = float(np.percentile(np.abs(r - np.median(r)), 90))
    # banding: median along a row/column keeps stripe-coherent structure and
    # kills stars/noise; p95 of |that| = band amplitude
    band_h = ndi.median_filter(resid, size=(1, 33))   # horizontal stripes
    band_v = ndi.median_filter(resid, size=(33, 1))   # vertical stripes
    p95_h = float(np.percentile(np.abs(band_h[sky]), 95))
    p95_v = float(np.percentile(np.abs(band_v[sky]), 95))
    return mad, p90, max(p95_h, p95_v)


def sky_texture(before, after, protect_mask, star_mask):
    """skyMAD and band-amplitude p95 outside all masks, before vs after.
    A working background/fog flattener must LOWER both; DSO-safe processing
    must not raise them."""
    sky = ~(np.asarray(protect_mask, bool) | np.asarray(star_mask, bool))
    if sky.sum() < 1000:
        return dict(sky_frac=float(sky.mean()), sky_mad_before=np.nan,
                    sky_mad_after=np.nan, sky_p90_before=np.nan,
                    sky_p90_after=np.nan, band_p95_before=np.nan,
                    band_p95_after=np.nan)
    mb, pb, bb = _texture_stats(_lum(before), sky)
    ma, pa, ba = _texture_stats(_lum(after), sky)
    return dict(sky_frac=float(sky.mean()),
                sky_mad_before=mb, sky_mad_after=ma,
                sky_p90_before=pb, sky_p90_after=pa,
                band_p95_before=bb, band_p95_after=ba)


def flux_conservation(before, after, exclude_star_mask):
    """Signed luminance change outside the star mask (mean DN). Catches
    background level shifts that per-pixel metrics miss."""
    keep = ~np.asarray(exclude_star_mask, bool)
    d = (_lum(after) - _lum(before))[keep]
    return dict(mean_dn=float(d.mean()),
                median_dn=float(np.median(d)),
                p99_abs_dn=float(np.percentile(np.abs(d), 99)),
                n_px=int(keep.sum()))


def residual_point_sources(after, peak_min=10.0):
    """Count residual point sources (is_point & peak >= peak_min DN) on the
    'after' image using PEQ/star_detect.py (written by a parallel task).
    Returns None gracefully while that module does not exist."""
    try:
        from star_detect import detect_stars
    except ImportError:
        return None
    try:
        stars = detect_stars(np.asarray(after, np.float32))

        def col(*names):
            for name in names:
                try:
                    return np.asarray(stars[name])
                except (TypeError, IndexError, KeyError, ValueError):
                    try:
                        return np.asarray([s[name] for s in stars])
                    except Exception:
                        continue
            raise KeyError(names)

        try:
            is_point = col("is_point").astype(bool)
        except Exception:
            is_point = np.ones(len(stars), bool)
        peak = col("peak_dn", "peak").astype(float)
        return dict(n_residual=int((is_point & (peak >= peak_min)).sum()),
                    n_total=int(len(peak)), peak_min=peak_min)
    except Exception as e:                      # API drift in parallel module
        print("metrics8: star_detect present but unusable: %r" % (e,),
              file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
def report(before, after, protect_mask, star_mask, label=""):
    """Run all metrics, print a one-tile report, return the dict."""
    r = dict(
        dso=dso_zero_change(before, after, protect_mask),
        sky=sky_texture(before, after, protect_mask, star_mask),
        flux=flux_conservation(before, after, star_mask | protect_mask),
        residual=residual_point_sources(after),
    )
    d, s, f = r["dso"], r["sky"], r["flux"]
    ok = "PASS" if d["max_abs"] == 0.0 else "FAIL"
    print("== metrics8 %s ==" % label)
    print("  1. DSO zero-change : max=%.3f mean=%.5f DN over %d px  [%s]"
          % (d["max_abs"], d["mean_abs"], d["n_px"], ok))
    print("  2. sky texture     : skyMAD %.3f -> %.3f DN   p90 %.3f -> %.3f DN"
          "   band p95 %.3f -> %.3f DN   (sky=%.1f%% of tile)"
          % (s["sky_mad_before"], s["sky_mad_after"],
             s["sky_p90_before"], s["sky_p90_after"],
             s["band_p95_before"], s["band_p95_after"], 100 * s["sky_frac"]))
    print("  3. flux conserv.   : mean %+.4f DN  median %+.4f DN  p99|d|=%.2f DN"
          % (f["mean_dn"], f["median_dn"], f["p99_abs_dn"]))
    if r["residual"] is None:
        print("  4. residual stars  : n/a (star_detect.py not available)")
    else:
        print("  4. residual stars  : %d point sources with peak>=%g DN (of %d)"
              % (r["residual"]["n_residual"], r["residual"]["peak_min"],
                 r["residual"]["n_total"]))
    return r


def _cli():
    import argparse
    from PIL import Image
    import protect_mask as pmod

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--npix", type=int, default=None,
                    help="HEALPix nest index of the tile; enables the real-"
                         "neighbour apron for the protection mask")
    ap.add_argument("--order", type=int, default=4)
    args = ap.parse_args()

    before = np.asarray(Image.open(args.before).convert("RGB"), np.float32)
    after = np.asarray(Image.open(args.after).convert("RGB"), np.float32)

    apron_img = None
    if args.npix is not None:
        import apron as apron_mod
        apron_img, _ = apron_mod.assemble_apron(args.order, args.npix, 64)
    mask, info = pmod.protect_mask(before, apron_img)
    print("protect mask: %.1f%% of tile, star mask: %.1f%%"
          % (100 * info["coverage"], 100 * info["star_coverage"]))
    report(before, after, mask, info["star_mask"],
           label="%s vs %s" % (os.path.basename(args.before),
                               os.path.basename(args.after)))


if __name__ == "__main__":
    _cli()
