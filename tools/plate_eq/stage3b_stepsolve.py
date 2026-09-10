"""Stage 3 (A): global boundary-STEP solve, apply only the 10-40deg band.

Signal = the DC step across each plate boundary (real structure is continuous
across a boundary -> ~0; only plate DC offset shows). This avoids the level
conflation that made the per-plate-level version fabricate blocks in the band.

  1. nside-512 L from dss-clean
  2. per adjacent comb-region pair: robust banded step (depth 1-3 each side)
  3. global least-squares o : o_i - o_j = -step_ij  (gauge: median 0)
  4. apply only o_band = o_map - smooth(o_map, 40deg)  (10-40deg block, no >40 drift)
Diagnostic: prints |step| distribution FIRST. If tiny -> blocks are real/content
-level (go to plan B). Preview only (no tile writes).
"""
import os, sys, numpy as np, cv2, healpy as hp
import healpy.projector as hpproj
import scipy.sparse as sp, scipy.sparse.linalg as spl
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
NS = 512; NPIX = hp.nside2npix(NS)
REFHP = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
CAP = 6.0
SRC = "apps/skydata/surveys/dss-clean"

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()

Lcache = SC + "/L512_clean.npy"
if os.path.exists(Lcache):
    L = np.load(Lcache)
else:
    print("building nside-512 L from dss-clean...", flush=True)
    L = np.full(NPIX, np.nan, np.float32)
    for npix in range(3072):
        im = cv2.imread(f"{SRC}/Norder4/Dir0/Npix{npix}.webp")
        if im is None: continue
        l = cv2.resize(0.299 * im[:, :, 2] + 0.587 * im[:, :, 1] + 0.114 * im[:, :, 0],
                       (32, 32), interpolation=cv2.INTER_AREA)
        L[npix * 1024 + cellsub] = l.ravel()
    np.save(Lcache, L)
print("L ready", flush=True)

sh = np.load(SC + "/dc4_sharp.npz"); BMAX = int(sh['bmax'])
wr = np.load(SC + "/winner_red.npz", allow_pickle=True)['winner'].astype(np.int64)
wb = np.load(SC + "/winner_blue.npz", allow_pickle=True)['winner'].astype(np.int64)
comb = wr * BMAX + (wb + 1)
ar = np.arange(NPIX)
nb = hp.get_all_neighbours(NS, ar, nest=True)   # (8,NPIX)

# ---- boundary depth (dist-to-nearest-different-region, in HEALPix hops) ----
print("BFS depth...", flush=True)
depth = np.full(NPIX, 127, np.int8); cause = np.full(NPIX, -1, np.int64)
for k in range(8):
    q = nb[k]; idx = np.where(q >= 0)[0]
    d = idx[comb[q[idx]] != comb[idx]]
    cause[d] = comb[q[d]]; depth[d] = 0
frontier = np.where(depth == 0)[0]
for dc in range(1, 4):
    qs = nb[:, frontier].ravel(); src = np.tile(frontier, 8)
    ok = qs >= 0; qs = qs[ok]; src = src[ok]
    ok = (depth[qs] > dc) & (comb[qs] == comb[src]); qs = qs[ok]; src = src[ok]
    depth[qs] = dc; cause[qs] = cause[src]; frontier = np.unique(qs)

