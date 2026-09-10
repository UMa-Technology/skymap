"""Diagnose the 4 remaining problem sites (post-v6):
 1. Crux/Musca long bright strips (user screenshot 1)
 2. Regor halo plate-cut + bright plate block (user screenshot 2)
 3. tile N4/1252 area (354.4,+17.0)   4. tile N4/1219 area (0.0,+7.2)
Render current full state (chain+dc4+dc5+dc6) with region boundaries overlaid.
"""
import os, sys, numpy as np, healpy as hp
import healpy.projector as hpproj
from PIL import Image
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from seamnet_common import load_state, load_labels
NS = 512

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh4 = np.load(SC + "/dc4_sharp.npz")
U0 = sh4['region_ids']; CREG = sh4['c_reg']; BMAX = int(sh4['bmax'])
sh6 = np.load(SC + "/dc6_sharp.npz")
U6 = sh6['region_ids']; C6 = sh6['c_reg']
resid6 = np.load(SC + "/dDark6_resid.npy")
c5 = np.load(SC + "/dc5_chroma.npz")
c6 = np.load(SC + "/dc6_chroma.npz")
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
CR = R + lum + pR
CG = G + lum + 0.5 * (pR + pB)
CB = B + lum + pB

def render(name, ra, dec, span_deg, xs=900):
    reso = span_deg * 60.0 / xs
    proj = hpproj.GnomonicProj(rot=(ra, dec, 0), xsize=xs, ysize=xs, reso=reso)
    v2p = lambda x, y, z: hp.vec2pix(NS, x, y, z, nest=True)
    imgs = [np.array(proj.projmap(M, v2p)) for M in (CR, CG, CB)]
    regm = np.array(proj.projmap(comb.astype(np.float64), v2p))
    rgb = np.stack(imgs, -1)
    med = np.median(rgb)
    im = np.arcsinh((rgb - med) / 4.0)
    lo, hi = np.percentile(im, [1, 99.7])
    im = np.clip((im - lo) / (hi - lo), 0, 1)
    edge = np.zeros(regm.shape, bool)
    edge[:-1, :] |= regm[:-1, :] != regm[1:, :]
    edge[:, :-1] |= regm[:, :-1] != regm[:, 1:]
    im2 = im.copy(); im2[edge] = [1.0, 0.55, 0.1]
    canvas = np.concatenate([im, np.ones((im.shape[0], 8, 3)), im2], axis=1)
    canvas = (canvas[::-1] * 255).astype(np.uint8)
    Image.fromarray(canvas).save(SC + "/diag7/%s.png" % name)
    print("rendered", name, flush=True)

os.makedirs(SC + "/diag7", exist_ok=True)
render("crux_musca", 187.0, -64.5, 14.0)
render("regor", 122.4, -47.3, 9.0)
render("t1252", 354.4, 17.0, 7.0)
render("t1219", 0.0, 7.2, 7.0)
print("DONE")
