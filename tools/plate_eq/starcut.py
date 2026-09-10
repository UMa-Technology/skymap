"""Star stamp harvester: builds a training-material library of real DSS star
cutouts (additive star layer + soft alpha mask) for the starless-DSS
synthetic-training-pair generator (starless_design.md Stage 1).

Pipeline:
  1. Stratify the order-4 sky by galactic latitude (star density proxy):
        30 quiet  tiles  |b| > 30
        30 medium tiles  10 < |b| <= 30
        20 dense  tiles  |b| <= 10
     (deterministic: seeded rng choice over healpy nest pixels)
  2. Per tile: detect_stars(); harvest is_point, non-saturated stars with
     peak_dn >= 12 that lie > 32 px from every tile edge.  Per tile at most
     PER_TILE_CAP stamps, chosen evenly over the peak-sorted list so the
     brightness range is spanned (keeps dense tiles from dominating).
  3. Stamp side = clamp(ceil(6*hfr), 12, 64) -> next size bucket of
     (12,16,24,32,48,64).  Per-channel local annulus median background
     (annulus 2.5*hfr..3.5*hfr around the centroid, measured on the tile)
     is subtracted so the stamp is the ADDITIVE star layer; negatives
     clipped to 0.  Soft alpha mask = gaussian(sigma=1) of the stamp
     luminance, normalized to [0,1].
  4. Saturated stars (flat cores / spikes) harvested separately: 40 stamps
     spanning the size range (sat_stamps_* arrays).  Saturated candidates are
     taken from DENSE (|b|<=10) tiles only: saturating galaxy cores and
     Magellanic star-clouds live off-plane (verified: an all-sky harvest
     picked up LMC-edge / SMC-wing objects at b=-28/-46), while a local
     halo-decay test cannot separate them because the 32px-cell background
     absorbs any smooth extended envelope.

Output: starcut_lib.npz with, per non-empty bucket <s>:
     stamps_<s> (N,s,s,3) f16 | masks_<s> (N,s,s) f16 | meta_<s> (N,4) f32
     meta columns: peak_dn, hfr, fwhm, saturated(0/1)
     src_<s> (N,3) f32: source npix, x, y (provenance / dedup / QA)
     plus sat_stamps_<s>/sat_masks_<s>/sat_meta_<s>/sat_src_<s> for the
     saturated set.
Also renders a contact sheet diag8/starcut_sheet.png (~200 random stamps,
asinh stretch) and prints a per-bucket summary table.

Deterministic end to end (fixed rng seeds for tile choice + sheet sampling).
"""
import os
import numpy as np
import healpy as hp
from PIL import Image
from scipy.ndimage import gaussian_filter

from star_detect import detect_stars, load_tile, luminance, PEQ

ORDER = 4
NSIDE = 1 << ORDER            # 16
NPIX = 12 * NSIDE * NSIDE     # 3072
TW = 512
EDGE = 32                     # stay >32 px away from tile edges
MIN_PEAK = 12.0               # DN above local background
BUCKETS = (12, 16, 24, 32, 48, 64)
PER_TILE_CAP = 400
N_SAT = 40
LIB_PATH = os.path.join(PEQ, "starcut_lib.npz")
SHEET_PATH = os.path.join(PEQ, "diag8", "starcut_sheet.png")


# ------------------------------------------------------------- tile choice

def galactic_b_all():
    """Galactic latitude b (deg) of every order-4 tile center (nest)."""
    lon, lat = hp.pix2ang(NSIDE, np.arange(NPIX), nest=True, lonlat=True)
    vec = np.asarray(hp.ang2vec(lon, lat, lonlat=True)).T      # (3,N)
    rot = hp.Rotator(coord=['C', 'G'])                          # equ -> gal
    vg = rot(vec)
    return np.degrees(np.arcsin(np.clip(vg[2], -1, 1)))


def stratified_tiles(n_quiet=30, n_medium=30, n_dense=20, seed=42):
    b = galactic_b_all()
    ab = np.abs(b)
    strata = {
        'quiet':  np.where(ab > 30)[0],
        'medium': np.where((ab > 10) & (ab <= 30))[0],
        'dense':  np.where(ab <= 10)[0],
    }
    counts = {'quiet': n_quiet, 'medium': n_medium, 'dense': n_dense}
    rng = np.random.default_rng(seed)
    picked = {}
    for name, pool in strata.items():
        k = min(counts[name], len(pool))
        picked[name] = np.sort(rng.choice(pool, size=k, replace=False))
    return picked, b


# ------------------------------------------------------------- harvesting

def bucket_of(side):
    for s in BUCKETS:
        if side <= s:
            return s
    return BUCKETS[-1]


