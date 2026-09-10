"""Deterministic star detector for 8-bit DSS2 HiPS tiles.

Clean-room numpy/scipy re-implementation of the mlnoga/nightlight FindStars
*specification* (refs/nightlight/internal/star/findstars.go — GPL, spec only,
no code copied), adapted to 8-bit RGB webp tiles:

  1. local background  : 32px grid cells, interquartile mean ("trimmed median",
                         middle 50% of sorted cell pixels), bilinear-interp to
                         full res.  sigma = MAD*1.4826 of (lum-bg), global AND
                         per-cell (cell sigma floored at 0.7 DN, bilinear map).
  2. candidates        : (lum-bg) > max(k_sig*sigma_cell, abs_min), local max
                         via maximum_filter(size=3); saturated plateaus
                         (max-channel >= 250) are labeled and replaced by their
                         plateau *centroid* candidate.
  3. suppression       : brightest-first overlap suppression, radius 4 px.
  4. centroid          : iterative center-of-mass, window 2*ceil(hfr0)+3
                         clamped to [5,9] px, on bg-subtracted clipped data.
  5. HFR + point test  : half-flux radius (flux-weighted mean radius, r<=8) on
                         bg-subtracted data with a 1*sigma_cell noise floor
                         removed (8-bit adaptation: without it the positive
                         half of the noise in the 197-px window dominates the
                         radial moments of faint stars and inflates HFR/FWHM
                         ~2-3x, which also breaks the in/out test in crowded
                         fields); nightlight in/out flux-ratio test
                         innerMass*outerPix > starInOut*outerMass*innerPix
                         (inner r<=hfr, outer hfr<r<=2.5*hfr) rejects galaxy
                         cores / diffuse bumps.  Two crowding adaptations for
                         dense Milky-Way tiles: (a) the HFR/FWHM measurement
                         radius is capped at 0.6x the distance to the nearest
                         *significant* neighbor (peak >= 0.3x own peak),
                         (b) outerMass is computed robustly as
                         median(outer)*outerPix so a neighbor star that lands
                         in the annulus cannot fail a real point source
                         (a uniformly bright galaxy annulus still fails).
  6. FWHM window veto  : (ABIRL heuristic) stars with FWHM > fwhm_veto * field
                         median FWHM of accepted point sources are flagged
                         extended_suspect (=> protected, not removed).
                         Exempt: saturated stars (flat top inflates FWHM) and
                         BRIGHT stars (peak >= veto_bright_dn) whose in/out
                         contrast ratio >= inout_exempt (bright stars' wings
                         widen the FWHM naturally, but their inner/outer
                         contrast is overwhelming, unlike a galaxy core
                         sitting on its own envelope; the brightness gate
                         keeps the veto active for faint fuzz whose
                         noise-floored outer annulus is empty).

Everything is deterministic: exact statistics, no sampling, stable sort order.

API:   detect_stars(img[, localbg=...]) -> structured array
       fields: x,y,peak_dn,flux,hfr,fwhm,is_point,saturated,extended_suspect
       (peak_dn / flux are background-SUBTRACTED star amplitude / mass in DN)

CLI:   python star_detect.py <npix> [<npix>...]
       renders overlay PNGs to diag8/stars_<npix>.png
       (green circle r=2.5*hfr = is_point, red = extended_suspect)
"""
import os
import numpy as np
from scipy import ndimage

TW = 512
RAW = "/Users/larry/code/stellarium-web-engine/apps/skydata/surveys/dss"
PEQ = os.path.dirname(os.path.abspath(__file__))

STAR_DTYPE = np.dtype([
    ('x', 'f4'), ('y', 'f4'),
    ('peak_dn', 'f4'), ('flux', 'f4'),
    ('hfr', 'f4'), ('fwhm', 'f4'),
    ('is_point', '?'), ('saturated', '?'), ('extended_suspect', '?'),
])


# ---------------------------------------------------------------- helpers

def luminance(img):
    """RGB (H,W,3) or gray (H,W), float 0..1 or DN 0..255 -> luminance in DN."""
    a = np.asarray(img, dtype=np.float32)
    if a.ndim == 3:
        lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    else:
        lum = a.copy()
    if lum.max() <= 1.5:          # float 0..1 input
        lum *= 255.0
    return lum


