"""Full-res A/B renders: current on-disk tiles (post quantization-repair) vs
tiles + SeamNet correction (dSeam.npz applied on the fly). Writes to plate-eq-review/."""
import numpy as np, healpy as hp, cv2, os, sys
sys.path.insert(0, "tools")
from clean_dss.background import upsample_smooth
from scipy.spatial import cKDTree

SC = os.environ["SCRATCH"]; W = 512; NST = 16
OUT = "apps/web-frontend/public/plate-eq-review"
FIELD = sys.argv[1] if len(sys.argv) > 1 else SC + "/seamnet/dSeam.npz"
TAGPFX = sys.argv[2] if len(sys.argv) > 2 else "seamnet"
d = np.load(FIELD)
dR, dG, dB = d['dR'], d['dG'], d['dB']

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()
BASE = "apps/skydata/surveys/dss/Norder4"

def tile_pair(npix):
    f = os.path.join(BASE, f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
    img = cv2.imread(f)
    if img is None: return None, None
    b = npix * 1024
    delta = np.stack([upsample_smooth(dB[b + cellsub].reshape(32, 32), W),
                      upsample_smooth(dG[b + cellsub].reshape(32, 32), W),
                      upsample_smooth(dR[b + cellsub].reshape(32, 32), W)], 2)
    after = np.clip(img.astype(np.float32) + delta, 0, 255)
    return img.astype(np.float32), after

def subpix_sky(npix, step=2):
    xs = np.arange(0, W, step); X, Y = np.meshgrid(xs, xs)
    sub = (p1(Y.ravel()) | (p1(X.ravel()) << 1)); nest = npix * (W * W) + sub
    ra, dec = hp.pix2ang(NST * W, nest, nest=True, lonlat=True)
    return X.ravel(), Y.ravel(), ra, dec

def gno(r, de, r0, d0):
    r = np.radians(r); de = np.radians(de); rr = np.radians(r0); dd = np.radians(d0)
    cosc = np.sin(dd) * np.sin(de) + np.cos(dd) * np.cos(de) * np.cos(r - rr)
    return (np.degrees(np.cos(de) * np.sin(r - rr) / cosc),
            np.degrees((np.cos(dd) * np.sin(de) - np.sin(dd) * np.cos(de) * np.cos(r - rr)) / cosc))

def stretch(rgb, a, b):
    v = np.clip(rgb, 0, 255) / 255.0
    return (np.clip((v - a) / max(b - a, 1e-3), 0, 1) ** 0.6 * 255).astype(np.uint8)

def render(tag, r0, d0, half, px=42):
    vec = hp.ang2vec(r0, d0, lonlat=True)
    tiles = hp.query_disc(NST, vec, np.radians(half * 1.5 + 3), nest=True, inclusive=True)
    XI = []; ETA = []; BEF = []; AFT = []
    for t in tiles:
        bimg, aimg = tile_pair(int(t))
        if bimg is None: continue
        X, Y, ra, dec = subpix_sky(int(t))
        xi, eta = gno(ra, dec, r0, d0)
        sel = (np.abs(xi) < half) & (np.abs(eta) < half)
        if not sel.any(): continue
        X, Y = X[sel], Y[sel]
        BEF.append(bimg[Y, X]); AFT.append(aimg[Y, X])
        XI.append(xi[sel]); ETA.append(eta[sel])
    XI = np.concatenate(XI); ETA = np.concatenate(ETA)
    BEF = np.concatenate(BEF); AFT = np.concatenate(AFT)
    N = int(2 * half * px)
    GX, GY = np.meshgrid(np.linspace(-half, half, N), np.linspace(half, -half, N))
    qi = cKDTree(np.stack([XI, ETA], 1)).query(np.stack([GX.ravel(), GY.ravel()], 1))[1]
    bv = np.clip(BEF[qi], 0, 255) / 255.0
    a_, b_ = np.percentile(bv, 2), np.percentile(bv, 92)   # same stretch both sides
    bimg = stretch(BEF[qi].reshape(N, N, 3), a_, b_)
    aimg = stretch(AFT[qi].reshape(N, N, 3), a_, b_)
    cv2.putText(bimg, "before (tiles)", (8, 22), 0, 0.6, (0, 0, 255), 2)
    cv2.putText(aimg, "+ " + TAGPFX, (8, 22), 0, 0.6, (0, 0, 255), 2)
    cv2.imwrite(os.path.join(OUT, "%s_%s.png" % (TAGPFX, tag)),
                np.hstack([bimg, np.full((N, 10, 3), 60, np.uint8), aimg]))
    print(tag, "done", flush=True)

SPOTS = [("musca", 188.0, -62.0, 7), ("galcenter", 266.0, -29.0, 7),
         ("pipe", 262.0, -25.0, 6), ("cygnus", 305.0, 38.0, 7),
         ("ara", 252.0, -50.0, 7), ("M7", 268.5, -34.8, 5),
         ("NGC6633", 276.9, 6.6, 5), ("M25", 277.9, -19.1, 5)]
for tag, r0, d0, h in SPOTS:
    render(tag, r0, d0, h)
print("ALL DONE")
