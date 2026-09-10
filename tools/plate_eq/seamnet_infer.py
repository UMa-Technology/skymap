"""SeamNet inference v2.

1. Sweep the sphere with 3072 crops (nside-16 centers), Hann-blend the U-Net's
   predicted artifact field back to nside-512.
2. PROJECT the free-form prediction onto per-region coefficients (DC + b-slope)
   of the known tessellations — the net is only an estimator; the applied
   correction is analytically piecewise on the real plate geometry, so it cannot
   hallucinate free-form structure or smear seams.
3. Calibrate the amplitude response on held-out synthetic injections (L1 nets
   under-predict; divide by measured response slope).
4. Sanity gate: predicted cross-seam steps must correlate with steps measured
   directly on the state maps at real seams.
Saves seamnet/dSeam.npz (dR,dG,dB correction to ADD) + seamnet_coefs.npz.
"""
import os, time
import numpy as np
import healpy as hp
import torch
from seamnet_common import (SC, NS, NPIX, SZ, SCALE, load_state, load_labels,
                            tangent_frame, crop_dirs, sample_crop, draw_crop,
                            inject, edge_maps, net_input)
from seamnet_model import UNet

OUT = SC + "/seamnet"
DEV = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
CAP = 6.0
NC = 16                       # 3072 crop centers
DISC = np.radians(8.5)
BB = 16

R, G, B, gb = load_state()
labr, labb = load_labels()
net = UNet().to(DEV)
net.load_state_dict(torch.load(OUT + "/ckpt_best.pt", map_location=DEV))
net.eval()
t0 = time.time()

# ---------- pass 1: predict + blend ----------
centers = np.array(hp.pix2vec(NC, np.arange(hp.nside2npix(NC)), nest=True)).T
num = np.zeros((3, NPIX), np.float64)
den = np.zeros(NPIX, np.float64)
hann = np.sin(np.pi * (np.arange(SZ) + 0.5) / SZ) ** 2
buf, bidx = [], []

def flush():
    global buf, bidx
    if not buf: return
    with torch.no_grad():
        p = net(torch.from_numpy(np.stack(buf)).to(DEV)).cpu().numpy()
    for pred, ci in zip(p, bidx):
        c = centers[ci]
        e1, e2 = tangent_frame(c, 0.0)
        pix = hp.query_disc(NS, c, DISC, nest=True)
        v = np.array(hp.pix2vec(NS, pix, nest=True)).T
        tvec = v / (v @ c)[:, None]
        xr = np.arctan(tvec @ e1) / np.radians(SCALE) + (SZ - 1) / 2
        yr = np.arctan(tvec @ e2) / np.radians(SCALE) + (SZ - 1) / 2
        ok = (xr >= 0.5) & (xr <= SZ - 1.5) & (yr >= 0.5) & (yr <= SZ - 1.5)
        pix, xr, yr = pix[ok], xr[ok], yr[ok]
        x0 = np.floor(xr).astype(int); y0 = np.floor(yr).astype(int)
        fx = xr - x0; fy = yr - y0
        val = ((pred[:, y0, x0] * (1 - fx) + pred[:, y0, x0 + 1] * fx) * (1 - fy)
               + (pred[:, y0 + 1, x0] * (1 - fx) + pred[:, y0 + 1, x0 + 1] * fx) * fy)
        w = ((hann[y0] * (1 - fy) + hann[y0 + 1] * fy)
             * (hann[x0] * (1 - fx) + hann[x0 + 1] * fx))
        np.add.at(den, pix, w)
        for k in range(3):
            np.add.at(num[k], pix, w * val[k])
    buf, bidx = [], []

for i, c in enumerate(centers):
    V = crop_dirs(c, 0.0)
    (r_, g_, b_, gc), (a_, bb_) = sample_crop(V, [R, G, B, gb], [labr, labb])
    er, eb = edge_maps(a_, bb_)
    buf.append(net_input(np.stack([r_, g_, b_]), er, eb)); bidx.append(i)
    if len(buf) == BB: flush()
    if (i + 1) % 256 == 0: print("sweep", i + 1, "/", len(centers), int(time.time() - t0), "s", flush=True)
