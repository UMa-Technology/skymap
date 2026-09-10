"""v7a-2: TILE-RESOLUTION seam-step measurement + graph solve.

The nside-512 banded measurement compared sky strips 15-25' apart -> in the
galactic band that difference is real structure, not artifact -> the first
graph solve painted +/-8 DN blocks at galcenter (preview regression).
Fix: measure the step ACROSS the exact plate boundary at quarter-tile
resolution (1.7'/px adjacent pairs; real-sky difference negligible even in
dense fields). Same doctrine as application: sharp things must be handled AT
the true boundary.

Base state = on-disk v6 tiles + dband7 (v7b) sampled per point. Halo discs
excluded. Per-pair medians -> Huber graph LSQ (L on comb, then R/B chroma on
plate mosaics with per-sample cL adjustment). Overwrites dc7_sharp/dc7_chroma.
"""
import os, sys, numpy as np, cv2, time
import healpy as hp
import scipy.sparse as sp
import scipy.sparse.linalg as spl
SC = os.environ["SCRATCH"]
sys.path.insert(0, SC)
from gsss_winner import load_channel, sky_to_pixel

W = 512; NST = 16; QR = 4; NS = 512
STEP_CAP_L = 8.0; STEP_CAP_C = 4.0

sh = np.load(SC + "/dc4_sharp.npz"); BMAX = int(sh['bmax'])
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
wr_c = wrz['winner'].astype(np.int64); wb_c = wbz['winner'].astype(np.int64)
comb_c = wr_c * BMAX + (wb_c + 1)
dbR = np.load(SC + "/dband7_R.npy"); dbG = np.load(SC + "/dband7_G.npy")
dbB = np.load(SC + "/dband7_B.npy")

plans = np.load(SC + "/halo_plan.npy", allow_pickle=True).item()
hexcl = np.zeros(hp.nside2npix(NS), bool)
for nm, pl in plans.items():
    hexcl[hp.query_disc(NS, hp.ang2vec(pl['ra'], pl['dec'], lonlat=True),
                        np.radians(pl['Rh'] + 0.3), nest=True)] = True
for ra0, dec0, rr in ((84.0534, -1.2019, 1.5), (85.1897, -1.9426, 1.5)):
    hexcl[hp.query_disc(NS, hp.ang2vec(ra0, dec0, lonlat=True), np.radians(rr), nest=True)] = True

hdr = None
for cand in [os.path.join(SC, 'getimage/hdrs/DSSHeaders'), os.path.join(SC, 'getimage/DSSHeaders')]:
    if os.path.isdir(cand): hdr = cand; break
plates_r = load_channel(hdr, ['XP', 'XS', 'ER', 'GR'])
plates_b = load_channel(hdr, ['XJ', 'S'])
vec_r = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_r])
vec_b = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_b])
COSR = np.cos(np.radians(7.8))
print("red %d blue %d plates" % (len(plates_r), len(plates_b)), flush=True)

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()
qx = np.arange(0, W, QR); QX, QY = np.meshgrid(qx, qx)
qsub = (p1(QY.ravel()) | (p1(QX.ravel()) << 1))

def winner_at(mean_vec, ra, dec, plates, vecs):
    cand = np.where(vecs @ mean_vec > COSR)[0]
    best = np.full(len(ra), -1e9); win = np.full(len(ra), -1, np.int64)
    for ci in cand:
        pl = plates[ci]
        x, y = sky_to_pixel(pl, ra, dec)
        m = np.minimum.reduce([x, y, pl['nx'] - x, pl['ny'] - y])
        upd = (m > 0) & (m > best)
        best[upd] = m[upd]; win[upd] = ci
    return win

SRC = "apps/skydata/surveys/dss"
def n4path(npix): return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