def _maxchannel(img):
    a = np.asarray(img, dtype=np.float32)
    mc = a.max(axis=2) if a.ndim == 3 else a.copy()
    if mc.max() <= 1.5:
        mc = mc * 255.0
    return mc


def _bilinear_upsample(grid, cell, H, W):
    """Bilinear-interpolate a (ny,nx) per-cell grid (values at cell centers)
    to a full-res (H,W) map, clamped at the borders."""
    ny, nx = grid.shape
    gy = np.clip((np.arange(H, dtype=np.float64) + 0.5) / cell - 0.5, 0, ny - 1)
    gx = np.clip((np.arange(W, dtype=np.float64) + 0.5) / cell - 0.5, 0, nx - 1)
    y0 = np.floor(gy).astype(np.int64); fy = (gy - y0)[:, None]
    x0 = np.floor(gx).astype(np.int64); fx = (gx - x0)[None, :]
    y1 = np.minimum(y0 + 1, ny - 1); x1 = np.minimum(x0 + 1, nx - 1)
    g = grid.astype(np.float64)
    out = (g[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) +
           g[np.ix_(y0, x1)] * (1 - fy) * fx +
           g[np.ix_(y1, x0)] * fy * (1 - fx) +
           g[np.ix_(y1, x1)] * fy * fx)
    return out.astype(np.float32)


def local_background(lum, cell=32, sigma_floor=0.7):
    """Grid-cell trimmed background + robust sigma.

    Returns (bg_map, sigma_map, sigma_global):
      bg_map       full-res background (interquartile mean per cell, bilinear)
      sigma_map    full-res per-cell MAD*1.4826 sigma (floored), bilinear
      sigma_global MAD*1.4826 of (lum - bg_map) over the whole frame
    """
    H, W = lum.shape
    if H % cell or W % cell:
        raise ValueError(f"image dims {H}x{W} must be multiples of cell={cell}")
    ny, nx = H // cell, W // cell
    blocks = lum.reshape(ny, cell, nx, cell).transpose(0, 2, 1, 3)
    blocks = blocks.reshape(ny, nx, cell * cell)
    srt = np.sort(blocks, axis=2)
    n = cell * cell
    q = n // 4
    bg_cells = srt[:, :, q:n - q].mean(axis=2)          # interquartile mean
    bg = _bilinear_upsample(bg_cells, cell, H, W)

    resid = lum - bg
    rb = resid.reshape(ny, cell, nx, cell).transpose(0, 2, 1, 3)
    rb = rb.reshape(ny, nx, cell * cell)
    med = np.median(rb, axis=2, keepdims=True)
    mad = np.median(np.abs(rb - med), axis=2)
    sig_cells = np.maximum(mad * 1.4826, sigma_floor).astype(np.float32)
    sigma_map = _bilinear_upsample(sig_cells, cell, H, W)

    gmed = np.median(resid)
    sigma_global = float(np.median(np.abs(resid - gmed)) * 1.4826)
    return bg, sigma_map, sigma_global


def _disk_offsets(radius):
    r = int(np.ceil(radius))
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    keep = dy * dy + dx * dx <= radius * radius + 1e-6
    return dy[keep], dx[keep]


def _suppress_overlaps(ys, xs, peaks, sat, H, W, radius):
    """Brightest-first greedy suppression: drop any candidate whose (rounded)
    center falls within `radius` of an already-kept brighter star."""
    order = np.lexsort((xs, ys, -peaks))       # peak desc, then y, then x
    occ = np.zeros((H, W), dtype=bool)
    dy, dx = _disk_offsets(radius)
    keep_idx = []
    for i in order:
        iy = int(round(float(ys[i]))); ix = int(round(float(xs[i])))
        iy = min(max(iy, 0), H - 1);   ix = min(max(ix, 0), W - 1)
        if occ[iy, ix]:
            continue
        keep_idx.append(i)
        yy = np.clip(iy + dy, 0, H - 1)
        xx = np.clip(ix + dx, 0, W - 1)
        occ[yy, xx] = True
    keep_idx = np.array(keep_idx, dtype=np.int64)
    return ys[keep_idx], xs[keep_idx], peaks[keep_idx], sat[keep_idx]


