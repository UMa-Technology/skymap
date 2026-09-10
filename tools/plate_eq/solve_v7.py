"""v7: (a) in-plate EDGE-BAND flattening + (b) seam-step GRAPH leveling.

Motivation (user round 7): residual artifacts fall into two classes the v4/v6
absolute-reference estimator cannot touch:
  - thin sliver regions + steps inside the galactic band (eligibility gate
    darkmed<16 excluded the whole Milky Way -> Crux strips never leveled;
    Regor bright plate block),
  - in-plate EDGE BANDS hugging the boundary (t1252/t1219, +/-1.5-2.5 DN,
    0.3-1 deg wide) which no per-region constant can fix.

Method:
  1. dev fields per channel (star-suppressed, 3-deg highpass).
  2. Global BFS from all region boundaries: hop depth + "cause" (nearest other
     label). Group (region, cause, depth) medians.
  3. v7b: per (region,cause) edge profile P(d) from dev, deep-anchored to 0,
     gated on significance + low texture + off halo discs. Correction field
     dband7_{R,G,B} (nside512 smooth chain terms).
  4. v7a: on the band-corrected state, per-seam step from depth-1..3 banded
     medians of the RAW state (real sky is continuous across plate boundaries,
     so seam steps are artifacts by definition -> no dark-sky gate needed).
     Damped weighted graph LSQ per tessellation:
       L on combined regions -> dc7_sharp.npz
       R on red mosaic, B on blue/GAP mosaic -> dc7_chroma.npz
     Huber-reweighted 3x, area-scaled damping, caps.
"""
import os, sys, numpy as np, healpy as hp
import scipy.sparse as sp
import scipy.sparse.linalg as spl
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from seamnet_common import load_state, load_labels
NS = 512; NPIX = hp.nside2npix(NS)

DMAX_BAND = 12   # BFS depth for edge bands (12 px ~ 1.4 deg)
DTAPER = 8       # profile tapered to 0 by this depth
BAND_CAP = 4.0
STEP_CAP_L = 8.0
STEP_CAP_C = 4.0

# ---------------- current state ----------------
R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh4 = np.load(SC + "/dc4_sharp.npz")
U0 = sh4['region_ids']; CREG = sh4['c_reg']; BMAX = int(sh4['bmax'])
sh6 = np.load(SC + "/dc6_sharp.npz"); U6 = sh6['region_ids']; C6 = sh6['c_reg']
resid6 = np.load(SC + "/dDark6_resid.npy")
c5 = np.load(SC + "/dc5_chroma.npz"); c6 = np.load(SC + "/dc6_chroma.npz")
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
labr, labb_eff = load_labels()

