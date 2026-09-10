#!/usr/bin/env python
"""protect_mask.py -- extended-structure protection mask for the DSS starless pipeline.

IRON RULE (starless_design.md Stage 0 item 2): pixels inside this mask must
NEVER be altered by star removal / background processing.

Recipe (validated in photutils_exp3/exp4 + galmask-chain tests, thresholds fit
on ground-truthed tiles 169/M31, 1040/NGC253+NGC288, 1252/quiet, 1890/Barnard,
2068/LMC):
  * luminance (Rec.709), detection on convolved image (gaussian fwhm=3);
  * GLOBAL fixed-DN thresholds (galmask finding: per-tile sigma thresholds jump
    at tile borders); every background is computed on the APRON canvas (640px =
    tile + 64px of REAL neighbour pixels, apron.assemble_apron) so thresholds
    have no tile-border discontinuity; masks are cropped back to 512.
  * TWO backgrounds, both iteratively refined (estimate-detect-mask-re-estimate,
    astrocomputing ch6):
      - fine   = box16/MedianBackground: threshold of the compact pass
        (+2.5 DN). Rides on the plate fog, so 1-3 DN fog texture is NOT
        detected on quiet tiles (a box64 threshold bg was measured to merge
        fog sheets into 10k-px false "extended" segments on tile 1252);
      - coarse = box64/MMMBackground: threshold of the faint-diffuse pass
        (+1.2 DN) and of the dark pass (-2.5 DN). Needed because the fine bg
        self-absorbs large structure (M31 visible-disk containment 48% with
        box16-only vs ~95% with the coarse diffuse pass).
  * compact pass: detect(conv fwhm3, fine_bg+2.5, n_pixels=10); SourceCatalog
    gating: extended iff area>=400 | semimajor>8px | r50>6px; extended
    dilated by 15px = PROTECTION; compact dilated by 3px = star mask
    (removable, NOT protection);
  * bright-star HALO VETO (nightlight HFR-ratio idea): an "extended" segment
    is reclassified as a star (removable) iff annulus(10-14px)/core(<=2.5px)
    mean ratio around the PEAK pixel < 0.20 AND >=25% of the segment flux lies
    within 9px of the peak. Separates bright-star veiling halos from galaxy
    bodies: NGC253 core ratio=0.24 (kept), M31=0.86 (kept), star halos
    0.03-0.16 (vetoed). Compact globulars (NGC288 ratio=0.03) are also vetoed
    -> they must be protected by the DSO-catalog-ellipse union stage, NOT by
    this detector.
  * faint-diffuse pass (exp3 pass 2): detect(conv fwhm12, coarse_bg+1.2,
    n_pixels=300); a blob is kept ONLY if it touches a kept (protected)
    compact-pass extended segment of >=2000px -- the pass exists to extend the
    faint skirts of real DSO bodies (M31 outer disk), while isolated
    low-amplitude blobs are plate fog and must stay flattenable (and a fog
    sheet touching some small extended blob must not be anchored by it).
    Kept blobs are protected whole: compact knots and bright-star halos
    superposed on a DSO skirt are inside the protection (DSO fidelity beats
    star removal there; the engine draws its own stars on top anyway).
  * dark-nebula reverse gate (astrocomputing ch6): detect on
    (coarse_bg - img) > 2.5 DN; extended gating as above PLUS a depth gate
    max(bg-img) >= 6 DN (real dark structure: Barnard 8-15 DN, LMC lanes
    13-55 DN, M31 dust lanes 14 DN; quiet-tile fog lows are 3.4-5.3 DN).

API:  protect_mask(rgb_512, apron_rgb_640=None) -> (mask_bool_512, segm_info)
CLI:  python protect_mask.py <npix> [<npix> ...] [--order 4]
        -> diag8/protect_<npix>.png overlay (red boundary = bright-extended
           protection, yellow boundary = dark-nebula protection) + stats.
"""
import os
import sys
import time
import warnings

