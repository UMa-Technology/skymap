"""Sharp per-region application of the v4 leveling.

Total per-tile delta = upsample(smooth chain incl. delta_restore + dDark4_resid)
                     + SHARP term: c_reg[combined region of each tile pixel],
where the combined region is evaluated at quarter tile resolution (0.8' placement)
with the exact GetImage FURTHEST_FROM_EDGE rule, then nearest-upsampled x4 and the
correction plane blurred sigma=1.5 px (matches HiPS seam softness).

Modes:
  preview  — render before/after PNGs at benchmark spots (tiles untouched)
  apply    — full single-quantization rebuild from git HEAD (all N4+N3+mono)
"""
import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0, "tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
import healpy as hp

SC = os.environ["SCRATCH"]
sys.path.insert(0, SC)
from gsss_winner import load_channel, sky_to_pixel

W = 512; NST = 16; QR = 4          # quarter-res winner evaluation
MODE = sys.argv[1] if len(sys.argv) > 1 else "preview"

d = np.load(SC + "/delta512.npz"); dL0 = np.load(SC + "/dLum512.npy")
dreg = np.load(SC + "/delta_regions_final.npz"); dm = np.load(SC + "/delta_membrane.npz")
base = np.load(SC + "/dDarkDC.npy") + np.load(SC + "/dDarkDC2.npy")
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
FR = (d['dR'] + dL0 + dreg['dR'] + dm['dR'] + base + drest['dR'] + resid4).astype(np.float32)
FG = (d['dG'] + dL0 + dreg['dG'] + dm['dG'] + base + drest['dG'] + resid4).astype(np.float32)
FB = (d['dB'] + dL0 + dreg['dB'] + dm['dB'] + base + drest['dB'] + resid4).astype(np.float32)

sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb_coarse = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
cval_coarse = np.zeros(len(comb_coarse), np.float32)
ii = np.searchsorted(U0, comb_coarse)
ok = (ii < len(U0)) & (U0[np.clip(ii, 0, len(U0) - 1)] == comb_coarse)
cval_coarse[ok] = CREG[ii[ok]]

print("parsing GSSS headers...", flush=True)
hdr = None
for cand in [os.path.join(SC, 'getimage/hdrs/DSSHeaders'), os.path.join(SC, 'getimage/DSSHeaders')]:
    if os.path.isdir(cand): hdr = cand; break
plates_r = load_channel(hdr, ['XP', 'XS', 'ER', 'GR'])
plates_b = load_channel(hdr, ['XJ', 'S'])
print("red %d blue %d plates" % (len(plates_r), len(plates_b)), flush=True)
vec_r = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_r])
vec_b = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_b])
COSR = np.cos(np.radians(5.0 + 2.8))

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
cy, cx = np.meshgrid(np.arange(32), np.arange(32), indexing='ij')
cellsub = (p1(cy) | (p1(cx) << 1)).ravel()
qx = np.arange(0, W, QR); QX, QY = np.meshgrid(qx, qx)
qsub = (p1(QY.ravel()) | (p1(QX.ravel()) << 1))

def winner_at(pts_vec, ra, dec, plates, vecs):
    cand = np.where(vecs @ pts_vec.mean(0) > COSR)[0]
    best = np.full(len(ra), -1e9); win = np.full(len(ra), -1, np.int64)
    for ci in cand:
        pl = plates[ci]
        x, y = sky_to_pixel(pl, ra, dec)
        m = np.minimum.reduce([x, y, pl['nx'] - x, pl['ny'] - y])
        upd = (m > 0) & (m > best)
        best[upd] = m[upd]; win[upd] = ci
    return win

