"""Probe: are the residual bands (1) thin sliver REGIONS or (2) in-plate EDGE bands?
Render dev field (L - 3deg trend, linear +/-6 DN) + random-colored region map,
and print banded dev medians vs hop-distance-to-seam for the dominant seams.
"""
import os, sys, numpy as np, healpy as hp
import healpy.projector as hpproj
from PIL import Image
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from seamnet_common import load_state, load_labels
NS = 512; NPIX = hp.nside2npix(NS)

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
CR = R + lum + pR; CG = G + lum + 0.5 * (pR + pB); CB = B + lum + pB
L = 0.299 * CR + 0.587 * CG + 0.114 * CB

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

print("computing dev field...", flush=True)
# star-suppressed background then highpass 3 deg
bgf = L.copy()
for it in range(2):
    s = smooth(bgf, 1.0)
    r_ = bgf - s
    sig = 1.4826 * np.median(np.abs(r_ - np.median(r_)))
    bgf = np.where(r_ > 2.0 * sig, s, bgf)
dev = bgf - smooth(bgf, 3.0)

rng = np.random.default_rng(7)
uc = np.unique(comb)
cmap = rng.uniform(0.15, 1.0, (len(uc), 3))
regcol_idx = np.searchsorted(uc, comb)

def render(name, ra, dec, span_deg, xs=800):
    reso = span_deg * 60.0 / xs
    proj = hpproj.GnomonicProj(rot=(ra, dec, 0), xsize=xs, ysize=xs, reso=reso)
    v2p = lambda x, y, z: hp.vec2pix(NS, x, y, z, nest=True)
    dv = np.array(proj.projmap(dev, v2p))
    ridx = np.array(proj.projmap(regcol_idx.astype(np.float64), v2p)).astype(np.int64)
    g = np.clip((dv + 6.0) / 12.0, 0, 1)
    im1 = np.stack([g, g, g], -1)
    im2 = cmap[np.clip(ridx, 0, len(uc) - 1)]
    edge = np.zeros(ridx.shape, bool)
    edge[:-1, :] |= ridx[:-1, :] != ridx[1:, :]
    edge[:, :-1] |= ridx[:, :-1] != ridx[:, 1:]
    im3 = im1.copy(); im3[edge] = [1.0, 0.3, 0.0]
    canvas = np.concatenate([im1, np.ones((xs, 6, 3)), im3, np.ones((xs, 6, 3)), im2], axis=1)
    Image.fromarray((canvas[::-1] * 255).astype(np.uint8)).save(SC + "/diag7/%s_dev.png" % name)
    print("rendered", name, flush=True)

# ---- banded medians vs hop distance for dominant seams around a site ----
NB8 = hp.get_all_neighbours  # (8,N)
def seam_table(name, ra, dec, rad=3.0, topn=6):
    pix = hp.query_disc(NS, hp.ang2vec(ra, dec, lonlat=True), np.radians(rad), nest=True)
    inset = np.zeros(NPIX, bool); inset[pix] = True
    nb = NB8(NS, pix, nest=True)  # (8,npx)
    lc = comb[pix]
    pairs = {}
    for k in range(8):
        q = nb[k]
        ok = (q >= 0) & inset[np.clip(q, 0, NPIX - 1)]
        a = lc[ok]; b = comb[q[ok]]
        m = a != b
        for x, y in zip(a[m], b[m]):
            key = (min(int(x), int(y)), max(int(x), int(y)))
            pairs[key] = pairs.get(key, 0) + 1
    top = sorted(pairs.items(), key=lambda kv: -kv[1])[:topn]
    print("\n=== %s (%.1f,%.1f) top seams ===" % (name, ra, dec), flush=True)
    for (la, lb), cnt in top:
        # hop distance from this seam within each region (BFS depth<=14)
        for lab, other in ((la, lb), (lb, la)):
            mreg = inset & (comb == lab)
            regpix = np.where(mreg)[0]
            depth = np.full(NPIX, -1, np.int16)
            # frontier: region pixels adjacent to `other`
            nbr = NB8(NS, regpix, nest=True)
            front = []
            for k in range(8):
                q = nbr[k]
                okq = (q >= 0)
                hit = np.zeros(len(regpix), bool)
                hit[okq] = comb[q[okq]] == other
                front.append(hit)
            f0 = np.any(np.stack(front), 0)
            cur = regpix[f0]
            depth[cur] = 0
            for d in range(1, 14):
                nbq = NB8(NS, cur, nest=True).ravel()
                nbq = nbq[nbq >= 0]
                nxt = nbq[(depth[nbq] < 0) & mreg[nbq]]
                if len(nxt) == 0: break
                nxt = np.unique(nxt)
                depth[nxt] = d
                cur = nxt
            meds = []
            for d in range(14):
                sel = depth[regpix] == d
                meds.append(np.median(dev[regpix[sel]]) if sel.sum() >= 8 else np.nan)
            print("  seam(%d|%d) len=%4d side %-7d dev(d0..13): %s" %
                  (la, lb, cnt, lab, " ".join("%5.1f" % v if np.isfinite(v) else "   . " for v in meds)),
                  flush=True)

os.makedirs(SC + "/diag7", exist_ok=True)
render("crux_musca", 187.0, -64.5, 14.0)
render("regor", 122.4, -47.3, 9.0)
render("t1252", 354.4, 17.0, 7.0)
render("t1219", 0.0, 7.2, 7.0)
seam_table("t1219", 0.0, 7.2)
seam_table("t1252", 354.4, 17.0)
seam_table("regor", 122.4, -47.3)
print("DONE")