def _window_sum(resid_pos, cy, cx, rad):
    """Return (values, dy grid, dx grid) of a window clamped to the image."""
    H, W = resid_pos.shape
    y0, y1 = max(cy - rad, 0), min(cy + rad + 1, H)
    x0, x1 = max(cx - rad, 0), min(cx + rad + 1, W)
    v = resid_pos[y0:y1, x0:x1]
    dy = np.arange(y0, y1, dtype=np.float32)[:, None] - cy
    dx = np.arange(x0, x1, dtype=np.float32)[None, :] - cx
    return v, dy, dx, y0, x0


def _quick_hfr(resid_pos, iy, ix, rad=4):
    v, dy, dx, _, _ = _window_sum(resid_pos, iy, ix, rad)
    d = np.sqrt(dy * dy + dx * dx)
    sel = d <= rad
    mass = float(v[sel].sum())
    if mass <= 0:
        return 1.0
    return float((v[sel] * d[sel]).sum() / mass)


def _refine_centroid(resid_pos, y, x, hfr0, max_rounds=10):
    """Iterative center-of-mass on bg-subtracted negative-clipped data.
    Window size 2*ceil(hfr0)+3 clamped to [5,9] px."""
    win = int(2 * np.ceil(hfr0) + 3)
    win = min(max(win, 5), 9)
    rad = win // 2
    H, W = resid_pos.shape
    cy, cx = float(y), float(x)
    for _ in range(max_rounds):
        iy = int(round(cy)); ix = int(round(cx))
        iy = min(max(iy, 0), H - 1); ix = min(max(ix, 0), W - 1)
        v, dy, dx, _, _ = _window_sum(resid_pos, iy, ix, rad)
        mass = float(v.sum())
        if mass <= 0:
            break
        ny = iy + float((v * dy).sum() / mass)
        nx = ix + float((v * dx).sum() / mass)
        shift2 = (ny - cy) ** 2 + (nx - cx) ** 2
        cy, cx = ny, nx
        if shift2 < 1e-4:                      # < 0.01 px
            break
    return cy, cx


# ---------------------------------------------------------------- detector

