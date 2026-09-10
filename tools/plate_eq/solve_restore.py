"""Boundary restoration pass.

Evidence (band profiles at the strongest current seams): earlier stages measured
"steps" at boundaries where the ORIGINAL sky was a smooth real gradient, and their
corrections CREATED 4-8 DN cliffs and one-sided trenches there. Decomposition used
here: current_discontinuity = s_orig (original plate step, robust banded estimate
with confidence) + jump_C (discontinuity of the total applied correction field C —
known EXACTLY, C = sum of all delta fields, no stars/structure/noise).

Per seam, per side:
  excess_d  = C banded mean at depth d - interior(C)   -> trench/overshoot profile,
              removed exactly (depth-resolved).
  s_eff     = conf*s_orig_est + jump_C'                -> membrane ramp -+ s_eff/2,
              gated by: sign agreement with a direct current-step estimate AND
              |direct| > 0.7 (there must BE a visible break to remove).
Gating outcome matrix: chain fixed a real step well -> direct~0 -> no action;
chain created a cliff on smooth sky -> undone; chain missed a real step -> flattened.
Saves delta_restore.npz.
"""
import os, numpy as np, healpy as hp
SC = os.path.dirname(os.path.abspath(__file__))
NS = 512; NPIX = hp.nside2npix(NS); ar = np.arange(NPIX)

z = np.load(SC + "/mapbase.npz")
orig = {'R': z['mapR'].astype(np.float64), 'G': z['mapG'].astype(np.float64),
        'B': z['mapB'].astype(np.float64)}
d = np.load(SC + "/delta512.npz"); dL = np.load(SC + "/dLum512.npy")
dreg = np.load(SC + "/delta_regions_final.npz"); dm = np.load(SC + "/delta_membrane.npz")
base = np.load(SC + "/dDarkDC.npy") + np.load(SC + "/dDarkDC2.npy")
C = {'R': d['dR'] + dL + dreg['dR'] + dm['dR'] + base,
     'G': d['dG'] + dL + dreg['dG'] + dm['dG'] + base,
     'B': d['dB'] + dL + dreg['dB'] + dm['dB'] + base}
cur = {ch: orig[ch] + C[ch] for ch in 'RGB'}

wr = np.load(SC + "/winner_red.npz", allow_pickle=True)
wb = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb = wr['winner'].astype(np.int64) * (wb['winner'].max() + 2) + (wb['winner'].astype(np.int64) + 1)
u, lab = np.unique(comb, return_inverse=True); NL = len(u)
neighT = hp.get_all_neighbours(NS, ar, nest=True).T.copy()
P = []; Q = []
for k in range(8):
    q = neighT[:, k]; ok = (q >= 0) & (q > ar) & (lab[np.clip(q, 0, NPIX - 1)] != lab)
    P.append(ar[ok]); Q.append(q[ok])
