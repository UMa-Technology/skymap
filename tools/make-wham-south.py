#!/usr/bin/env python3
"""Render the southern Hα sky from the WHAM-SS DR1 integrated map into staged
int16 plates that join the MDW northern fields in the ONE hipsgen pass.

Design (validated on the Cygnus pilot, see the halpha design spec Phase 3):
- Source: wham-ss-DR1-v161116-170912-int-grid.fits (galactic CAR, 0.25 deg/px,
  Rayleighs, Natural-Neighbor interpolation of the 1-degree-beam pointings).
- Plates: equatorial CAR band strips + a gnomonic polar cap, 0.1 deg/px,
  every plate rendered TRIM=5 deg oversized per side because the production
  border=50 trim (meant for the MDW vignette) also eats 50 px of every input.
- Tone: R -> sigma 0.15 deg smoothing (kills the 0.25-deg bilinear diamonds;
  the survey's own block zero-steps are invisible after conversion) ->
  Jy = A_FIT*R + C_FIT (empirical cross-calibration against the MTF-inverted
  MDW staging: a=3.12e-6 Jy/R, r=0.969; the fitted intercept keeps the Dec-0
  blend band consistent) -> the SAME fixed-anchor MTF as the north -> int16.
- Carve: hipsgen's fading weights are not guaranteed pixel-scale based, so a
  plate under sharp MDW sky could grab weight and blur it. Therefore BLANK
  every plate pixel that any staged MDW field covers with valid (border-
  trimmed) pixels -- the north/south crossfade is then driven purely by the
  MDW frame-edge fading (proven smooth), and the MDW interior stays pure by
  construction. Carving reads the ACTUAL staged field WCS headers, so fields
  that failed to download do not punch holes in the south coverage.

Constants must match make-halpha-survey.py (frozen production values).
"""
import argparse
import glob
import os

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from scipy.ndimage import gaussian_filter

# WHAM -> MDW empirical calibration (Cygnus pilot regression, 2026-07-16)
A_FIT = 3.122e-6          # Jy per Rayleigh
C_FIT = -1.51e-4          # Jy (mean per-field intercept; see spec Phase 3)
SMOOTH_SIG_DEG = 0.15

# must match make-halpha-survey.py
MTF_SHADOW, MTF_WHITE, B_BG = -0.00032, 0.05, 0.12
STAGE_SCALE, STAGE_BLANK = 32000, -32768

SCALE = 0.1               # deg/px of the plates
TRIM = 50 * SCALE         # deg eaten per side by the border=50 hipsgen param
DEC_TOP = 2.0             # post-trim northern limit of the southern coverage
FIELD_INSET = 55          # px: an MDW pixel deeper than this inside a field
                          # counts as MDW-covered (border=50 trim + safety)


def _load_map(path):
    hdr = fits.getheader(path)
    dat = fits.getdata(path).astype(np.float64)
    return dat, hdr["CD1_1"], hdr["CD2_2"], hdr["CRPIX1"], hdr["CRPIX2"]


def _sampler(path):
    MDAT, CD1, CD2, CRP1, CRP2 = _load_map(path)

    def sample(l, b):
        l = np.mod(np.asarray(l, float) + 180.0, 360.0) - 180.0
        x = (l / CD1) + (CRP1 - 1.0)
        y = (np.asarray(b, float) / CD2) + (CRP2 - 1.0)
        x0 = np.floor(x).astype(int)
        y0 = np.clip(np.floor(y).astype(int), 0, MDAT.shape[0] - 2)
        fx, fy = x - x0, y - y0
        xw = lambda i: np.mod(i, MDAT.shape[1])
        return (MDAT[y0, xw(x0)] * (1 - fx) * (1 - fy) +
                MDAT[y0, xw(x0 + 1)] * fx * (1 - fy) +
                MDAT[y0 + 1, xw(x0)] * (1 - fx) * fy +
                MDAT[y0 + 1, xw(x0 + 1)] * fx * fy)

    return sample


def _mtf(m, x):
    return ((m - 1.0) * x) / (((2.0 * m - 1.0) * x) - m)


def _tone(R):
    R = gaussian_filter(R, SMOOTH_SIG_DEG / SCALE)
    jy = A_FIT * R + C_FIT
    mp = (0.0 - MTF_SHADOW) / (MTF_WHITE - MTF_SHADOW)
    mid = mp * (B_BG - 1.0) / (2.0 * B_BG * mp - B_BG - mp)
    return _mtf(mid, np.clip((jy - MTF_SHADOW) / (MTF_WHITE - MTF_SHADOW),
                             0.0, 1.0))


def _write_int16(v, hdr, carved, dst):
    i16 = np.round(np.clip(v, 0.0, 1.0) * STAGE_SCALE).astype(np.int16)
    if carved is not None:
        i16[carved] = STAGE_BLANK
    hdu = fits.PrimaryHDU(data=i16, header=hdr)
    # AFTER construction: PrimaryHDU(header=...) silently strips scaling
    # keywords from a pre-built header (hipsgen then reads raw ints against
    # dataRange=0 1 and blanks the whole plate -- bit us in the pilot).
    hdu.header["BSCALE"] = 1.0 / STAGE_SCALE
    hdu.header["BZERO"] = 0.0
    hdu.header["BLANK"] = STAGE_BLANK
    tmp = dst + ".tmp"
    hdu.writeto(tmp, overwrite=True, output_verify="silentfix")
    os.replace(tmp, dst)