def detect_stars(img, localbg=None, cell=32, k_sig=4.0, abs_min=6.0,
                 radius=4.0, sat_dn=250.0, star_in_out=1.4, fwhm_veto=1.5,
                 r_hfr=8.0, min_veto_stars=8, inout_exempt=8.0,
                 veto_bright_dn=60.0):
    """Detect stars on an 8-bit tile (or assembled canvas).

    img      : (H,W,3) RGB or (H,W) luminance; float 0..1 or DN 0..255.
    localbg  : optional precomputed full-res luminance background map (DN).
    returns  : structured array (STAR_DTYPE), sorted by peak_dn descending.
               peak_dn and flux are background-subtracted (star amplitude).
               is_point         = passed in/out flux-ratio AND FWHM window
               saturated        = candidate came from a >=250 DN plateau
               extended_suspect = detected but NOT point-like (protect it)
    """
    lum = luminance(img)
    mchan = _maxchannel(img)
    H, W = lum.shape

    if localbg is not None:
        bg = np.asarray(localbg, dtype=np.float32)
        _, sigma_map, sigma_global = local_background(lum, cell=cell)
    else:
        bg, sigma_map, sigma_global = local_background(lum, cell=cell)

    resid = lum - bg
    resid_pos = np.clip(resid, 0.0, None)          # for centroiding (spec)
    resid_meas = np.clip(resid - sigma_map, 0.0, None)  # for HFR/FWHM/in-out

    # ---- candidates: threshold + 3x3 local maxima -----------------------
    thresh = np.maximum(k_sig * sigma_map, abs_min)
    above = resid > thresh
    maxf = ndimage.maximum_filter(resid, size=3, mode='nearest')
    cand_mask = above & (resid >= maxf)

    # ---- saturated plateaus -> centroid candidates -----------------------
    satmask = mchan >= sat_dn
    cand_mask &= ~satmask                       # plateau pixels handled below
    sat_ys = sat_xs = sat_pk = np.zeros(0, np.float32)
    if satmask.any():
        lab, nlab = ndimage.label(satmask, structure=np.ones((3, 3), int))
        idx = np.arange(1, nlab + 1)
        cys, cxs = np.zeros(nlab), np.zeros(nlab)
        coms = ndimage.center_of_mass(satmask, lab, idx)
        for k, (cy, cx) in enumerate(coms):
            cys[k], cxs[k] = cy, cx
        pks = ndimage.labeled_comprehension(resid, lab, idx, np.max, float, 0.0)
        sat_ys = cys.astype(np.float32)
        sat_xs = cxs.astype(np.float32)
        sat_pk = pks.astype(np.float32)

    cy_i, cx_i = np.nonzero(cand_mask)
    ys = np.concatenate([cy_i.astype(np.float32), sat_ys])
    xs = np.concatenate([cx_i.astype(np.float32), sat_xs])
    pks = np.concatenate([resid[cy_i, cx_i].astype(np.float32), sat_pk])
    sat = np.concatenate([np.zeros(len(cy_i), bool), np.ones(len(sat_ys), bool)])
    if len(ys) == 0:
        return np.zeros(0, dtype=STAR_DTYPE)

    # ---- brightest-first overlap suppression ------------------------------
    ys, xs, pks, sat = _suppress_overlaps(ys, xs, pks, sat, H, W, radius)

    # ---- centroid refinement ---------------------------------------------
    n = len(ys)
    fy = np.empty(n, np.float32); fx = np.empty(n, np.float32)
    for i in range(n):
        iy = int(round(float(ys[i]))); ix = int(round(float(xs[i])))
        hfr0 = _quick_hfr(resid_meas, iy, ix)
        yy, xx = _refine_centroid(resid_pos, ys[i], xs[i], hfr0)
        fy[i], fx[i] = yy, xx

    # ---- post-centroid dedup (merged flat-top ties), keep brighter --------
    order = np.lexsort((fx, fy, -pks))
    occ = np.zeros((H, W), dtype=bool)
    d3y, d3x = _disk_offsets(1.5)
    keep = []
    for i in order:
        iy = min(max(int(round(float(fy[i]))), 0), H - 1)
        ix = min(max(int(round(float(fx[i]))), 0), W - 1)
        if occ[iy, ix]:
            continue
        keep.append(i)
        occ[np.clip(iy + d3y, 0, H - 1), np.clip(ix + d3x, 0, W - 1)] = True
    keep = np.array(keep, dtype=np.int64)
    fy, fx, pks, sat = fy[keep], fx[keep], pks[keep], sat[keep]

    # ---- crowding: cap measurement radius by nearest significant neighbor -
    nstars = len(fy)
    r_meas = np.full(nstars, r_hfr, np.float32)
    if nstars > 1:
        from scipy.spatial import cKDTree
        pts_arr = np.stack([fy, fx], axis=1).astype(np.float64)
        tree = cKDTree(pts_arr)
        kq = min(nstars, 8)
        dists, idxs = tree.query(pts_arr, k=kq)
        dists = np.atleast_2d(dists); idxs = np.atleast_2d(idxs)
        for i in range(nstars):
            for j in range(1, kq):
                jj = int(idxs[i, j])
                if pks[jj] >= 0.3 * pks[i]:
                    r_meas[i] = min(r_hfr, max(3.0, 0.6 * float(dists[i, j])))
                    break

    # ---- HFR, flux, FWHM, in/out point-source test ------------------------
    out = []
    ratios = []
    for i in range(nstars):
        cyf, cxf = float(fy[i]), float(fx[i])
        iy = min(max(int(round(cyf)), 0), H - 1)
        ix = min(max(int(round(cxf)), 0), W - 1)
        rm = float(r_meas[i])
        v, dy, dx, _, _ = _window_sum(resid_meas, iy, ix, int(np.ceil(rm)))
        d = np.sqrt((dy + (iy - cyf)) ** 2 + (dx + (ix - cxf)) ** 2)
        sel = d <= rm
        mass = float(v[sel].sum())
        if mass <= 0:
            continue
        hfr = float((v[sel] * d[sel]).sum() / mass)
        hfr = max(hfr, 0.5)
        # FWHM from the second radial moment (2-D Gaussian equivalent)
        m2 = float((v[sel] * d[sel] ** 2).sum() / mass)
        fwhm = 2.3548 * np.sqrt(max(m2, 1e-6) / 2.0)

        # in/out flux ratio in a window big enough for 2.5*hfr
        rout = 2.5 * hfr
        v2, dy2, dx2, _, _ = _window_sum(resid_meas, iy, ix, int(np.ceil(rout)))
        d2 = np.sqrt((dy2 + (iy - cyf)) ** 2 + (dx2 + (ix - cxf)) ** 2)
        inner = d2 <= hfr
        outer = (d2 > hfr) & (d2 <= rout)
        im_, ip_ = float(v2[inner].sum()), int(inner.sum())
        op_ = int(outer.sum())
        # robust outer mass: neighbor stars in the annulus cannot inflate it
        om_ = float(np.median(v2[outer]) * op_) if op_ > 0 else 0.0
        is_pt = (im_ * op_) > (star_in_out * om_ * ip_)
        ratio = (im_ * op_) / (om_ * ip_) if om_ * ip_ > 0 else np.inf

        out.append((cxf, cyf, float(pks[i]), mass, hfr, float(fwhm),
                    bool(is_pt), bool(sat[i]), False))
        ratios.append(ratio)

    stars = np.array(out, dtype=STAR_DTYPE)
    if len(stars) == 0:
        return stars
    ratios = np.array(ratios, dtype=np.float64)

    # ---- FWHM window veto (ABIRL): wide = suspected extended source --------
    ref = stars['is_point'] & ~stars['saturated']
    if ref.sum() >= min_veto_stars:
        med_fwhm = float(np.median(stars['fwhm'][ref]))
        exempt = (ratios >= inout_exempt) & (stars['peak_dn'] >= veto_bright_dn)
        wide = stars['is_point'] & ~stars['saturated'] & \
               (stars['fwhm'] > fwhm_veto * med_fwhm) & ~exempt
        stars['is_point'][wide] = False
    stars['extended_suspect'] = ~stars['is_point']

    order = np.lexsort((stars['x'], stars['y'], -stars['peak_dn']))
    return stars[order]