P = np.concatenate(P); Q = np.concatenate(Q)
la = lab[P]; lb = lab[Q]; a = np.minimum(la, lb); b = np.maximum(la, lb)
key = a * NL + b; uk, pairidx = np.unique(key, return_inverse=True)
pa = (uk // NL).astype(np.int64); pb = (uk % NL).astype(np.int64); NPAIR = len(uk)

pairof = np.full(NPIX, -1, np.int64); depth = np.full(NPIX, 127, np.int8)
seedpix = np.concatenate([P, Q]); seedpair = np.concatenate([pairidx, pairidx])
o = np.argsort(seedpix, kind='stable'); sp = seedpix[o]; pp = seedpair[o]
fi = np.unique(sp, return_index=True)[1]
pairof[sp[fi]] = pp[fi]; depth[sp[fi]] = 0; frontier = sp[fi]
MAXD = 10
for dcur in range(1, MAXD + 1):
    nb = neighT[frontier].ravel(); src = np.repeat(frontier, 8)
    okn = nb >= 0; nb = nb[okn]; src = src[okn]
    ok2 = (depth[nb] == 127) & (lab[nb] == lab[src]); nb = nb[ok2]; src = src[ok2]
    if len(nb) == 0: break
    oo = np.argsort(nb, kind='stable'); nb = nb[oo]; src = src[oo]
    fi = np.unique(nb, return_index=True)[1]; nb = nb[fi]; src = src[fi]
    pairof[nb] = pairof[src]; depth[nb] = dcur; frontier = nb

mm = pairof >= 0
sideA_pix = np.zeros(NPIX, bool)
sideA_pix[mm] = lab[mm] == pa[pairof[mm]]
# group key: (pair, side, depth) for depth 0..8
gd = np.clip(depth.astype(np.int64), 0, 12)
gkey = (pairof * 2 + sideA_pix.astype(np.int64)) * 16 + gd
gsel = mm & (gd <= 8)
GK = gkey[gsel]; GPIX = ar[gsel]
order = np.argsort(GK, kind='stable'); GKs = GK[order]; GPo = GPIX[order]
ugk, starts = np.unique(GKs, return_index=True)
cntg = np.diff(np.append(starts, len(GKs)))

# exact banded means of C per (pair,side,depth); MEDIAN-free (C is noiseless fields)
def band_means(field):
    s = np.add.reduceat(field[GPo], starts)
    return s / cntg
CM = {ch: band_means(C[ch]) for ch in 'RGB'}
gk_pair = (ugk // 16) // 2; gk_side = (ugk // 16) % 2; gk_d = ugk % 16

def side_depth_table(vals):
    """(NPAIR,2,9) table of banded values, nan where absent."""
    T = np.full((NPAIR, 2, 9), np.nan)
    T[gk_pair, gk_side, gk_d] = vals
    return T

# robust banded linear fit on ORIGINAL (structure present) per (pair,side): depths 1..6
mband = mm & (depth >= 1) & (depth <= 6)
bp = np.where(mband)[0]; pid = pairof[bp]; sA = sideA_pix[bp]; dep = depth[bp].astype(np.float64)
kps = pid * 2 + sA.astype(np.int64)
oo = np.argsort(kps, kind='stable'); kps_s = kps[oo]; bp_s = bp[oo]; dep_s = dep[oo]
ukp, stt = np.unique(kps_s, return_index=True)
segpix = np.split(bp_s, stt[1:]); segdep = np.split(dep_s, stt[1:])

def measure_orig(vals):
    est = {}
    for kk, pixs, deps in zip(ukp, segpix, segdep):
        if len(pixs) < 6: continue
        v = vals[pixs]; med = np.median(v); mad = np.median(np.abs(v - med)) + 1e-6
        keep = np.abs(v - med) < 4 * mad
        if keep.sum() < 6: continue
        vv = v[keep]; dd = deps[keep]
        A_ = np.stack([np.ones_like(dd), dd], 1)
        c = np.linalg.lstsq(A_, vv, rcond=None)[0]
        est[int(kk)] = (c[0], c[1], mad, len(vv))
    s0 = np.zeros(NPAIR); conf = np.zeros(NPAIR)
    for i in range(NPAIR):
        ea = est.get(i * 2 + 1); eb = est.get(i * 2 + 0)
        if not ea or not eb: continue
        s0[i] = ea[0] - eb[0]
        conf[i] = 1.0 / (1.0 + ((ea[2] + eb[2]) / 2.5) ** 2 + (abs(ea[1] - eb[1]) / 0.8) ** 2)
    return s0, conf

t = np.zeros(NPIX); t[mm] = 1.0 - depth[mm].astype(np.float64) / (MAXD + 1)
wd = np.zeros(NPIX); wd[mm] = t[mm] * t[mm] * (3 - 2 * t[mm])
signA = np.zeros(NPIX); signA[mm] = np.where(sideA_pix[mm], 1.0, -1.0)

# membrane ramp value at each depth (same smoothstep as the pixel weights)
tt = 1.0 - np.arange(9) / (MAXD + 1)
wd_d = tt * tt * (3 - 2 * tt)                          # (9,)

# Luminance-only solve: the same correction goes to R,G,B so chroma is untouched
# (per-channel solves picked different plans per channel -> coloured wedges).
orig['L'] = 0.299 * orig['R'] + 0.587 * orig['G'] + 0.114 * orig['B']
C['L'] = 0.299 * C['R'] + 0.587 * C['G'] + 0.114 * C['B']
cur['L'] = orig['L'] + C['L']
CM['L'] = band_means(C['L'])

out = {}
for ch in 'L':
    with np.errstate(all='ignore'):
        T = side_depth_table(CM[ch])                   # C banded means
        Tcur = side_depth_table(band_means(cur[ch]))   # current banded means (structure incl.)
        interior = np.nanmedian(T[:, :, 6:9], axis=2)  # (NPAIR,2)
    excess = np.nan_to_num(T - interior[:, :, None], nan=0.0)      # (NPAIR,2,9)
    interior = np.nan_to_num(interior, nan=0.0)
    Tcur = np.nan_to_num(Tcur, nan=0.0)
    jumpC = interior[:, 1] - interior[:, 0]            # A - B of the correction field
    s_orig, conf = measure_orig(orig[ch])
    s_now_dir, _ = measure_orig(cur[ch])               # direct current estimate
    s_eff = np.clip(conf * np.clip(s_orig, -8, 8) + jumpC, -8, 8)
    gate = (np.abs(s_now_dir) > 0.7) & (np.sign(s_eff) == np.sign(s_now_dir)) & (np.abs(s_eff) > 0.5)
    # four candidate treatments per seam; deterministic visibility score; 'none' is
    # always a candidate so the chosen plan can only improve the score.
    memb_prof = np.zeros((NPAIR, 2, 9))
    memb_prof[:, 1, :] = -(s_eff * gate)[:, None] / 2.0 * wd_d[None, :]   # side A
    memb_prof[:, 0, :] = +(s_eff * gate)[:, None] / 2.0 * wd_d[None, :]   # side B
    exc_prof = -excess
    cand = {0: np.zeros((NPAIR, 2, 9)), 1: memb_prof, 2: exc_prof, 3: memb_prof + exc_prof}
    scores = np.zeros((4, NPAIR))
    for v, cp in cand.items():
        Pres = Tcur + cp
        disc = np.abs(Pres[:, 1, 0] - Pres[:, 0, 0])
        excC = excess + cp                             # residual C-warp after treatment
        trench = np.mean(np.abs(excC[:, :, :6]), axis=(1, 2))
        scores[v] = disc + 0.6 * trench
    best = np.argmin(scores, axis=0)
    use_memb = (best == 1) | (best == 3)
    use_exc = (best == 2) | (best == 3)
    s_apply = s_eff * gate * use_memb
    c = np.zeros(NPIX)
    pofm = pairof[mm]; sidm = sideA_pix[mm].astype(np.int64); gdm = np.clip(depth[mm], 0, 8).astype(np.int64)
    exc_px = excess[pofm, sidm, gdm] * use_exc[pofm]
    exc_px[depth[mm] > 8] = 0.0
    c[mm] = -exc_px - signA[mm] * s_apply[pofm] / 2.0 * wd[mm]
    c = np.clip(c, -4, 4)
    out[ch] = c.astype(np.float32)
    print("%s: plan none/memb/exc/both = %d/%d/%d/%d | score %.3f -> %.3f | corr |p99| %.2f" %
          (ch, int((best == 0).sum()), int((best == 1).sum()), int((best == 2).sum()),
           int((best == 3).sum()), scores[0].mean(), scores[best, np.arange(NPAIR)].mean(),
           np.percentile(np.abs(c), 99)), flush=True)

np.savez(SC + "/delta_restore.npz", dR=out['L'], dG=out['L'], dB=out['L'])
print("saved delta_restore.npz (luminance-only, all channels equal)", flush=True)

# verification: re-profile the 4 case seams from the diagnosis
labr_w = wr['winner'].astype(np.int64)
for ch in ['L']:
    new = cur[ch] + out[ch]
    P2 = []; Q2 = []
    for k in range(0, 8, 2):
        q = neighT[:, k]; ok = (q >= 0) & (q > ar) & (labr_w[np.clip(q, 0, NPIX - 1)] != labr_w)
        P2.append(ar[ok]); Q2.append(q[ok])
    P2 = np.concatenate(P2); Q2 = np.concatenate(Q2)
    st_now = np.abs(cur[ch][P2] - cur[ch][Q2]); st_new = np.abs(new[P2] - new[Q2])
    print("red-boundary 1px |step| mean: now %.3f -> restored %.3f (orig %.3f)" %
          (st_now.mean(), st_new.mean(), np.abs(orig[ch][P2] - orig[ch][Q2]).mean()), flush=True)
print("DONE")