import numpy as np
import scipy.ndimage as ndi
from astropy.stats import SigmaClip
from astropy.convolution import convolve
from photutils.background import Background2D, MedianBackground, MMMBackground
from photutils.segmentation import (detect_sources, make_2dgaussian_kernel,
                                    SourceCatalog)

PEQ = os.path.dirname(os.path.abspath(__file__))
LUMW = np.array([0.2126, 0.7152, 0.0722], np.float32)
SC = SigmaClip(sigma=3.0, maxiters=10)

PARAMS = dict(
    thresh_dn=2.5,        # global fixed-DN threshold above fine background
    n_pixels=10,          # min segment size, compact pass (photutils 3.0 name)
    fwhm=3.0,             # detection kernel FWHM (px), compact pass
    diffuse_dn=1.2,       # fixed-DN threshold of the faint-diffuse pass
    diffuse_fwhm=12.0,    # kernel FWHM of the diffuse pass
    diffuse_npix=300,     # min segment size of the diffuse pass
    fine_box=16,          # compact-pass threshold bg (rides on plate fog)
    fine_est="median",
    coarse_box=64,        # diffuse/dark-pass threshold bg
    coarse_est="mmm",
    n_refine=2,           # estimate-detect-mask-re-estimate iterations
    ext_area=400,         # extended if area >= this ...
    ext_smaj=8.0,         # ... or semimajor axis > this (px)
    ext_r50=6.0,          # ... or half-flux radius > this (px)
    ext_dilate=15,        # dilation radius (px) for extended -> protection
    star_dilate=3,        # dilation radius (px) for compact -> star mask
    max_bg_mask_frac=0.90,  # skip bg re-estimate when mask covers more
    # bright-star halo veto (fit on 169/1040/1252 ground truth, see header)
    veto_ratio=0.20,      # annulus/core mean ratio below this ...
    veto_fpeak=0.25,      # ... AND flux fraction within 9px of peak above this
    veto_max_area=20000,  # never veto truly huge segments (M31 body = 50k px)
    dark_min_depth=6.0,   # dark segment must reach this depth below coarse bg
    diffuse_seed_area=2000,  # diffuse blob kept only if touching a kept
                             # pass-1 extended segment at least this big
)


def _disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def _lum(img):
    img = np.asarray(img, np.float32)
    return img @ LUMW if img.ndim == 3 else img


def _val(q):
    return np.atleast_1d(getattr(q, "value", q)).astype(float)


def _bg(canvas, box, est, mask=None):
    bkg = MMMBackground() if est == "mmm" else MedianBackground()
    return Background2D(canvas, box_size=box, filter_size=3, sigma_clip=SC,
                        bkg_estimator=bkg, mask=mask,
                        exclude_percentile=90.0).background


def _gate(diff, segm, p, is_dark):
    """SourceCatalog gating -> (table dict, extended labels, compact labels)."""
    cat = SourceCatalog(diff, segm)
    area = _val(cat.area)
    smaj = _val(cat.semimajor_axis)
    ell = _val(cat.ellipticity)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r50 = _val(cat.flux_radius(0.5))       # photutils 3.0 name
    r50g = np.where(np.isfinite(r50), r50, 0.0)  # NaN never passes the gate
    extended = (area >= p["ext_area"]) | (smaj > p["ext_smaj"]) | (r50g > p["ext_r50"])
    labels = np.asarray(cat.labels)
    table = dict(label=labels, area=area, ellipticity=ell, semimajor=smaj,
                 r50=r50, is_extended=extended,
                 is_dark=np.full(labels.size, is_dark, bool),
                 halo_ratio=np.full(labels.size, np.nan),
                 fpeak9=np.full(labels.size, np.nan),
                 is_halo_veto=np.zeros(labels.size, bool),
                 dark_depth=np.full(labels.size, np.nan))
    return table, labels[extended], labels[~extended]