def _mdw_footprints(stagedir, dec_max):
    """WCS of every staged MDW field that can reach the carve band."""
    out = []
    for p in sorted(glob.glob(os.path.join(stagedir, "[0-9]*.fits"))):
        hdr = fits.getheader(p)
        if float(hdr.get("CRVAL2", 90.0)) > dec_max:
            continue
        out.append(WCS(hdr))
    return out


def _carve(RA, DE, footprints):
    carved = np.zeros(RA.shape, bool)
    for w in footprints:
        x, y = w.wcs_world2pix(RA.ravel(), DE.ravel(), 0)
        carved |= ((x > FIELD_INSET) & (x < 3999 - FIELD_INSET) &
                   (y > FIELD_INSET) & (y < 3999 - FIELD_INSET)
                   ).reshape(RA.shape)
    return carved


def _car_plate(sample, footprints, ra_lo, ra_hi, dec_lo, dec_hi, dst):
    """Equatorial plate-carree strip (CRVAL2=0 so the projection stays plain;
    the reference row may lie far outside the image, which is standard)."""
    nx = int(round((ra_hi - ra_lo) / SCALE))
    ny = int(round((dec_hi - dec_lo) / SCALE))
    ra = ra_lo + (np.arange(nx) + 0.5) * SCALE
    dec = dec_lo + (np.arange(ny) + 0.5) * SCALE
    RA, DE = np.meshgrid(ra, dec)
    g = SkyCoord(ra=RA.ravel() * u.deg, dec=DE.ravel() * u.deg,
                 frame="fk5").galactic
    v = _tone(sample(g.l.deg, g.b.deg).reshape(RA.shape))
    carved = _carve(RA, DE, footprints) if footprints else None
    hdr = fits.Header()
    hdr["CTYPE1"], hdr["CTYPE2"] = "RA---CAR", "DEC--CAR"
    hdr["CUNIT1"] = hdr["CUNIT2"] = "deg"
    hdr["CRVAL1"], hdr["CRVAL2"] = ra_lo, 0.0
    hdr["CRPIX1"] = 0.5
    hdr["CRPIX2"] = 0.5 - dec_lo / SCALE
    hdr["CD1_1"], hdr["CD1_2"] = SCALE, 0.0
    hdr["CD2_1"], hdr["CD2_2"] = 0.0, SCALE
    hdr["EQUINOX"] = 2000.0
    _write_int16(v, hdr, carved, dst)
    cf = carved.mean() if carved is not None else 0.0
    print(f"   {os.path.basename(dst)}: {nx}x{ny}px RA[{ra_lo:.0f}..{ra_hi:.0f}]"
          f" Dec[{dec_lo:.1f}..{dec_hi:.1f}] carved={cf * 100:.1f}%")


def _polar_plate(sample, half_deg, dst):
    """Gnomonic cap centred on the south celestial pole. The pixel->sky
    mapping is taken FROM the written WCS itself (astropy), so the header and
    the data cannot disagree about the TAN-at-pole conventions."""
    n = int(round(2 * half_deg / SCALE))
    hdr = fits.Header()
    hdr["CTYPE1"], hdr["CTYPE2"] = "RA---TAN", "DEC--TAN"
    hdr["CUNIT1"] = hdr["CUNIT2"] = "deg"
    hdr["CRVAL1"], hdr["CRVAL2"] = 0.0, -90.0
    hdr["CRPIX1"] = hdr["CRPIX2"] = (n + 1) / 2.0
    hdr["CD1_1"], hdr["CD1_2"] = SCALE, 0.0
    hdr["CD2_1"], hdr["CD2_2"] = 0.0, SCALE
    hdr["EQUINOX"] = 2000.0
    w = WCS(hdr)
    xs, ys = np.meshgrid(np.arange(n), np.arange(n))
    ra, dec = w.wcs_pix2world(xs.ravel(), ys.ravel(), 0)
    g = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="fk5").galactic
    v = _tone(sample(g.l.deg, g.b.deg).reshape(n, n))
    _write_int16(v, hdr, None, dst)
    print(f"   {os.path.basename(dst)}: {n}x{n}px polar cap "
          f"(Dec <= ~{-(90 - half_deg):.0f} at edge midpoints)")


def generate(map_path, stagedir):
    print(f"== WHAM southern plates -> {stagedir} ==")
    sample = _sampler(map_path)
    foot = _mdw_footprints(stagedir, DEC_TOP + 2.5)
    print(f"   carving against {len(foot)} staged MDW boundary fields")
    bands = [(-28.5, DEC_TOP), (-56.5, -26.5), (-73.0, -54.5)]
    chunks = [(0.0, 92.0), (90.0, 182.0), (180.0, 272.0), (270.0, 362.0)]
    for bi, (d0, d1) in enumerate(bands):
        fp = foot if d1 >= -2.0 else []      # only band A can touch MDW
        for ci, (r0, r1) in enumerate(chunks):
            _car_plate(sample, fp, r0 - TRIM, r1 + TRIM, d0 - TRIM, d1 + TRIM,
                       os.path.join(stagedir, f"wham_b{bi}c{ci}.fits"))
    _polar_plate(sample, 19.0 + TRIM, os.path.join(stagedir, "wham_pole.fits"))
    print("== WHAM plates done ==")


def main():
    ap = argparse.ArgumentParser(description="Stage WHAM southern Hα plates.")
    ap.add_argument("--map", required=True, help="WHAM int-grid FITS path")
    ap.add_argument("--staging", required=True,
                    help="staging16 dir (already holding the MDW fields)")
    args = ap.parse_args()
    generate(args.map, args.staging)


if __name__ == "__main__":
    main()