def lut(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

cl = lut(U0, CREG, comb) + lut(U6, C6, comb)
pR = lut(c5['uR'], c5['cR'], labr) + lut(c6['uR'], c6['cR'], labr)
pB = lut(c5['uB'], c5['cB'], labb_eff) + lut(c6['uB'], c6['cB'], labb_eff)
lum = drest['dR'] + resid4 + cl + resid6
CH = {'R': (R + lum + pR).astype(np.float32),
      'G': (G + lum + 0.5 * (pR + pB)).astype(np.float32),
      'B': (B + lum + pB).astype(np.float32)}
del R, G, B, drest, resid4, resid6, cl, pR, pB, lum

# halo discs excluded from all estimation (radial fills live there)
plans = np.load(SC + "/halo_plan.npy", allow_pickle=True).item()
hexcl = np.zeros(NPIX, bool)
for nm, pl in plans.items():
    pixh = hp.query_disc(NS, hp.ang2vec(pl['ra'], pl['dec'], lonlat=True),
                         np.radians(pl['Rh'] + 0.3), nest=True)
    hexcl[pixh] = True
for ra0, dec0, rr in ((84.0534, -1.2019, 1.5), (85.1897, -1.9426, 1.5),   # Alnilam/Alnitak
                      (122.3832, -47.3366, 2.2)):                          # Regor (to be planned)
    hexcl[hp.query_disc(NS, hp.ang2vec(ra0, dec0, lonlat=True), np.radians(rr), nest=True)] = True
print("halo-excluded pixels: %.2f%%" % (100 * hexcl.mean()), flush=True)

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

def dev_of(vals):
    bgf = vals.astype(np.float64)
    for it in range(2):
        s = smooth(bgf, 1.0)
        r_ = bgf - s
        sig = 1.4826 * np.median(np.abs(r_ - np.median(r_)))
        bgf = np.where(r_ > 2.0 * sig, s, bgf)
    return (bgf - smooth(bgf, 3.0)).astype(np.float32)

print("dev fields...", flush=True)
DEV = {ch: dev_of(CH[ch]) for ch in 'RGB'}

# ---------------- global BFS: depth + cause ----------------
print("BFS depth/cause...", flush=True)
nb = hp.get_all_neighbours(NS, np.arange(NPIX), nest=True)   # (8, NPIX)
depth = np.full(NPIX, 127, np.int8)
cause = np.full(NPIX, -1, np.int64)
for k in range(8):
    q = nb[k]
    idx = np.where(q >= 0)[0]
    d = idx[comb[q[idx]] != comb[idx]]
    cause[d] = comb[q[d]]
    depth[d] = 0
frontier = np.where(depth == 0)[0]
for dc in range(1, DMAX_BAND + 1):
    qs = nb[:, frontier].ravel()
    src = np.tile(frontier, 8)
    ok = qs >= 0
    qs = qs[ok]; src = src[ok]
    ok = (depth[qs] > dc) & (comb[qs] == comb[src])
    qs = qs[ok]; src = src[ok]
    depth[qs] = dc
    cause[qs] = cause[src]
    frontier = np.unique(qs)
    if len(frontier) == 0: break
inband = (depth <= DMAX_BAND) & (cause >= 0)
print("  pixels within %d hops of a seam: %.1f%%" % (DMAX_BAND, 100 * inband.mean()), flush=True)

regs = np.unique(comb); NR = len(regs)
rid = np.searchsorted(regs, comb)
cid = np.full(NPIX, -1, np.int64)
cid[inband] = np.searchsorted(regs, cause[inband])
area = np.bincount(rid, minlength=NR).astype(np.float64)

sel = np.where(inband & ~hexcl)[0]
key = (rid[sel] * NR + cid[sel]) * (DMAX_BAND + 1) + depth[sel]

def seg_stats(vals):
    """per-(region,cause,depth): count, median, q1, q3"""
    order = np.lexsort((vals[sel], key))
    ks = key[order]; vs = vals[sel][order]
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    counts = np.diff(np.r_[starts, len(ks)])
    med = vs[starts + counts // 2]
    q1 = vs[starts + counts // 4]
    q3 = vs[starts + (3 * counts) // 4]
    return ks[starts], counts, med, q1, q3

# ---------------- v7b: edge-band profiles ----------------
print("edge-band profiles...", flush=True)
uk, cnt, medR, q1R, q3R = seg_stats(DEV['R'])
_, _, medG, _, _ = seg_stats(DEV['G'])
_, _, medB, _, _ = seg_stats(DEV['B'])
pairk = uk // (DMAX_BAND + 1)
dep = (uk % (DMAX_BAND + 1)).astype(np.int64)
upair, pinv = np.unique(pairk, return_inverse=True)
pinv = pinv.reshape(-1)
NPair = len(upair)
prof = np.zeros((3, NPair, DMAX_BAND + 1), np.float32)
pcnt = np.zeros((NPair, DMAX_BAND + 1), np.int64)
piqr = np.zeros((NPair, DMAX_BAND + 1), np.float32)
for arr, med in ((0, medR), (1, medG), (2, medB)):
    prof[arr][pinv, dep] = med
pcnt[pinv, dep] = cnt
piqr[pinv, dep] = (q3R - q1R)
# deep anchor: subtract mean of depths 8..12 (require some support there)
deepok = (pcnt[:, 8:] >= 15).sum(1) >= 3
deepm = np.zeros((3, NPair), np.float32)
wdeep = np.where(pcnt[:, 8:] >= 15, pcnt[:, 8:], 0).astype(np.float64)
for ci in range(3):
    with np.errstate(invalid='ignore'):
        deepm[ci] = np.where(deepok, (prof[ci][:, 8:] * wdeep).sum(1) / np.maximum(wdeep.sum(1), 1), 0)
prof -= deepm[:, :, None]
profL = 0.299 * prof[0] + 0.587 * prof[1] + 0.114 * prof[2]
# gates: enough pixels in shallow bands, significant, quiet texture, deep anchored
shal_ok = (pcnt[:, :4] >= 25).sum(1) >= 3
signif = (np.abs(profL[:, :4]) > 0.7).sum(1) >= 2
quiet = np.nanmedian(np.where(pcnt[:, :6] >= 15, piqr[:, :6], np.nan), axis=1) < 6.0
useb = shal_ok & signif & quiet & deepok
print("  band pairs: %d | gated in: %d" % (NPair, int(useb.sum())), flush=True)
# taper and cap
tap = np.clip((DTAPER - np.arange(DMAX_BAND + 1)) / 2.0 + 1.0, 0, 1)  # 1 until d=DTAPER-2, ->0 at DTAPER+2
corr = -np.clip(prof, -BAND_CAP, BAND_CAP) * tap[None, None, :]
corr[:, ~useb, :] = 0.0
# 3-tap smooth along depth
corr = np.concatenate([corr[:, :, :1], corr, corr[:, :, -1:]], axis=2)
corr = (corr[:, :, :-2] + corr[:, :, 1:-1] + corr[:, :, 2:]) / 3.0

dband = {ch: np.zeros(NPIX, np.float32) for ch in 'RGB'}
# map every in-band pixel (incl. halo-excluded? NO - skip there) to its correction
selall = np.where(inband & ~hexcl)[0]
pk = rid[selall] * NR + cid[selall]
ppos = np.searchsorted(upair, pk)
okp = (ppos < NPair) & (upair[np.clip(ppos, 0, NPair - 1)] == pk)
selall = selall[okp]; ppos = ppos[okp]
dp = depth[selall].astype(np.int64)
for ci, ch in enumerate('RGB'):
    dband[ch][selall] = corr[ci][ppos, dp]
    np.save(SC + "/dband7_%s.npy" % ch, dband[ch])
bl = 0.299 * dband['R'] + 0.587 * dband['G'] + 0.114 * dband['B']
print("  dband L: nonzero %.2f%% |p99| %.2f max %.2f" %
      (100 * (np.abs(bl) > 0.05).mean(), np.percentile(np.abs(bl[np.abs(bl) > 0.05]), 99)
       if (np.abs(bl) > 0.05).any() else 0, np.abs(bl).max()), flush=True)

for ch in 'RGB':
    CH[ch] += dband[ch]

# ---------------- v7a: seam-step graph ----------------
def graph_solve(vals, lab, cap, tag):
    """seam-step graph leveling on tessellation `lab` for channel state `vals`."""
    lregs = np.unique(lab); NL = len(lregs)
    lr = np.searchsorted(lregs, lab)
    # boundary depth/cause for THIS tessellation (comb refines labr/labb, so
    # reuse comb BFS only for comb; recompute cheap shallow BFS otherwise)
    dep2 = np.full(NPIX, 127, np.int8)
    cau2 = np.full(NPIX, -1, np.int64)
    for k in range(8):
        q = nb[k]
        ok = q >= 0
        idx = np.where(ok)[0]
        d = idx[lab[q[ok]] != lab[idx]]
        cau2[d] = lab[nb[k][d]]
        dep2[d] = 0
    frontier = np.where(dep2 == 0)[0]
    for dc in range(1, 4):
        qs = nb[:, frontier].ravel(); src = np.tile(frontier, 8)
        ok = qs >= 0
        qs = qs[ok]; src = src[ok]
        ok = (dep2[qs] > dc) & (lab[qs] == lab[src])
        qs = qs[ok]; src = src[ok]
        dep2[qs] = dc; cau2[qs] = cau2[src]
        frontier = np.unique(qs)
    ib = (dep2 <= 3) & (cau2 >= 0) & ~hexcl
    s2 = np.where(ib)[0]
    c2 = np.searchsorted(lregs, cau2[s2])
    k2 = (lr[s2].astype(np.int64) * NL + c2) * 4 + dep2[s2]
    order = np.lexsort((vals[s2], k2))
    ks = k2[order]; vs = vals[s2][order]
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    counts = np.diff(np.r_[starts, len(ks)])
    med = vs[starts + counts // 2]
    ukk = ks[starts]
    pk2 = ukk // 4; dp2 = ukk % 4
    up2, pv2 = np.unique(pk2, return_inverse=True)
    pv2 = pv2.reshape(-1)
    M = np.full((len(up2), 4), np.nan, np.float32)
    C = np.zeros((len(up2), 4), np.int64)
    M[pv2, dp2] = med; C[pv2, dp2] = counts
    # side value at seam: weighted mean of depths 1..3 (skip mixed d0)
    wts = np.array([0.0, 3.0, 2.0, 1.0])
    wm = np.where(C >= 6, wts[None, :], 0.0)
    okrow = wm.sum(1) > 0
    sideval = np.full(len(up2), np.nan, np.float32)
    sideval[okrow] = (np.nan_to_num(M[okrow]) * wm[okrow]).sum(1) / wm[okrow].sum(1)
    sidecnt = C[:, 1]
    i_of = (up2 // NL).astype(np.int64); j_of = (up2 % NL).astype(np.int64)
    # match ordered pairs (i,j) with (j,i)
    fwd = {}
    for t in range(len(up2)):
        if np.isfinite(sideval[t]):
            fwd[(i_of[t], j_of[t])] = t
    ii = []; jj = []; ss = []; ww = []
    for (a, b), t in fwd.items():
        if a < b and (b, a) in fwd:
            t2 = fwd[(b, a)]
            ii.append(a); jj.append(b)
            ss.append(float(sideval[t] - sideval[t2]))
            ww.append(float(min(max(sidecnt[t], 1), max(sidecnt[t2], 1), 400)))
    ii = np.array(ii); jj = np.array(jj); ss = np.array(ss); ww0 = np.array(ww)
    print("%s: regions %d seams %d |step| p50 %.2f p95 %.2f" %
          (tag, NL, len(ii), np.median(np.abs(ss)), np.percentile(np.abs(ss), 95)), flush=True)
    lam = 0.05 * np.sqrt(np.bincount(lr, minlength=NL).astype(np.float64))
    w = ww0.copy()
    for itn in range(4):
        Adiag = lam.copy()
        np.add.at(Adiag, ii, w); np.add.at(Adiag, jj, w)
        Aoff = sp.coo_matrix((-w, (ii, jj)), shape=(NL, NL))
        A = sp.diags(Adiag) + Aoff + Aoff.T
        bvec = np.zeros(NL)
        np.add.at(bvec, ii, -w * ss); np.add.at(bvec, jj, w * ss)
        cvec, info = spl.cg(A.tocsr(), bvec, rtol=1e-8, maxiter=2000,
                            M=sp.diags(1.0 / Adiag))
        if info != 0: print("  cg info", info, flush=True)
        r_ = ss + cvec[ii] - cvec[jj]
        sc = 1.345 * max(1.4826 * np.median(np.abs(r_)), 0.3)
        w = ww0 * np.minimum(1.0, sc / np.maximum(np.abs(r_), 1e-6))
    cvec = np.clip(cvec, -cap, cap)
    act = np.abs(cvec) > 0.3
    print("  active %d |c| p95 %.2f max %.2f | resid seam p95 %.2f (was %.2f)" %
          (int(act.sum()), np.percentile(np.abs(cvec[act]), 95) if act.any() else 0,
           np.abs(cvec).max(), np.percentile(np.abs(ss + cvec[ii] - cvec[jj]), 95),
           np.percentile(np.abs(ss), 95)), flush=True)
    return lregs, cvec.astype(np.float32)

L = 0.299 * CH['R'] + 0.587 * CH['G'] + 0.114 * CH['B']
uL7, cL7 = graph_solve(L, comb, STEP_CAP_L, "L/comb graph")
np.savez(SC + "/dc7_sharp.npz", region_ids=uL7, c_reg=cL7, bmax=BMAX)
addL = lut(uL7, cL7, comb)
for ch in 'RGB':
    CH[ch] += addL
uR7, cR7 = graph_solve(CH['R'], labr, STEP_CAP_C, "R/red graph")
uB7, cB7 = graph_solve(CH['B'], labb_eff, STEP_CAP_C, "B/blue graph")
np.savez(SC + "/dc7_chroma.npz", uR=uR7, cR=cR7, uB=uB7, cB=cB7)

# ---------------- site reports ----------------
pR7 = lut(uR7, cR7, labr); pB7 = lut(uB7, cB7, labb_eff)
for nmz, (raz, dez, rr) in (("t1219", (0.0, 7.2, 3)), ("t1252", (354.4, 17.0, 3)),
                            ("regor", (122.4, -47.3, 3.5)), ("crux", (186.6, -63.1, 4)),
                            ("araNGC6193", (250.3, -48.8, 4)), ("galcenter", (266, -29, 4))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(rr), nest=True)
    lz = np.abs(addL[pixz]); bz = np.abs(bl[pixz])
    print("zone %-11s |band L| p99 %.2f max %.2f | |cL7| p99 %.2f max %.2f | |R7-B7| p99 %.2f" %
          (nmz, np.percentile(bz, 99), bz.max(), np.percentile(lz, 99), lz.max(),
           np.percentile(np.abs(pR7[pixz] - pB7[pixz]), 99)), flush=True)
# named regions from the probe
for lab_ in (1837016, 1959344, 1833618, 1835317, 1712989, 2562459, 2645701, 2564158, 2647400):
    j = np.searchsorted(uL7, lab_)
    if j < len(uL7) and uL7[j] == lab_:
        print("  region %d: cL7 = %+.2f" % (lab_, cL7[j]), flush=True)
print("DONE")