t0 = time.time()
S_wr_a = []; S_wr_b = []; S_wb_a = []; S_wb_b = []
S_cmb_a = []; S_cmb_b = []; S_dL = []; S_dR = []; S_dB = []
nproc = 0
for npix in range(3072):
    cells = comb_c[npix * 1024 + cellsub]
    if np.ptp(cells) == 0: continue
    img = cv2.imread(n4path(npix))
    if img is None: continue
    q = cv2.resize(img.astype(np.float32), (W // QR, W // QR), interpolation=cv2.INTER_AREA)
    nest = npix * (W * W) + qsub
    ra, dec = hp.pix2ang(NST * W, nest, nest=True, lonlat=True)
    pv = np.array(hp.ang2vec(ra, dec, lonlat=True))
    wr_ = winner_at(pv.mean(0), ra, dec, plates_r, vec_r)
    wb_ = winner_at(pv.mean(0), ra, dec, plates_b, vec_b)
    cell512 = nest // 1024
    ex = hexcl[cell512].reshape(128, 128)
    vL = (0.299 * q[:, :, 2] + 0.587 * q[:, :, 1] + 0.114 * q[:, :, 0]
          + (0.299 * dbR + 0.587 * dbG + 0.114 * dbB)[cell512].reshape(128, 128))
    vR = q[:, :, 2] + dbR[cell512].reshape(128, 128)
    vB = q[:, :, 0] + dbB[cell512].reshape(128, 128)
    combq = (wr_ * BMAX + (wb_ + 1)).reshape(128, 128)
    wrq = wr_.reshape(128, 128); wbq = wb_.reshape(128, 128)
    for (sa, sb) in (((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
                     ((slice(None, -1), slice(None)), (slice(1, None), slice(None)))):
        m = (combq[sa] != combq[sb]) & ~ex[sa] & ~ex[sb]
        if not m.any(): continue
        La = vL[sa][m]; Lb = vL[sb][m]
        ok = (La < 200) & (Lb < 200) & (np.abs(La - Lb) < 40)
        if not ok.any(): continue
        S_cmb_a.append(combq[sa][m][ok]); S_cmb_b.append(combq[sb][m][ok])
        S_wr_a.append(wrq[sa][m][ok]); S_wr_b.append(wrq[sb][m][ok])
        S_wb_a.append(wbq[sa][m][ok]); S_wb_b.append(wbq[sb][m][ok])
        S_dL.append((La - Lb)[ok])
        S_dR.append((vR[sa][m] - vR[sb][m])[ok])
        S_dB.append((vB[sa][m] - vB[sb][m])[ok])
    nproc += 1
    if nproc % 200 == 0:
        print("tiles %d (%ds) samples %d" % (nproc, time.time() - t0,
              sum(len(x) for x in S_dL)), flush=True)

cmb_a = np.concatenate(S_cmb_a); cmb_b = np.concatenate(S_cmb_b)
wr_a = np.concatenate(S_wr_a); wr_b = np.concatenate(S_wr_b)
wb_a = np.concatenate(S_wb_a); wb_b = np.concatenate(S_wb_b)
dL = np.concatenate(S_dL); dR = np.concatenate(S_dR); dB = np.concatenate(S_dB)
print("total samples %d from %d tiles (%ds)" % (len(dL), nproc, time.time() - t0), flush=True)
np.savez(SC + "/steps7_samples.npz", cmb_a=cmb_a, cmb_b=cmb_b, wr_a=wr_a, wr_b=wr_b,
         wb_a=wb_a, wb_b=wb_b, dL=dL.astype(np.float32), dR=dR.astype(np.float32),
         dB=dB.astype(np.float32))

def solve_graph(la, lb, dv, cap, tag, minn=40):
    """orient pairs, per-pair median/MAD, damped Huber graph LSQ."""
    swap = la > lb
    a = np.where(swap, lb, la); b = np.where(swap, la, lb)
    v = np.where(swap, -dv, dv)
    lregs = np.unique(np.concatenate([a, b])); NL = len(lregs)
    ia = np.searchsorted(lregs, a); ib = np.searchsorted(lregs, b)
    key = ia.astype(np.int64) * NL + ib
    order = np.lexsort((v, key))
    ks = key[order]; vs = v[order]
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    counts = np.diff(np.r_[starts, len(ks)])
    med = vs[starts + counts // 2]
    q1 = vs[starts + counts // 4]; q3 = vs[starts + (3 * counts) // 4]
    ukey = ks[starts]
    keep = counts >= minn
    ii = (ukey[keep] // NL).astype(np.int64); jj = (ukey[keep] % NL).astype(np.int64)
    ss = med[keep].astype(np.float64)
    madp = np.maximum((q3 - q1)[keep] * 0.5, 0.5)
    ww0 = np.minimum(counts[keep], 2000) / (1.0 + (madp / 8.0) ** 2)
    print("%s: regions %d pairs %d (kept %d) |step| p50 %.2f p95 %.2f" %
          (tag, NL, len(ukey), len(ii), np.median(np.abs(ss)), np.percentile(np.abs(ss), 95)),
          flush=True)
    lam = np.full(NL, 2.0)
    w = ww0.copy()
    for itn in range(4):
        Adiag = lam.copy()
        np.add.at(Adiag, ii, w); np.add.at(Adiag, jj, w)
        Aoff = sp.coo_matrix((-w, (ii, jj)), shape=(NL, NL))
        A = sp.diags(Adiag) + Aoff + Aoff.T
        bvec = np.zeros(NL)
        np.add.at(bvec, ii, -w * ss); np.add.at(bvec, jj, w * ss)
        cvec, info = spl.cg(A.tocsr(), bvec, rtol=1e-8, maxiter=3000, M=sp.diags(1.0 / Adiag))
        if info != 0: print("  cg info", info, flush=True)
        r_ = ss + cvec[ii] - cvec[jj]
        sc = 1.345 * max(1.4826 * np.median(np.abs(r_)), 0.25)
        w = ww0 * np.minimum(1.0, sc / np.maximum(np.abs(r_), 1e-6))
    cvec = np.clip(cvec, -cap, cap)
    act = np.abs(cvec) > 0.3
    print("  active %d |c| p95 %.2f max %.2f | seam resid p95 %.2f (was %.2f)" %
          (int(act.sum()), np.percentile(np.abs(cvec[act]), 95) if act.any() else 0,
           np.abs(cvec).max(), np.percentile(np.abs(ss + cvec[ii] - cvec[jj]), 95),
           np.percentile(np.abs(ss), 95)), flush=True)
    return lregs, cvec.astype(np.float32)

def lutv(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

uL7, cL7 = solve_graph(cmb_a, cmb_b, dL, STEP_CAP_L, "L/comb")
np.savez(SC + "/dc7_sharp.npz", region_ids=uL7, c_reg=cL7, bmax=BMAX)
adjL = lutv(uL7, cL7, cmb_a) - lutv(uL7, cL7, cmb_b)
labr_a = np.where(wr_a < 0, 19000, wr_a); labr_b = np.where(wr_b < 0, 19000, wr_b)
labb_a = np.where(wb_a < 0, labr_a + 20000, wb_a); labb_b = np.where(wb_b < 0, labr_b + 20000, wb_b)
mR = labr_a != labr_b
uR7, cR7 = solve_graph(labr_a[mR], labr_b[mR], (dR + adjL)[mR], STEP_CAP_C, "R/red")
mB = labb_a != labb_b
uB7, cB7 = solve_graph(labb_a[mB], labb_b[mB], (dB + adjL)[mB], STEP_CAP_C, "B/blue")
np.savez(SC + "/dc7_chroma.npz", uR=uR7, cR=cR7, uB=uB7, cB=cB7)

# zone report
pL = lutv(uL7, cL7, comb_c)
labr_c = wr_c.copy(); labr_c[labr_c < 0] = 19000
labbe_c = np.where(wb_c < 0, labr_c + 20000, wb_c)
pR = lutv(uR7, cR7, labr_c); pB = lutv(uB7, cB7, labbe_c)
for nmz, (raz, dez, rr) in (("t1219", (0.0, 7.2, 3)), ("t1252", (354.4, 17.0, 3)),
                            ("regor", (122.4, -47.3, 3.5)), ("crux", (186.6, -63.1, 4)),
                            ("araNGC6193", (250.3, -48.8, 4)), ("galcenter", (266, -29, 4))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(rr), nest=True)
    lz = np.abs(pL[pixz])
    print("zone %-11s |cL7| p50 %.2f p99 %.2f max %.2f | |R7| max %.2f |B7| max %.2f" %
          (nmz, np.median(lz), np.percentile(lz, 99), lz.max(),
           np.abs(pR[pixz]).max(), np.abs(pB[pixz]).max()), flush=True)
print("DONE %ds" % (time.time() - t0), flush=True)