def _halo_veto(canvas, diff, segm, ext_labels, table, p):
    """Bright-star halo veto (see module header). Returns (kept, vetoed)
    label arrays and records per-segment features in `table`."""
    if len(ext_labels) == 0:
        return ext_labels, np.array([], int)
    yy, xx = np.mgrid[0:canvas.shape[0], 0:canvas.shape[1]]
    dpos = np.maximum(diff, 0)
    kept, vetoed = [], []
    for lab in ext_labels:
        i = int(np.where(table["label"] == lab)[0][0])
        m = segm.data == lab
        if table["area"][i] >= p["veto_max_area"]:
            kept.append(lab)
            continue
        py, px = ndi.maximum_position(np.where(m, canvas, -np.inf))
        r = np.hypot(yy - py, xx - px)
        core = diff[r <= 2.5].mean()
        annm = (r >= 10) & (r <= 14) & m
        ann = diff[annm].mean() if annm.any() else 0.0
        ratio = ann / max(core, 1e-6)
        fpeak9 = dpos[m & (r <= 9)].sum() / max(dpos[m].sum(), 1e-6)
        table["halo_ratio"][i] = ratio
        table["fpeak9"][i] = fpeak9
        if ratio < p["veto_ratio"] and fpeak9 >= p["veto_fpeak"]:
            table["is_halo_veto"][i] = True
            vetoed.append(lab)
        else:
            kept.append(lab)
    return np.asarray(kept, int), np.asarray(vetoed, int)


def _label_mask(segm, labels, dilate_r):
    if segm is None or len(labels) == 0:
        return None
    m = np.isin(segm.data, labels)
    if dilate_r > 0:
        m = ndi.binary_dilation(m, structure=_disk(dilate_r))
    return m


def _cat_tables(tables):
    if not tables:
        keys = ("label", "area", "ellipticity", "semimajor", "r50",
                "is_extended", "is_dark", "halo_ratio", "fpeak9",
                "is_halo_veto", "dark_depth")
        return {k: np.array([]) for k in keys}
    return {k: np.concatenate([t[k] for t in tables]) for k in tables[0]}