# ---------------------------------------------------------------- CLI test

def load_tile(npix, order=4):
    from PIL import Image
    p = f"{RAW}/Norder{order}/Dir0/Npix{npix}.webp"
    return np.asarray(Image.open(p).convert("RGB")).astype(np.float32)


def render_overlay(rgb, stars, path, scale=2):
    from PIL import Image, ImageDraw
    beta = 30.0
    disp = np.arcsinh(rgb / beta) / np.arcsinh(255.0 / beta) * 255.0
    im = Image.fromarray(np.clip(disp, 0, 255).astype(np.uint8))
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    for s in stars:
        r = max(2.5 * s['hfr'], 2.0) * scale
        x, y = s['x'] * scale, s['y'] * scale
        col = (0, 255, 0) if s['is_point'] else (255, 60, 60)
        dr.ellipse([x - r, y - r, x + r, y + r], outline=col, width=1)
        if s['saturated']:
            dr.line([x - 2, y, x + 2, y], fill=(0, 200, 255), width=1)
            dr.line([x, y - 2, x, y + 2], fill=(0, 200, 255), width=1)
    im.save(path)


if __name__ == "__main__":
    import sys
    os.makedirs(os.path.join(PEQ, "diag8"), exist_ok=True)
    for arg in sys.argv[1:]:
        npix = int(arg)
        rgb = load_tile(npix)
        stars = detect_stars(rgb)
        npt = int(stars['is_point'].sum())
        nex = int(stars['extended_suspect'].sum())
        nst = int(stars['saturated'].sum())
        med_fwhm = float(np.median(stars['fwhm'][stars['is_point']])) \
            if npt else float('nan')
        med_hfr = float(np.median(stars['hfr'][stars['is_point']])) \
            if npt else float('nan')
        out = os.path.join(PEQ, "diag8", f"stars_{npix}.png")
        render_overlay(rgb, stars, out)
        print(f"Npix{npix}: total={len(stars)} is_point={npt} "
              f"extended_suspect={nex} saturated={nst} "
              f"median_fwhm={med_fwhm:.2f} median_hfr={med_hfr:.2f} -> {out}")
