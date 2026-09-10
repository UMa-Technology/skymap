#!/usr/bin/env python3
"""Build the offline Hα sky-survey HiPS from the MDW DR1 star-removed fields.

End-to-end pipeline (proven on the North America / Pelican pilot, fields
1518+1519); see the internal design notes.

  1. select fields  - from MDW's DR1 CSV manifest (a field list, or an RA/Dec
                      box, or the whole northern survey).
  2. download       - the star-removed ("*_infilled.fits") product per field.
                      MDW's TLS chain is broken, so we fetch with curl -k.
  3. flatten        - subtract a low-order 2D polynomial background per field
                      (source-masked) to remove vignetting/gradient, so
                      overlapping fields agree and no seam is baked in.
  4. stretch        - ONE global Siril-style MTF (midtones transfer function)
                      applied to every field, from FIXED flux anchors (see
                      MTF_SHADOW/MTF_WHITE). Highlights compress instead of
                      clipping; faint Hα stays visible; a single global param
                      set means it does not reintroduce a seam. Adapted for an
                      additive overlay: B_BG ~0.12, not Siril's 0.25 (which
                      would wash the field over the star map).
  5. stage          - write the stretched field as int16 (BSCALE=1/32000,
                      BLANK) into staging16/: half the bytes of float32 at a
                      precision (1/32000) far beyond the 8-bit JPEG target, so
                      ALL fields fit on disk at once; then drop the raw FITS.
  6. hipsgen        - ONE pass over every staged field, reprojected to a
                      HEALPix HiPS at Norder 7 (native ~3.2"/px), with
                      mode=overlayFading feathering the field overlaps (the
                      seam fix). Single-pass is a CORRECTNESS requirement: the
                      batched APPEND path silently corrupts the pyramid
                      (mergeOverwrite instead of a weighted merge, border=50
                      dropped for the internal temp build, and batch-only sky
                      missing from the upper orders) -- never batch the build.
                      Needs an OLD JDK: JDK 24+ removed javax.swing.JApplet and
                      the (old Aladin) Hipsgen.jar crashes -> use openjdk@11.
  7. assemble       - keep only the image tiles + properties, set
                      hips_tile_format and hips_order_min>=1 (the engine only
                      loads a Norder0 allsky when order_min==0, which hipsgen
                      does not produce -> mismatched allsky = tiles jump).

Disk budget for the full northern run: raws live only within a batch (--batches
bounds that), staging is 2115 fields * ~64 MB ~= 132 GB, and the build's int16
FITS tiles add ~100 GB before assemble -> peak ~235 GB. The raw->staging step
never modifies the downloaded file in place, so an interrupted run resumes
cleanly: staged fields are skipped, half-processed fields restart from the raw.

Usage:
  # pilot (what shipped):
  make-halpha-survey.py --fields 1518,1519
  # a sky region (RA in HOURS, Dec in degrees):
  make-halpha-survey.py --box "20.4 21.4 43 47"
  # the whole northern survey (heavy: ~270 GB download, hours):
  make-halpha-survey.py --all-north
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats

CSV_URL = "https://mdw.astro.columbia.edu/js/MDW_DR1_web_v2.1.csv"
# Per-field download paths come from the manifest's starless column and MUST
# NOT be templated: the product version differs per field (V0/V2/V2.1) and so
# does the host dir (downloads2/downloads3). A hardcoded "downloads3/...V2"
# template 404-skipped 42% of the survey -- silently, thanks to skip-on-fail.
BASE_URL = "https://mdw.astro.columbia.edu/"

# --- flatten (seam fix) -----------------------------------------------------
FLAT_ORDER = 2       # 2D background polynomial order
FLAT_SIGMA = 2.5     # clip sources brighter than this * sigma before fitting
FLAT_DECIM = 6       # sub-sample stride for the least-squares fit

# --- stretch (tone) ---------------------------------------------------------
# FIXED, flux-calibrated MTF anchors (data is BUNIT=Jy + MAGZP; per-field flatten
# centers each background at ~0). Using the validated NA-nebula pilot's shadow and
# white as CONSTANTS -- not data percentiles/MADN -- gives identical tone across
# all 2115 fields, immune to BOTH failure modes we hit: (a) outlier fields -- a
# saturated-star residual spiked one field's max to ~1866 Jy and poisoned a
# percentile-100 white point (crushed faint fields dark, blew bright nebulae);
# (b) field-mix drift -- a data-driven shadow (median - 2.8*MADN) tones a
# faint-field batch darker than a bright one.
MTF_SHADOW = -0.00032   # shadow clip in Jy (pilot: median - 2.8*MADN)
MTF_WHITE = 0.05        # white point in Jy (pilot bright-Hα peak ~0.049)

# --- staging (disk) ----------------------------------------------------------
STAGE_SCALE = 32000     # stretched [0,1] -> int16 counts (precision 1/32000)
STAGE_BLANK = -32768    # FITS integer null for the NaN (invalid) pixels


def sh(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def load_manifest(work):
    path = os.path.join(work, "MDW_DR1_web_v2.1.csv")
    if not os.path.exists(path):
        sh(["curl", "-k", "-sL", "--max-time", "120", "-o", path, CSV_URL])
    rows = []
    with open(path) as fh:
        next(fh)  # header
        for line in fh:
            c = line.rstrip("\n").split(",")
            if len(c) >= 7:
                rows.append({"field": c[1], "ra": float(c[2]),
                             "dec": float(c[3]), "starless": c[6]})
    return rows


def select(rows, args):
    if args.fields:
        want = set(args.fields.split(","))
        return [r for r in rows if r["field"] in want]
    if args.box:
        r0, r1, d0, d1 = map(float, args.box.split())
        return [r for r in rows if r0 <= r["ra"] <= r1 and d0 <= r["dec"] <= d1]
    return rows  # --all-north


def _fits_complete(path):
    """True if the file opens as FITS and its last data row is readable --
    a size check alone let TRUNCATED files (from a killed run) be treated as
    complete and staged as garbage."""
    try:
        with fits.open(path) as hdul:
            d = hdul[0].data
            if d is None:
                return False
            float(d[-1, -1])      # force the last data block off the disk
            return True
    except Exception:
        return False


def _download_one(r, fitsdir):
    dst = os.path.join(fitsdir, f"{r['field']}.fits")
    if os.path.exists(dst):
        if os.path.getsize(dst) > 1_000_000 and _fits_complete(dst):
            return None                   # verified complete
        os.remove(dst)                    # partial/corrupt -> refetch
    url = BASE_URL + r["starless"].lstrip("/")
    for _ in range(4):                    # curl retry+resume, then whole-field
        try:                              # retries; give up -> skip, don't abort
            subprocess.run(
                ["curl", "-k", "-sL", "--fail", "--retry", "5",
                 "--retry-delay", "5", "--connect-timeout", "30",
                 "--max-time", "1200", "-C", "-", "-o", dst, url], check=True)
            if _fits_complete(dst):
                return None
        except subprocess.CalledProcessError:
            continue
    if os.path.exists(dst):
        os.remove(dst)
    return r["field"]                     # failed -> caller logs it


def download(rows, fitsdir, workers):
    # N-way parallel to beat MDW's per-connection speed cap, which is the run's
    # dominant cost (a single stream is ~6 MB/s -> ~13 h for the full ~264 GB).
    os.makedirs(fitsdir, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        skipped = [f for f in ex.map(lambda r: _download_one(r, fitsdir), rows)
                   if f]
    if skipped:
        print(f"  WARNING: skipped {len(skipped)} field(s): {skipped[:15]}")
    print(f"  downloaded {len(rows) - len(skipped)}/{len(rows)}")
    return len(skipped)


def _design(x, y, order):
    cols = [(x ** i) * (y ** j)
            for i in range(order + 1) for j in range(order + 1 - i)]
    return np.column_stack(cols)


def flatten_array(d):
    h, w = d.shape
    yy, xx = np.mgrid[0:h, 0:w]
    xn = (xx / (w - 1)) * 2 - 1
    yn = (yy / (h - 1)) * 2 - 1
    valid = np.isfinite(d) & (d != 0)
    _, med, std = sigma_clipped_stats(d[valid], sigma=FLAT_SIGMA, maxiters=5)
    bkg = valid & (d < med + FLAT_SIGMA * std) & (d > med - 5 * std)
    strd = np.zeros_like(d, bool)
    strd[::FLAT_DECIM, ::FLAT_DECIM] = True
    m = bkg & strd
    coef, *_ = np.linalg.lstsq(_design(xn[m], yn[m], FLAT_ORDER),
                               d[m], rcond=None)
    model = np.zeros_like(d)
    k = 0
    for i in range(FLAT_ORDER + 1):
        for j in range(FLAT_ORDER + 1 - i):
            model += coef[k] * (xn ** i) * (yn ** j)
            k += 1
    out = d - model
    out[~valid] = np.nan
    return out


def mtf(mid, x):
    return ((mid - 1.0) * x) / (((2.0 * mid - 1.0) * x) - mid)


def global_mtf_params(fitsdir, b_bg):
    # Fully deterministic from the fixed anchors (median ~ 0 after flatten): no
    # dependence on the field mix, so every batch tones identically -- the
    # validated pilot look -- with no outlier or drift sensitivity.
    shadow, hi = MTF_SHADOW, MTF_WHITE
    mp = (0.0 - shadow) / (hi - shadow)
    mid = mp * (b_bg - 1.0) / (2.0 * b_bg * mp - b_bg - mp)
    return shadow, hi, mid


def stretch_array(d, shadow, hi, mid):
    valid = np.isfinite(d)
    xp = np.clip((d - shadow) / (hi - shadow), 0.0, 1.0)
    out = mtf(mid, xp)
    out[~valid] = np.nan
    return out


def stage_int16(v, hdr, dst):
    """Write the stretched [0,1] field as an int16 FITS (tmp+rename: a crashed
    run never leaves a truncated file that would then be skipped as done)."""
    i = np.full(v.shape, STAGE_BLANK, np.int16)
    ok = np.isfinite(v)
    i[ok] = np.round(np.clip(v[ok], 0.0, 1.0) * STAGE_SCALE).astype(np.int16)
    hdu = fits.PrimaryHDU(data=i, header=hdr)
    hdu.header["BSCALE"] = 1.0 / STAGE_SCALE
    hdu.header["BZERO"] = 0.0
    hdu.header["BLANK"] = STAGE_BLANK
    tmp = dst + ".tmp"
    hdu.writeto(tmp, overwrite=True, output_verify="silentfix")
    os.replace(tmp, dst)


def process_field(src, dst, shadow, hi, mid):
    with fits.open(src) as hdul:
        d = hdul[0].data.astype(np.float64)
        hdr = hdul[0].header.copy()
    d[d == 0] = np.nan                    # MDW blank convention
    stage_int16(stretch_array(flatten_array(d), shadow, hi, mid), hdr, dst)


def run_hipsgen(java, jar, stagedir, hipsdir):
    # ONE pass over every staged field -- hipsgen APPEND must never be used
    # here: its cross-batch merge is mergeOverwrite (not weighted), it drops
    # border= for its internal temp build, and it loses batch-only sky from the
    # upper orders (all silently). mode=overlayFading is
    # THE inter-field seam fix: fields sit at different additive sky levels
    # (nightly airglow; MDW's calibration is point-source only), and the default
    # overlayMean hard-averages the overlap, so the contributor set jumps at the
    # overlap-band edge -> a visible line after the MTF stretch. Fading weights
    # each field by its distance to the image border, spreading the difference
    # across the ~20' overlap band.
    sh([java, "-Djava.awt.headless=true", "-Xmx8g", "-jar", jar,
        f"in={stagedir}", f"out={hipsdir}", "id=umatech/P/MDW/Halpha",
        "order=7", "border=50", "pixelCut=0 1 Linear", "dataRange=0 1",
        "mode=overlayFading", "-clean", "INDEX", "TILES", "JPEG"])


def resolve_params(fitsdir, b_bg, cache):
    """Compute the global MTF params once (from the first batch, an interleaved
    spread of the whole sky) and reuse them for every later batch, so the tone --
    and therefore the seamlessness -- is identical across batches."""
    if cache and os.path.exists(cache):
        p = json.load(open(cache))
        return p["shadow"], p["hi"], p["mid"]
    shadow, hi, mid = global_mtf_params(fitsdir, b_bg)
    if cache:
        json.dump({"shadow": shadow, "hi": hi, "mid": mid, "b_bg": b_bg},
                  open(cache, "w"))
    return shadow, hi, mid


def prepare_batch(rows, fitsdir, stagedir, args, cache, delete_raws):
    todo = [r for r in rows if not os.path.exists(
        os.path.join(stagedir, f"{r['field']}.fits"))]
    print(f"   {len(rows) - len(todo)} already staged, {len(todo)} to prepare")
    if not todo:
        return 0
    skipped = download(todo, fitsdir, args.workers)
    shadow, hi, mid = resolve_params(fitsdir, args.b_bg, cache)
    print(f"== flatten + stretch (shadow={shadow:.4g} white={hi:.4g} "
          f"mid={mid:.4g}) + stage ==")
    for r in todo:
        src = os.path.join(fitsdir, f"{r['field']}.fits")
        if not os.path.exists(src):
            continue                      # download gave up; already logged
        process_field(src, os.path.join(stagedir, f"{r['field']}.fits"),
                      shadow, hi, mid)
        if delete_raws:
            os.remove(src)
    return skipped


def assemble(hipsdir, out):
    if os.path.exists(out):
        sh(["rm", "-rf", out])
    os.makedirs(out, exist_ok=True)
    # image tiles + properties only (drop the FITS tiles + HpxFinder)
    sh(["rsync", "-a", "--include=*/", "--include=properties", "--include=*.jpg",
        "--exclude=*", hipsdir + "/", out + "/"])
    # engine hygiene: single tile format + order_min>=1 (avoid the order_min==0
    # Norder0-allsky path, which hipsgen does not populate -> tile displacement)
    props = os.path.join(out, "properties")
    lines = []
    for ln in open(props):
        if ln.startswith("hips_tile_format"):
            ln = "hips_tile_format     = jpeg\n"
        elif ln.startswith("hips_order_min"):
            ln = "hips_order_min       = 3\n"
        lines.append(ln)
    open(props, "w").writelines(lines)
    sh(["rm", "-rf", os.path.join(out, "HpxFinder"),
        os.path.join(out, "Norder0"), os.path.join(out, "Norder1"),
        os.path.join(out, "Norder2")])
    # NOTE: for production sharpness, re-encode the .jpg tiles to WebP Q90 here
    # (the engine prefers webp; smaller + sharper per byte, like the DSS survey).


def main():
    ap = argparse.ArgumentParser(description="Build the MDW Hα HiPS survey.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fields", help="comma-separated field ids, e.g. 1518,1519")
    g.add_argument("--box", help="'ra0 ra1 dec0 dec1'  (RA in hours)")
    g.add_argument("--all-north", action="store_true", help="whole DR1 (~270GB)")
    ap.add_argument("--batches", type=int, default=1,
                    help="split download+preprocess into N disk-bounded batches"
                         " (raws deleted per batch once staged); the HiPS build"
                         " itself is always ONE hipsgen pass over the staging")
    ap.add_argument("--workers", type=int, default=3,
                    help="parallel download streams (per-connection speed cap is"
                         " the bottleneck; keep modest to be nice to MDW)")
    ap.add_argument("--b-bg", type=float, default=0.12,
                    help="MTF target background (overlay tone knob; 0.12 ship)")
    ap.add_argument("--wham-map", default=None,
                    help="WHAM DR1 int-grid FITS: also stage the southern sky"
                         " (make-wham-south.py plates, carved against the"
                         " staged MDW fields) before the hipsgen pass")
    ap.add_argument("--work", default="tools/halpha-build/prod")
    ap.add_argument("--out", default="apps/skydata/surveys/halpha")
    ap.add_argument("--java", default="/opt/homebrew/opt/openjdk@11/bin/java")
    ap.add_argument("--jar", default="tools/halpha-build/Hipsgen.jar")
    args = ap.parse_args()

    fitsdir = os.path.join(args.work, "fits")
    stagedir = os.path.join(args.work, "staging16")
    hipsdir = os.path.join(args.work, "hips")
    os.makedirs(args.work, exist_ok=True)
    os.makedirs(stagedir, exist_ok=True)
    cache = os.path.join(args.work, "stretch_params.json")

    rows = select(load_manifest(args.work), args)
    if not rows:
        sys.exit("no fields matched the selection")
    batches = max(1, args.batches)
    print(f"== {len(rows)} field(s), {batches} prepare batch(es) ==")
    total_skipped = 0
    for bi in range(batches):
        brows = rows[bi::batches]
        print(f"== prepare batch {bi + 1}/{batches}: {len(brows)} fields ==")
        total_skipped += prepare_batch(brows, fitsdir, stagedir, args, cache,
                                       delete_raws=(batches > 1))
    if total_skipped > 10:
        # a hole-ridden survey must never be built silently: fix the cause and
        # re-run (staged fields are skipped, so a re-run only fetches the rest)
        sys.exit(f"ABORT before hipsgen: {total_skipped} fields failed to "
                 f"download -- that is coverage loss, not flakiness.")
    if total_skipped:
        print(f"  WARNING: proceeding with {total_skipped} missing field(s)")
    if args.wham_map:
        # southern sky: rendered AFTER the northern prepare so the carve can
        # read the actual staged field footprints (a failed/missing field must
        # not punch a hole in the southern coverage)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "wham", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "make-wham-south.py"))
        wham = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wham)
        wham.generate(args.wham_map, stagedir)
    print("== hipsgen (ONE pass over the whole staging) ==")
    run_hipsgen(args.java, args.jar, stagedir, hipsdir)
    print("== assemble ==")
    assemble(hipsdir, args.out)
    print(f"== done -> {args.out} ==")


if __name__ == "__main__":
    main()