def protect_mask(rgb_512, apron_rgb_640=None, **kw):
    """Extended-structure protection mask.

    rgb_512       : (512,512,3) or (512,512) image, 8-bit DN scale.
    apron_rgb_640 : optional (512+2a, 512+2a[,3]) apron canvas whose margins are
                    REAL neighbour pixels (apron.assemble_apron). If given, all
                    statistics are computed on it and cropped back to the tile.

    Returns (mask_bool_512, segm_info) where segm_info holds:
      table       per-segment dict of arrays: label, area, ellipticity,
                  semimajor, r50, is_extended, is_dark
      star_mask   compact/star segments dilated star_dilate px (removable,
                  NOT protection), cropped to the tile
      mask_bright / mask_dark  the two protection components (tile crop)
      localbg     final local background (tile crop)
      coverage / star_coverage / params
    """
    p = dict(PARAMS)
    p.update(kw)
    tile = _lum(rgb_512)
    th, tw = tile.shape
    if apron_rgb_640 is not None:
        canvas = _lum(apron_rgb_640)
        a = (canvas.shape[0] - th) // 2
    else:
        canvas, a = tile, 0
    crop = (slice(a, a + th), slice(a, a + tw))

    k1 = make_2dgaussian_kernel(p["fwhm"], size=5)
    conv = convolve(canvas, k1)
    k2 = make_2dgaussian_kernel(p["diffuse_fwhm"], size=25)
    conv2 = convolve(canvas, k2)

    # --- two iteratively-refined backgrounds (astrocomputing ch6) ----------
    fine = _bg(canvas, p["fine_box"], p["fine_est"])
    coarse = _bg(canvas, p["coarse_box"], p["coarse_est"])
    segb = segd = None
    for it in range(p["n_refine"] + 1):
        segb = detect_sources(conv, fine + p["thresh_dn"], n_pixels=p["n_pixels"])
        segd = detect_sources(coarse - conv, p["thresh_dn"], n_pixels=p["n_pixels"])
        if it == p["n_refine"]:
            break
        m = np.zeros(canvas.shape, bool)
        for s in (segb, segd):
            if s is not None:
                m |= s.data > 0
        m = ndi.binary_dilation(m, structure=_disk(3))
        if not m.any() or m.mean() > p["max_bg_mask_frac"]:
            break
        fine = _bg(canvas, p["fine_box"], p["fine_est"], mask=m)
        coarse = _bg(canvas, p["coarse_box"], p["coarse_est"], mask=m)

    prot_b = np.zeros(canvas.shape, bool)
    prot_d = np.zeros(canvas.shape, bool)
    star = np.zeros(canvas.shape, bool)
    pass1_kept = np.zeros(canvas.shape, bool)
    tables = []

    # --- pass 1: compact detection, bright, + halo veto ---------------------
    if segb is not None:
        diff = canvas - fine
        tbl, ext_lab, cmp_lab = _gate(diff, segb, p, is_dark=False)
        ext_lab, halo_lab = _halo_veto(canvas, diff, segb, ext_lab, tbl, p)
        tables.append(tbl)
        # diffuse-pass seeds: kept extended segments big enough to be a real
        # DSO body (small kept blobs must not anchor whole fog sheets)
        seed_lab = ext_lab[np.isin(ext_lab, tbl["label"][
            tbl["area"] >= p["diffuse_seed_area"]])] if len(ext_lab) else ext_lab
        if len(seed_lab):
            pass1_kept = np.isin(segb.data, seed_lab)
        m = _label_mask(segb, ext_lab, p["ext_dilate"])
        if m is not None:
            prot_b |= m
        m = _label_mask(segb, cmp_lab, p["star_dilate"])
        if m is not None:
            star |= m
        m = _label_mask(segb, halo_lab, p["star_dilate"])
        if m is not None:
            star |= m

    # --- pass 2: faint diffuse emission (exp3 pass 2, fixed-DN) ------------
    # kept ONLY when touching a kept pass-1 extended segment (DSO skirt);
    # isolated low-amplitude blobs are plate fog and must stay flattenable.
    segf = detect_sources(conv2, coarse + p["diffuse_dn"], n_pixels=p["diffuse_npix"])
    if segf is not None and pass1_kept.any():
        keep = [lab for lab in segf.labels
                if pass1_kept[segf.data == lab].any()]
        m = _label_mask(segf, np.asarray(keep, int), p["ext_dilate"])
        if m is not None:
            # keep whole blobs: compact knots and even bright-star halos
            # superposed on a DSO skirt stay protected -- DSO fidelity beats
            # star removal there (the nu-And halo punched a 5.5k-px hole of
            # 8-DN real disk glow out of M31 when subtracted); standalone
            # halos never touch a seed, so they are still not protected
            prot_b |= m

    # --- dark-nebula reverse gate (astrocomputing ch6) ----------------------
    if segd is not None:
        tbl, ext_lab, _ = _gate(coarse - canvas, segd, p, is_dark=True)
        # depth gate: real dark structure reaches >= dark_min_depth below bg
        tbl["dark_depth"] = np.asarray(ndi.labeled_comprehension(
            coarse - canvas, segd.data, tbl["label"], np.max, float, 0.0))
        if len(ext_lab):
            deep = np.isin(tbl["label"], ext_lab) & (tbl["dark_depth"] >= p["dark_min_depth"])
            tbl["is_extended"] &= deep
            ext_lab = tbl["label"][deep & tbl["is_dark"]]
        tables.append(tbl)
        m = _label_mask(segd, ext_lab, p["ext_dilate"])
        if m is not None:
            prot_d |= m

    mask = (prot_b | prot_d)[crop]
    table = _cat_tables(tables)
    segm_info = dict(
        table=table,
        star_mask=(star & ~(prot_b | prot_d))[crop],
        mask_bright=prot_b[crop],
        mask_dark=prot_d[crop],
        localbg=fine[crop],
        coarsebg=coarse[crop],
        coverage=float(mask.mean()),
        star_coverage=float(star[crop].mean()),
        n_bright_ext=int((table["is_extended"] & ~table["is_dark"]
                          & ~table["is_halo_veto"]).sum()),
        n_dark_ext=int((table["is_extended"] & table["is_dark"]).sum()),
        n_compact=int((~table["is_extended"] & ~table["is_dark"]).sum()),
        n_halo_veto=int(table["is_halo_veto"].sum()),
        params=p,
    )
    return mask, segm_info