def annulus_bg(rgb, cx, cy, hfr):
    """Per-channel median of the annulus 2.5*hfr..3.5*hfr around (cx,cy)."""
    r_in = max(2.5 * hfr, 2.0)
    r_out = max(3.5 * hfr, r_in + 1.5)
    rad = int(np.ceil(r_out))
    iy, ix = int(round(cy)), int(round(cx))
    y0, y1 = max(iy - rad, 0), min(iy + rad + 1, rgb.shape[0])
    x0, x1 = max(ix - rad, 0), min(ix + rad + 1, rgb.shape[1])
    yy = np.arange(y0, y1, dtype=np.float32)[:, None] - cy
    xx = np.arange(x0, x1, dtype=np.float32)[None, :] - cx
    d = np.sqrt(yy * yy + xx * xx)
    sel = (d > r_in) & (d <= r_out)
    if sel.sum() < 8:                       # degenerate: widen once
        sel = (d > r_in) & (d <= r_out + 2.0)
    win = rgb[y0:y1, x0:x1]
    return np.median(win[sel], axis=0)      # (3,)


def cut_stamp(rgb, star):
    """Extract additive-layer stamp + soft alpha mask for one star.
    Returns (bucket, stamp f16 (s,s,3), mask f16 (s,s)) or None."""
    hfr = float(star['hfr'])
    side = int(np.ceil(6.0 * hfr))
    side = min(max(side, 12), 64)
    s = bucket_of(side)
    cx, cy = float(star['x']), float(star['y'])
    icx, icy = int(round(cx)), int(round(cy))
    h = s // 2
    y0, x0 = icy - h, icx - h
    if y0 < 0 or x0 < 0 or y0 + s > rgb.shape[0] or x0 + s > rgb.shape[1]:
        return None
    bg = annulus_bg(rgb, cx, cy, hfr)
    stamp = np.clip(rgb[y0:y0 + s, x0:x0 + s] - bg[None, None, :], 0, None)
    lum = 0.299 * stamp[..., 0] + 0.587 * stamp[..., 1] + 0.114 * stamp[..., 2]
    mask = gaussian_filter(lum.astype(np.float32), 1.0)
    mx = float(mask.max())
    if mx > 0:
        mask = mask / mx
    return s, stamp.astype(np.float16), np.clip(mask, 0, 1).astype(np.float16)


def spread_indices(order_desc, cap):
    """Evenly spaced indices over a sorted list (deterministic subsample)."""
    n = len(order_desc)
    if n <= cap:
        return order_desc
    pick = np.unique(np.round(np.linspace(0, n - 1, cap)).astype(int))
    return order_desc[pick]


