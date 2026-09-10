"""Stage 3: regional (~40 deg stepped) plate-block leveling on dss-clean.

Removes the 10-40 deg accumulated plate-band offsets that tile-local Stage 2
(per-tile anchoring) can't propagate away, WITHOUT flattening real >40 deg
structure (galactic-band brightness profile, Coalsack). Per-plate-region sky
level is compared to its own REF-deg smoothed neighbourhood; only the deviation
from that ~40 deg context is corrected. No dark-sky eligibility gate -> the
galactic band is included (each bright plate is judged against its bright
neighbours, so real band brightness is preserved).

Outputs stage3_offset.npz (per-comb-region L offset) + coarse before/after PNGs.
"""
import os, sys, numpy as np, cv2, healpy as hp
import healpy.projector as hpproj
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
NS = 512; NPIX = hp.nside2npix(NS)
REF = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0     # neighbourhood window (deg)
CAP = 6.0
DARK_PCT = 35.0            # per-region sky-level percentile (avoid bright nebula cores)
SRC = "apps/skydata/surveys/dss-clean"

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()

# ---- build nside-512 luminance from dss-clean order-4 tiles (32x32 each) ----
print("building nside-512 L from dss-clean...", flush=True)
L = np.full(NPIX, np.nan, np.float32)
for npix in range(3072):
    f = f"{SRC}/Norder4/Dir0/Npix{npix}.webp"
    im = cv2.imread(f)
    if im is None:
        continue
    l = cv2.resize(0.299 * im[:, :, 2] + 0.587 * im[:, :, 1] + 0.114 * im[:, :, 0],
                   (32, 32), interpolation=cv2.INTER_AREA)
    L[npix * 1024 + cellsub] = l.ravel()
print("L filled %.1f%%" % (100 * np.isfinite(L).mean()), flush=True)

# ---- plate-region ids (coarse winner is fine for per-region DC) ----
sh = np.load(SC + "/dc4_sharp.npz"); BMAX = int(sh['bmax'])
wr = np.load(SC + "/winner_red.npz", allow_pickle=True)['winner'].astype(np.int64)
wb = np.load(SC + "/winner_blue.npz", allow_pickle=True)['winner'].astype(np.int64)
comb = wr * BMAX + (wb + 1)

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

# ---- per-region sky level (DARK_PCT percentile) ----
u, inv = np.unique(comb, return_inverse=True); inv = inv.reshape(-1)
order = np.argsort(inv, kind='stable'); starts = np.unique(inv[order], return_index=True)[1]
Lo = L[order]; NL = len(u)
level = np.full(NL, np.nan); size = np.zeros(NL)
for k, seg in enumerate(np.split(Lo, starts[1:])):
    seg = seg[np.isfinite(seg)]
    size[k] = len(seg)
    if len(seg) >= 12:
        level[k] = np.percentile(seg, DARK_PCT)
ok = np.isfinite(level) & (size >= 12)
# ---- REF-deg neighbourhood reference of the region-level field ----
lvl_map = np.where(np.isfinite(level[inv]) & ok[inv], level[inv], 0.0)
wgt = np.where(ok[inv], 1.0, 0.0)
ns = smooth(lvl_map, REF); ds = smooth(wgt, REF)
ref_map = np.where(ds > 0.05, ns / np.maximum(ds, 0.05), np.nan)
ref = np.array([np.nanmean(seg) for seg in np.split(ref_map[order], starts[1:])])
# ---- per-region offset = pull level toward its REF-deg context ----
dev = level - ref
off = np.where(ok & np.isfinite(dev), -np.clip(dev, -CAP, CAP), 0.0)
# gentle: don't touch regions already within 0.6 DN of their context
off[np.abs(dev) < 0.6] = 0.0
act = np.abs(off) > 0.3
print("REF %.0f deg: regions %d active %d | |off| p95 %.2f max %.2f"
      % (REF, NL, int(act.sum()), np.percentile(np.abs(off[act]), 95) if act.any() else 0,
         np.abs(off).max()), flush=True)
np.savez(SC + "/stage3_offset.npz", region_ids=u, offset=off.astype(np.float32), bmax=BMAX, ref=REF)

# ---- coarse before/after preview for the two user regions ----
off_map = off[inv].astype(np.float32)
Lafter = L + off_map
os.makedirs(SC + "/diag8", exist_ok=True)
for nm, ra, dec, span in [("crux", 187, -60, 42), ("sgr", 270, -28, 38)]:
    proj = hpproj.GnomonicProj(rot=(ra, dec, 0), xsize=760, ysize=420, reso=span * 60 / 760)
    v2p = lambda x, y, z: hp.vec2pix(NS, x, y, z, nest=True)
    mb = np.array(proj.projmap(L, v2p)); ma = np.array(proj.projmap(Lafter, v2p))
    lo, hi = np.nanpercentile(mb, [8, 92])
    def sh_(m): return (np.clip((m - lo) / (hi - lo), 0, 1)[::-1] * 255).astype(np.uint8)
    b = sh_(mb); a = sh_(ma)
    cv2.putText(b, "before", (6, 20), 0, 0.6, 255, 2); cv2.putText(a, "after ref%.0f" % REF, (6, 20), 0, 0.6, 255, 2)
    cv2.imwrite(SC + f"/diag8/stage3_{nm}.png", np.hstack([b, np.full((420, 5), 128, np.uint8), a]))
    print("preview", nm, flush=True)
print("DONE")