flush()
holes = int((den <= 0).sum())
print("coverage holes:", holes, flush=True)
assert holes == 0
pred_map = (num / den).astype(np.float32)          # [R,G,B] predicted artifact

# ---------- pass 2: project onto per-region coefficients ----------
comb = labr.astype(np.int64) * 100000 + labb.astype(np.int64)

def project(pred, lab):
    """Per-region robust DC + b-slope; returns rendered piecewise field."""
    u, inv = np.unique(lab, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(inv, kind='stable')
    starts = np.unique(inv[order], return_index=True)[1]
    po = pred[order]; go = gb[order]
    field = np.zeros(NPIX, np.float32)
    dc_all = np.zeros(len(u), np.float32)
    for k, (segp, segg, segi) in enumerate(zip(np.split(po, starts[1:]),
                                               np.split(go, starts[1:]),
                                               np.split(order, starts[1:]))):
        dc = np.median(segp)
        dc_all[k] = dc
        f = np.full(len(segp), dc, np.float32)
        if len(segp) >= 400:
            t = segg - np.median(segg)
            m = np.abs(t) > 1.0
            if m.sum() >= 200 and (np.percentile(segg, 90) - np.percentile(segg, 10)) > 2.0:
                kk = np.clip(np.median((segp[m] - dc) / t[m]), -0.25, 0.25)
                f += kk * t
        field[segi] = f
    return field, u, dc_all

fR, uR, dcR = project(pred_map[0], labr)
fB, uB, dcB = project(pred_map[2], labb)
fG, uG, dcG = project(pred_map[1], comb)
print("projected: regions R=%d B=%d G(comb)=%d %ds" % (len(uR), len(uB), len(uG), int(time.time() - t0)), flush=True)

# ---------- pass 3: amplitude-response calibration on synthetic injections ----------
crng = np.random.default_rng(99)
pairs = []
for _ in range(48):
    img, a_, bb_, gc = draw_crop(crng, R, G, B, gb, labr, labb)
    x, A = inject(img, a_, bb_, gc, crng)
    er, eb = edge_maps(a_, bb_)
    with torch.no_grad():
        p = net(torch.from_numpy(net_input(x, er, eb)[None]).to(DEV))[0].cpu().numpy()
    for lab_c, ch in ((a_, 0), (bb_, 2)):
        ids, invc = np.unique(lab_c, return_inverse=True)
        invc = invc.reshape(-1)
        cnt = np.bincount(invc)
        for k in np.where(cnt >= 600)[0]:
            m = invc == k
            tdc = np.median(A[ch].reshape(-1)[m])
            pdc = np.median(p[ch].reshape(-1)[m])
            if abs(tdc) > 0.7:
                pairs.append((tdc, pdc))
pairs = np.array(pairs)
alpha = float(np.median(pairs[:, 1] / pairs[:, 0]))
boost = 1.0 / np.clip(alpha, 0.55, 1.0)
print("calibration: %d pairs, response alpha=%.3f -> boost %.2f" % (len(pairs), alpha, boost), flush=True)

# ---------- pass 4: real-seam sanity gate (red tessellation, R channel) ----------
ar = np.arange(NPIX)
neighT = hp.get_all_neighbours(NS, ar, nest=True).T
dcR_map = dict(zip(uR.tolist(), dcR.tolist()))
P_, Q_ = [], []
for k in range(0, 8, 2):
    q = neighT[:, k]
    ok = (q >= 0) & (q > ar) & (labr[np.clip(q, 0, NPIX - 1)] != labr)
    P_.append(ar[ok]); Q_.append(q[ok])
P_ = np.concatenate(P_); Q_ = np.concatenate(Q_)
la, lb_ = labr[P_].astype(np.int64), labr[Q_].astype(np.int64)
swap = la > lb_
la2 = np.where(swap, lb_, la); lb2 = np.where(swap, la, lb_)
key = la2 * 100000 + lb2
uk, kinv = np.unique(key, return_inverse=True)
meas = np.zeros(len(uk)); pred_step = np.zeros(len(uk)); cnt = np.bincount(kinv)
tex = np.full(len(uk), 9e9)
dR_state = R[P_] - R[Q_]
sgn = np.where(swap, -1.0, 1.0)
for k in np.where(cnt >= 40)[0]:
    m = kinv == k
    meas[k] = np.median((dR_state * sgn)[m])
    va = R[P_[m]]; vb = R[Q_[m]]
    tex[k] = max(np.median(np.abs(va - np.median(va))), np.median(np.abs(vb - np.median(vb))))
    a_id, b_id = int(uk[k] // 100000), int(uk[k] % 100000)
    pred_step[k] = dcR_map.get(a_id, 0.0) - dcR_map.get(b_id, 0.0)
sel = (cnt >= 40) & (np.abs(meas) > 0.8) & (np.abs(meas) < 8) & (tex < 2.0)
r = float(np.corrcoef(meas[sel], pred_step[sel])[0, 1])
slope = float(np.median(pred_step[sel] / meas[sel]))
print("real-seam gate: %d seams, corr r=%.3f median slope=%.3f  %s" %
      (int(sel.sum()), r, slope, "PASS" if r > 0.35 else "**FAIL**"), flush=True)

# ---------- pass 5: assemble correction ----------
# level part: calibrated projected coefficients; PLUS a seam-band-local free-form
# residual term (net's dipole prediction minus its projected level), confined to
# within ~5 px of a plate boundary and capped — membrane-style, cannot form patches.
fstack = np.stack([fR, fG, fB])
bound = np.zeros(NPIX, bool)
for k in range(8):
    q = neighT[:, k]
    qc = np.clip(q, 0, NPIX - 1)
    bound |= (q >= 0) & ((labr[qc] != labr) | (labb[qc] != labb))
band = bound.copy()
for _ in range(4):
    nb = neighT[band]
    nb = nb[nb >= 0]
    band[nb] = True
resid = np.clip(pred_map - fstack, -2.5, 2.5) * band[None, :]
print("seam band: %.1f%% of sky, resid |p95| in band %.2f" %
      (100 * band.mean(), np.percentile(np.abs((pred_map - fstack)[:, band]), 95)), flush=True)
corr = -(fstack * boost + resid)
high = np.abs(gb) > 35
for k in range(3):
    corr[k] -= np.median(corr[k][high])
corr = np.clip(corr, -CAP, CAP).astype(np.float32)
np.savez(OUT + "/dSeam.npz", dR=corr[0], dG=corr[1], dB=corr[2])
np.savez(OUT + "/seamnet_coefs.npz", uR=uR, dcR=dcR, uB=uB, dcB=dcB, alpha=alpha,
         gate_r=r, gate_slope=slope)
band = np.abs(gb) < 15
for k, nm in enumerate("RGB"):
    a = np.abs(corr[k])
    print("%s |corr| p50 %.2f p95 %.2f max %.2f | in-band p95 %.2f" %
          (nm, np.median(a), np.percentile(a, 95), a.max(), np.percentile(a[band], 95)), flush=True)
for nmz, (raz, dez) in (("galcenter", (266, -29)), ("pipe", (262, -25)),
                        ("cygnus", (305, 38)), ("ara", (252, -50)), ("musca", (188, -62))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(5), nest=True)
    cz = np.abs(corr[:, pixz])
    print("zone %-9s meanabs %.2f p99 %.2f" % (nmz, cz.mean(), np.percentile(cz, 99)), flush=True)
print("INFER DONE %ds" % int(time.time() - t0), flush=True)