def harvest():
    os.makedirs(os.path.join(PEQ, "diag8"), exist_ok=True)
    picked, b = stratified_tiles()

    lib = {s: {'stamps': [], 'masks': [], 'meta': [], 'src': []}
           for s in BUCKETS}
    sat_pool = []                       # (flux, npix, star, stamp, mask, s)
    tile_rows = []

    for stratum in ('quiet', 'medium', 'dense'):
        for npix in picked[stratum]:
            rgb = load_tile(int(npix), order=ORDER)
            stars = detect_stars(rgb)
            inside = ((stars['x'] > EDGE) & (stars['x'] < TW - EDGE) &
                      (stars['y'] > EDGE) & (stars['y'] < TW - EDGE))
            good = stars[inside & stars['is_point'] & ~stars['saturated'] &
                         (stars['peak_dn'] >= MIN_PEAK)]
            order_desc = np.argsort(-good['peak_dn'], kind='stable')
            take = spread_indices(order_desc, PER_TILE_CAP)
            n_cut = 0
            for i in take:
                res = cut_stamp(rgb, good[i])
                if res is None:
                    continue
                s, stamp, mask = res
                lib[s]['stamps'].append(stamp)
                lib[s]['masks'].append(mask)
                lib[s]['meta'].append((good[i]['peak_dn'], good[i]['hfr'],
                                       good[i]['fwhm'], 0.0))
                lib[s]['src'].append((npix, good[i]['x'], good[i]['y']))
                n_cut += 1
            # saturated star candidates (kept separately; dense tiles only —
            # no saturating galaxies / Magellanic clouds in the plane)
            satsel = stars[inside & stars['is_point'] & stars['saturated']] \
                if stratum == 'dense' else stars[:0]
            for st in satsel:
                res = cut_stamp(rgb, st)
                if res is None:
                    continue
                s, stamp, mask = res
                sat_pool.append((float(st['flux']), int(npix), st, stamp,
                                 mask, s))
            tile_rows.append((stratum, int(npix), float(b[npix]), len(good),
                              n_cut, len(satsel)))
            print(f"  [{stratum:6s}] Npix{int(npix):4d} b={b[npix]:+6.1f}  "
                  f"harvestable={len(good):4d} cut={n_cut:4d} sat={len(satsel)}")

    # ---- pick N_SAT saturated stamps spanning the flux range ----------------
    sat_pool.sort(key=lambda t: (-t[0], t[1]))          # flux desc, tile asc
    if len(sat_pool) > N_SAT:
        idx = np.unique(np.round(np.linspace(0, len(sat_pool) - 1,
                                             N_SAT)).astype(int))
        sat_pool = [sat_pool[i] for i in idx]
    sat_lib = {s: {'stamps': [], 'masks': [], 'meta': [], 'src': []}
               for s in BUCKETS}
    for flux, npix, st, stamp, mask, s in sat_pool:
        sat_lib[s]['stamps'].append(stamp)
        sat_lib[s]['masks'].append(mask)
        sat_lib[s]['meta'].append((st['peak_dn'], st['hfr'], st['fwhm'], 1.0))
        sat_lib[s]['src'].append((npix, st['x'], st['y']))

    # ---- save ---------------------------------------------------------------
    payload = {}
    for s in BUCKETS:
        if lib[s]['stamps']:
            payload[f'stamps_{s}'] = np.stack(lib[s]['stamps'])
            payload[f'masks_{s}'] = np.stack(lib[s]['masks'])
            payload[f'meta_{s}'] = np.array(lib[s]['meta'], np.float32)
            payload[f'src_{s}'] = np.array(lib[s]['src'], np.float32)
        if sat_lib[s]['stamps']:
            payload[f'sat_stamps_{s}'] = np.stack(sat_lib[s]['stamps'])
            payload[f'sat_masks_{s}'] = np.stack(sat_lib[s]['masks'])
            payload[f'sat_meta_{s}'] = np.array(sat_lib[s]['meta'], np.float32)
            payload[f'sat_src_{s}'] = np.array(sat_lib[s]['src'], np.float32)
    np.savez_compressed(LIB_PATH, **payload)

    # ---- summary table -------------------------------------------------------
    total = 0
    print("\nbucket |     n | peak p10/p50/p90 |  hfr p50")
    print("-------+-------+------------------+---------")
    for s in BUCKETS:
        if not lib[s]['stamps']:
            continue
        meta = np.array(lib[s]['meta'], np.float32)
        n = len(meta); total += n
        p = np.percentile(meta[:, 0], [10, 50, 90])
        print(f"  {s:4d} | {n:5d} | {p[0]:5.1f}/{p[1]:5.1f}/{p[2]:5.1f} "
              f"| {np.median(meta[:,1]):7.2f}")
    nsat = sum(len(v['stamps']) for v in sat_lib.values())
    print(f"total regular stamps: {total}   saturated stamps: {nsat}")
    sz = os.path.getsize(LIB_PATH) / 1e6
    print(f"library: {LIB_PATH} ({sz:.1f} MB)")

    render_sheet(lib, sat_lib)
    return lib, sat_lib


# ------------------------------------------------------------- contact sheet

def render_sheet(lib, sat_lib, n_show=200, cols=20, cell=64, seed=7):
    pool = []
    for s in BUCKETS:
        for st in lib[s]['stamps']:
            pool.append(st)
    rng = np.random.default_rng(seed)
    if len(pool) > n_show - len_sat(sat_lib):
        idx = rng.choice(len(pool), size=n_show - len_sat(sat_lib),
                         replace=False)
        pool = [pool[i] for i in sorted(idx)]
    # append all saturated stamps at the end (flat cores / spikes)
    for s in BUCKETS:
        pool.extend(sat_lib[s]['stamps'])

    rows = (len(pool) + cols - 1) // cols
    sheet = np.zeros((rows * cell, cols * cell, 3), np.uint8)
    for k, st in enumerate(pool):
        a = st.astype(np.float32)
        vmax = max(float(a.max()), 1.0)
        disp = np.arcsinh(a / 5.0) / np.arcsinh(vmax / 5.0)
        disp = np.clip(disp * 255, 0, 255).astype(np.uint8)
        im = Image.fromarray(disp).resize((cell - 2, cell - 2), Image.NEAREST)
        r, c = divmod(k, cols)
        sheet[r * cell + 1:(r + 1) * cell - 1,
              c * cell + 1:(c + 1) * cell - 1] = np.asarray(im)
    Image.fromarray(sheet).save(SHEET_PATH)
    print(f"contact sheet ({len(pool)} stamps): {SHEET_PATH}")


def len_sat(sat_lib):
    return sum(len(v['stamps']) for v in sat_lib.values())


if __name__ == "__main__":
    harvest()