def sharp_plane(npix):
    """(W,W) float32 sharp correction for tile npix, or scalar if uniform."""
    cells = cval_coarse[npix * 1024 + cellsub]
    if np.all(np.abs(cells - cells[0]) < 1e-6):
        return float(cells[0])
    nest = npix * (W * W) + qsub
    ra, dec = hp.pix2ang(NST * W, nest, nest=True, lonlat=True)
    pv = np.array(hp.ang2vec(ra, dec, lonlat=True))
    wr_ = winner_at(pv, ra, dec, plates_r, vec_r)
    wb_ = winner_at(pv, ra, dec, plates_b, vec_b)
    combq = wr_ * BMAX + (wb_ + 1)
    cq = np.zeros(len(combq), np.float32)
    jj = np.searchsorted(U0, combq)
    okq = (jj < len(U0)) & (U0[np.clip(jj, 0, len(U0) - 1)] == combq)
    cq[okq] = CREG[jj[okq]]
    plane = cv2.resize(cq.reshape(W // QR, W // QR), (W, W), interpolation=cv2.INTER_NEAREST)
    return cv2.GaussianBlur(plane, (0, 0), 1.5)

SRC = "apps/skydata/surveys/dss"; DSTM = "apps/skydata/surveys/dss-mono"
def n4path(npix): return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
def n3path(npix): return os.path.join(SRC, "Norder3", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

def save_lossless(bgr, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        cv2.imwrite(tf.name, bgr); s = tf.name
    try:
        r = subprocess.run(["cwebp", "-quiet", "-lossless", "-m", "6", "-o", dst, s], capture_output=True)
        if r.returncode != 0: raise RuntimeError(r.stderr.decode()[:200])
    finally:
        os.unlink(s)

def new_tile(npix):
    r = subprocess.run(["git", "show", "HEAD:" + n4path(npix)], capture_output=True)
    if r.returncode != 0: return None
    head = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR).astype(np.float32)
    b_i = npix * 1024
    up = np.stack([upsample_smooth(F[b_i + cellsub].reshape(32, 32), W) for F in (FB, FG, FR)], 2)
    sp = sharp_plane(npix)
    tot = up + (sp if np.isscalar(sp) else sp[..., None])
    return np.rint(np.clip(head + tot, 0, 255)).astype(np.uint8)

if MODE == "preview":
    from scipy.spatial import cKDTree
    OUT = "apps/web-frontend/public/plate-eq-review"
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
    for tag, r0, d0, half in [("crux", 187.0, -61.5, 7), ("musca", 188.0, -64.0, 6),
                              ("galcenter", 266.0, -29.0, 7), ("pipe", 262.0, -25.0, 6),
                              ("M7", 268.5, -34.8, 5)]:
        vec = hp.ang2vec(r0, d0, lonlat=True)
        tiles = hp.query_disc(NST, vec, np.radians(half * 1.5 + 3), nest=True, inclusive=True)
        XI = []; ETA = []; BEF = []; AFT = []
        for t in tiles:
            t = int(t)
            bimg = cv2.imread(n4path(t))
            if bimg is None: continue
            aimg = new_tile(t)
            X, Y, ra, dec = subpix_sky(t)
            xi, eta = gno(ra, dec, r0, d0)
            sel = (np.abs(xi) < half) & (np.abs(eta) < half)
            if not sel.any(): continue
            X, Y = X[sel], Y[sel]
            BEF.append(bimg.astype(np.float32)[Y, X]); AFT.append(aimg.astype(np.float32)[Y, X])
            XI.append(xi[sel]); ETA.append(eta[sel])
        XI = np.concatenate(XI); ETA = np.concatenate(ETA)
        BEF = np.concatenate(BEF); AFT = np.concatenate(AFT)
        N = int(2 * half * 42)
        GX, GY = np.meshgrid(np.linspace(-half, half, N), np.linspace(half, -half, N))
        qi = cKDTree(np.stack([XI, ETA], 1)).query(np.stack([GX.ravel(), GY.ravel()], 1))[1]
        bv = np.clip(BEF[qi], 0, 255) / 255.0
        aa, bb = np.percentile(bv, 2), np.percentile(bv, 92)
        b_ = stretch(BEF[qi].reshape(N, N, 3), aa, bb); a_ = stretch(AFT[qi].reshape(N, N, 3), aa, bb)
        cv2.putText(b_, "before", (8, 22), 0, 0.6, (0, 0, 255), 2)
        cv2.putText(a_, "+ sharp v4", (8, 22), 0, 0.6, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(OUT, "sharp4_%s.png" % tag),
                    np.hstack([b_, np.full((N, 10, 3), 60, np.uint8), a_]))
        print(tag, "done", flush=True)
    print("PREVIEW DONE", flush=True)
    sys.exit(0)

# ---- apply mode: full rebuild ----
t0 = time.time(); n = 0
for npix in range(3072):
    img = new_tile(npix)
    if img is None: print("NO HEAD", npix, flush=True); continue
    save_lossless(img, n4path(npix)); n += 1
    if n % 300 == 0: print("N4", n, int(time.time() - t0), "s", flush=True)
print("PASS1 N4:", n, flush=True)
for parent in range(768):
    ch = [cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch), n3path(parent))
print("PASS2 N3: 768", flush=True)
nm = 0
for f in sorted(glob.glob(os.path.join(SRC, "Norder4", "Dir*", "Npix*.webp"))):
    img = cv2.imread(f)
    if img is None: continue
    L = (0.114 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.299 * img[:, :, 2]).astype(np.float32)
    mono = np.repeat(np.rint(np.clip(L, 0, 255)).astype(np.uint8)[:, :, None], 3, axis=2)
    save_lossless(mono, f.replace(SRC, DSTM)); nm += 1
    if nm % 600 == 0: print("monoN4", nm, flush=True)
def m4path(npix): return os.path.join(DSTM, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
for f in sorted(glob.glob(os.path.join(SRC, "Norder3", "Dir*", "Npix*.webp"))):
    parent = int(os.path.basename(f)[4:-5])
    ch = [cv2.imread(m4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch), f.replace(SRC, DSTM))
print("DONE %ds N4=%d mono=%d" % (time.time() - t0, n, nm), flush=True)