# ---------------------------------------------------------------------------
def asinh_stretch(rgb, soft=25.0):
    x = np.asarray(rgb, np.float32)
    return 255.0 * np.arcsinh(x / soft) / np.arcsinh(255.0 / soft)


def _boundary(m):
    if not m.any():
        return np.zeros(m.shape, bool)
    b = m ^ ndi.binary_erosion(m)
    return ndi.binary_dilation(b)


def make_overlay(rgb_512, info):
    vis = asinh_stretch(rgb_512)
    vis[_boundary(info["mask_dark"])] = [255, 220, 40]    # dark nebulae: yellow
    vis[_boundary(info["mask_bright"])] = [255, 40, 40]   # bright extended: red
    return np.clip(vis, 0, 255).astype(np.uint8)


def _cli():
    import argparse
    from PIL import Image
    sys.path.insert(0, PEQ)
    import apron as apron_mod

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("npix", nargs="+", type=int)
    ap.add_argument("--order", type=int, default=4)
    ap.add_argument("--apron", type=int, default=64)
    ap.add_argument("--no-apron", action="store_true")
    args = ap.parse_args()

    outdir = os.path.join(PEQ, "diag8")
    os.makedirs(outdir, exist_ok=True)
    for npix in args.npix:
        t0 = time.time()
        sub, _placed = apron_mod.assemble_apron(args.order, npix, args.apron)
        a = args.apron
        tile = sub[a:a + 512, a:a + 512]
        mask, info = protect_mask(tile, None if args.no_apron else sub)
        out = os.path.join(outdir, "protect_%d.png" % npix)
        Image.fromarray(make_overlay(tile, info)).save(out)

        t = info["table"]
        print("tile %d (order %d): protect %.1f%% (bright %.1f%% dark %.1f%%)  "
              "star-mask %.1f%%  segs: %d bright-ext, %d dark-ext, "
              "%d halo-veto, %d compact  [%.1fs]"
              % (npix, args.order, 100 * info["coverage"],
                 100 * info["mask_bright"].mean(),
                 100 * info["mask_dark"].mean(),
                 100 * info["star_coverage"],
                 info["n_bright_ext"], info["n_dark_ext"],
                 info["n_halo_veto"], info["n_compact"], time.time() - t0))
        ext = np.where(t["is_extended"])[0]
        for i in ext[np.argsort(t["area"][ext])[::-1][:6]]:
            kind = ("VETOED" if t["is_halo_veto"][i]
                    else "DARK  " if t["is_dark"][i] else "BRIGHT")
            print("    %s seg label=%d area=%dpx smaj=%.1f r50=%s ell=%.2f "
                  "halo_ratio=%s fpeak9=%s"
                  % (kind, t["label"][i], t["area"][i], t["semimajor"][i],
                     "%.1f" % t["r50"][i] if np.isfinite(t["r50"][i]) else "nan",
                     t["ellipticity"][i],
                     "%.2f" % t["halo_ratio"][i] if np.isfinite(t["halo_ratio"][i]) else "-",
                     "%.2f" % t["fpeak9"][i] if np.isfinite(t["fpeak9"][i]) else "-"))
        print("    -> %s" % out)


if __name__ == "__main__":
    _cli()