# ---- per (region,cause) banded step: median L(region side, depth1-3) - reference across seam ----
regs = np.unique(comb); NR = len(regs); rid = np.searchsorted(regs, comb)
ib = (depth <= 3) & (cause >= 0) & np.isfinite(L)
sel = np.where(ib)[0]
cidx = np.searchsorted(regs, cause[sel])
key = rid[sel].astype(np.int64) * NR + cidx
vals = L[sel]
order = np.lexsort((vals, key)); ks = key[order]; vs = vals[order]
starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]]); counts = np.diff(np.r_[starts, len(ks)])
med = vs[starts + counts // 2]; ukey = ks[starts]
side = {}  # (i,j)->(median, count)
for kk, m, c in zip(ukey, med, counts):
    i = int(kk // NR); j = int(kk % NR); side[(i, j)] = (m, c)
I = []; J = []; S = []; Wt = []
for (i, j), (mi, ci) in side.items():
    if i < j and (j, i) in side:
        mj, cj = side[(j, i)]
        if ci < 20 or cj < 20: continue
        I.append(i); J.append(j); S.append(mi - mj); Wt.append(min(ci, cj, 400) ** 0.5)
I = np.array(I); J = np.array(J); S = np.array(S, float); Wt = np.array(Wt)
aS = np.abs(S)
print("=== boundary-step distribution on dss-clean (%d pairs) ===" % len(I), flush=True)
print("  |step| p50 %.2f  p90 %.2f  p95 %.2f  p99 %.2f  max %.2f DN"
      % (np.percentile(aS, 50), np.percentile(aS, 90), np.percentile(aS, 95),
         np.percentile(aS, 99), aS.max()), flush=True)
if np.percentile(aS, 95) < 1.0:
    print(">>> steps are tiny: residual blocks are REAL structure / content-level -> plan B", flush=True)

# ---- global least-squares solve o: o_i - o_j = -step, Huber IRLS ----
print("global solve...", flush=True)
w = Wt.copy(); o = np.zeros(NR)
for it in range(5):
    diag = np.full(NR, 1e-3)
    np.add.at(diag, I, w); np.add.at(diag, J, w)
    off = sp.coo_matrix((-w, (I, J)), shape=(NR, NR))
    A = sp.diags(diag) + off + off.T
    b = np.zeros(NR); np.add.at(b, I, -w * S); np.add.at(b, J, w * S)
    o, info = spl.cg(A.tocsr(), b, rtol=1e-7, maxiter=4000, M=sp.diags(1.0 / diag))
    o -= np.median(o)
    r = o[I] - o[J] + S
    scv = 1.345 * max(1.4826 * np.median(np.abs(r)), 0.3)
    w = Wt * np.minimum(1.0, scv / np.maximum(np.abs(r), 1e-6))
o_map = o[rid].astype(np.float32)
# bandpass: keep 10-40 deg (remove >40 deg drift)
o_band = o_map - hp.reorder(hp.smoothing(hp.reorder(o_map, n2r=True), fwhm=np.radians(REFHP)), r2n=True)
o_band = np.clip(o_band, -CAP, CAP)
print("global o: full |p95| %.2f max %.2f | banded(10-40) |p95| %.2f max %.2f"
      % (np.percentile(np.abs(o_map), 95), np.abs(o_map).max(),
         np.percentile(np.abs(o_band), 95), np.abs(o_band).max()), flush=True)
np.save(SC + "/stage3b_oband.npy", o_band)

# ---- coarse preview ----
Lafter = L + o_band
os.makedirs(SC + "/diag8", exist_ok=True)
for nm, ra, dec, span in [("crux", 187, -60, 42), ("sgr", 270, -28, 38)]:
    proj = hpproj.GnomonicProj(rot=(ra, dec, 0), xsize=760, ysize=420, reso=span * 60 / 760)
    v2p = lambda x, y, z: hp.vec2pix(NS, x, y, z, nest=True)
    mb = np.array(proj.projmap(L, v2p)); ma = np.array(proj.projmap(Lafter, v2p))
    lo, hi = np.nanpercentile(mb, [8, 92])
    def sh_(m): return (np.clip((m - lo) / (hi - lo), 0, 1)[::-1] * 255).astype(np.uint8)
    corrp = np.array(proj.projmap(o_band, v2p))
    cc = (np.clip((corrp + CAP) / (2 * CAP), 0, 1)[::-1] * 255).astype(np.uint8)
    b = sh_(mb); a = sh_(ma)
    cv2.putText(b, "before", (6, 20), 0, 0.6, 255, 2)
    cv2.putText(a, "after step-band40", (6, 20), 0, 0.6, 255, 2)
    cv2.putText(cc, "correction", (6, 20), 0, 0.6, 0, 2)
    cv2.imwrite(SC + f"/diag8/stage3b_{nm}.png",
                np.hstack([b, np.full((420, 5), 128, np.uint8), a, np.full((420, 5), 128, np.uint8), cc]))
    print("preview", nm, flush=True)
print("DONE")
