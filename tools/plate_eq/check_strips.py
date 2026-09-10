"""Verify the Crux slivers get leveled by dc7: render dev-field before/after at
nside512 and report the sliver regions' constants + measured steps."""
import os, sys, numpy as np, healpy as hp
import healpy.projector as hpproj
from PIL import Image
SC = os.environ["SCRATCH"]
sys.path.insert(0, SC)
from seamnet_common import load_state, load_labels
NS = 512; NPIX = hp.nside2npix(NS)

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh4 = np.load(SC + "/dc4_sharp.npz")
U0 = sh4['region_ids']; CREG = sh4['c_reg']; BMAX = int(sh4['bmax'])
sh6 = np.load(SC + "/dc6_sharp.npz"); U6 = sh6['region_ids']; C6 = sh6['c_reg']
sh7 = np.load(SC + "/dc7_sharp.npz"); U7 = sh7['region_ids']; C7 = sh7['c_reg']
resid6 = np.load(SC + "/dDark6_resid.npy")
c5 = np.load(SC + "/dc5_chroma.npz"); c6 = np.load(SC + "/dc6_chroma.npz")
c7 = np.load(SC + "/dc7_chroma.npz")
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
labr, labb_eff = load_labels()
dbR = np.load(SC + "/dband7_R.npy"); dbG = np.load(SC + "/dband7_G.npy")
dbB = np.load(SC + "/dband7_B.npy")

def lut(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

cl46 = lut(U0, CREG, comb) + lut(U6, C6, comb)
cl7 = lut(U7, C7, comb)
pR = lut(c5['uR'], c5['cR'], labr) + lut(c6['uR'], c6['cR'], labr)
pB = lut(c5['uB'], c5['cB'], labb_eff) + lut(c6['uB'], c6['cB'], labb_eff)
pR7 = lut(c7['uR'], c7['cR'], labr); pB7 = lut(c7['uB'], c7['cB'], labb_eff)
lum = drest['dR'] + resid4 + cl46 + resid6
L_before = (0.299 * (R + lum + pR + dbR) + 0.587 * (G + lum + 0.5 * (pR + pB) + dbG)
            + 0.114 * (B + lum + pB + dbB))
L_after = L_before + cl7 + 0.299 * pR7 + 0.587 * 0.5 * (pR7 + pB7) + 0.114 * pB7

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

bgf = L_before.copy()
for it in range(2):
    s = smooth(bgf, 1.0)
    r_ = bgf - s
    sig = 1.4826 * np.median(np.abs(r_ - np.median(r_)))
    bgf = np.where(r_ > 2.0 * sig, s, bgf)
trend = smooth(bgf, 3.0)
devB = (bgf - trend).astype(np.float32)
devA = devB + (L_after - L_before).astype(np.float32)

def render(name, ra, dec, span_deg, xs=800):
    reso = span_deg * 60.0 / xs
    proj = hpproj.GnomonicProj(rot=(ra, dec, 0), xsize=xs, ysize=xs, reso=reso)
    v2p = lambda x, y, z: hp.vec2pix(NS, x, y, z, nest=True)
    d1 = np.array(proj.projmap(devB, v2p)); d2 = np.array(proj.projmap(devA, v2p))
    g1 = np.clip((d1 + 6.0) / 12.0, 0, 1); g2 = np.clip((d2 + 6.0) / 12.0, 0, 1)
    im = np.concatenate([np.stack([g1] * 3, -1), np.ones((xs, 6, 3)),
                         np.stack([g2] * 3, -1)], axis=1)
    Image.fromarray((im[::-1] * 255).astype(np.uint8)).save(SC + "/diag7/%s.png" % name)
    print("rendered", name, flush=True)

os.makedirs(SC + "/diag7", exist_ok=True)
render("strips_check", 187.0, -64.5, 14.0)
render("regor_check", 122.4, -47.3, 9.0)

# sliver report: small elongated regions near crux with their c7
pix = hp.query_disc(NS, hp.ang2vec(187.0, -64.5, lonlat=True), np.radians(7), nest=True)
u, cnt = np.unique(comb[pix], return_counts=True)
for lab_, n_ in zip(u, cnt):
    j = np.searchsorted(U7, lab_)
    c7v = C7[j] if j < len(U7) and U7[j] == lab_ else 0.0
    if n_ < 600 and abs(c7v) > 0.3:
        sel = pix[comb[pix] == lab_]
        dv = np.median(devB[sel])
        print("region %-9d area %-4d med-dev %+5.2f  c7 %+5.2f" % (lab_, n_, dv, c7v), flush=True)
print("DONE")
