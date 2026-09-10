"""Integrated single-quantization rebuild from git HEAD:
  smooth chain (guided colour + lum + regions + membrane + darkdc1/2 + restore + v4resid)
+ SHARP luminance region constants (v4, combined tessellation)
+ SHARP per-channel chroma constants (v5: R on red tessellation, B on blue/GAP, G=mix)
+ round-symmetric bright-star halo fills (halo_plan.npy)
All sharp terms rendered at quarter-tile resolution with exact GetImage winners.
Usage: python apply_sharp2.py [apply|preview]
"""
import numpy as np, cv2, os, subprocess, tempfile, sys, glob, time
sys.path.insert(0, "tools")
from clean_dss.background import upsample_smooth
from clean_dss.pyramid import child_ids, rebuild_parent
import healpy as hp

SC = os.environ["SCRATCH"]
sys.path.insert(0, SC)
from gsss_winner import load_channel, sky_to_pixel

W = 512; NST = 16; QR = 4
MODE = sys.argv[1] if len(sys.argv) > 1 else "apply"

d = np.load(SC + "/delta512.npz"); dL0 = np.load(SC + "/dLum512.npy")
dreg = np.load(SC + "/delta_regions_final.npz"); dm = np.load(SC + "/delta_membrane.npz")
base = np.load(SC + "/dDarkDC.npy") + np.load(SC + "/dDarkDC2.npy")
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
resid6 = np.load(SC + "/dDark6_resid.npy")
dbR = np.load(SC + "/dband7_R.npy"); dbG = np.load(SC + "/dband7_G.npy")
dbB = np.load(SC + "/dband7_B.npy")
FR = (d['dR'] + dL0 + dreg['dR'] + dm['dR'] + base + drest['dR'] + resid4 + resid6 + dbR).astype(np.float32)
FG = (d['dG'] + dL0 + dreg['dG'] + dm['dG'] + base + drest['dG'] + resid4 + resid6 + dbG).astype(np.float32)
FB = (d['dB'] + dL0 + dreg['dB'] + dm['dB'] + base + drest['dB'] + resid4 + resid6 + dbB).astype(np.float32)

sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
c5 = np.load(SC + "/dc5_chroma.npz")
uR5, cR5, uB5, cB5 = c5['uR'], c5['cR'], c5['uB'], c5['cB']
sh6 = np.load(SC + "/dc6_sharp.npz")
U6, CREG6 = sh6['region_ids'], sh6['c_reg']
c6 = np.load(SC + "/dc6_chroma.npz")
uR6, cR6, uB6, cB6 = c6['uR'], c6['cR'], c6['uB'], c6['cB']
sh7 = np.load(SC + "/dc7_sharp.npz")
U7, CREG7 = sh7['region_ids'], sh7['c_reg']
c7 = np.load(SC + "/dc7_chroma.npz")
uR7, cR7, uB7, cB7 = c7['uR'], c7['cR'], c7['uB'], c7['cB']
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
wr_c = wrz['winner'].astype(np.int64); wb_c = wbz['winner'].astype(np.int64)
comb_c = wr_c * BMAX + (wb_c + 1)
labr_c = wr_c.copy(); labr_c[labr_c < 0] = 19000
labbe_c = np.where(wb_c < 0, labr_c + 20000, wb_c)

def lut(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

cl_coarse = lut(U0, CREG, comb_c) + lut(U6, CREG6, comb_c) + lut(U7, CREG7, comb_c)
cr_coarse = lut(uR5, cR5, labr_c) + lut(uR6, cR6, labr_c) + lut(uR7, cR7, labr_c)
cb_coarse = lut(uB5, cB5, labbe_c) + lut(uB6, cB6, labbe_c) + lut(uB7, cB7, labbe_c)

plans = np.load(SC + "/halo_plan.npy", allow_pickle=True).item()
halo_tiles = {}
for name, pl in plans.items():
    v0 = hp.ang2vec(pl['ra'], pl['dec'], lonlat=True)
    for t in hp.query_disc(NST, v0, np.radians(pl['Rh'] + 0.3), nest=True, inclusive=True):
        halo_tiles.setdefault(int(t), []).append(name)

print("parsing GSSS headers...", flush=True)
hdr = None
for cand in [os.path.join(SC, 'getimage/hdrs/DSSHeaders'), os.path.join(SC, 'getimage/DSSHeaders')]:
    if os.path.isdir(cand): hdr = cand; break
plates_r = load_channel(hdr, ['XP', 'XS', 'ER', 'GR'])
plates_b = load_channel(hdr, ['XJ', 'S'])
vec_r = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_r])
vec_b = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_b])
COSR = np.cos(np.radians(7.8))
print("red %d blue %d plates, halo tiles %d" % (len(plates_r), len(plates_b), len(halo_tiles)), flush=True)

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

def sharp_planes(npix):
    """Returns (3,W,W) float32 [B,G,R] additive plane, or a (3,) constant vector."""
    cells = npix * 1024 + cellsub
    clv = cl_coarse[cells]; crv = cr_coarse[cells]; cbv = cb_coarse[cells]
    uniform = (np.ptp(clv) < 1e-6) and (np.ptp(crv) < 1e-6) and (np.ptp(cbv) < 1e-6)
    jobs = halo_tiles.get(npix, [])
    if uniform and not jobs:
        cl, cr, cb = float(clv[0]), float(crv[0]), float(cbv[0])
        return np.array([cl + cb, cl + 0.5 * (cr + cb), cl + cr], np.float32)
    nest = npix * (W * W) + qsub
    th, ph = hp.pix2ang(NST * W, nest, nest=True)
    ra = np.degrees(ph); dec = 90.0 - np.degrees(th)
    pv = np.array(hp.ang2vec(ra, dec, lonlat=True))
    mv = pv.mean(0)
    wr_ = winner_at(mv, ra, dec, plates_r, vec_r)
    wb_ = winner_at(mv, ra, dec, plates_b, vec_b)
    combq = wr_ * BMAX + (wb_ + 1)
    labrq = np.where(wr_ < 0, 19000, wr_)
    labbq = np.where(wb_ < 0, labrq + 20000, wb_)
    cl = lut(U0, CREG, combq) + lut(U6, CREG6, combq) + lut(U7, CREG7, combq)
    cr = lut(uR5, cR5, labrq) + lut(uR6, cR6, labrq) + lut(uR7, cR7, labrq)
    cb = lut(uB5, cB5, labbq) + lut(uB6, cB6, labbq) + lut(uB7, cB7, labbq)
    addR = cl + cr; addG = cl + 0.5 * (cr + cb); addB = cl + cb
    for name in jobs:
        pl = plans[name]
        v0 = np.array(hp.ang2vec(pl['ra'], pl['dec'], lonlat=True))
        r = np.degrees(np.arccos(np.clip(pv @ v0, -1, 1)))
        for irow, rg in enumerate(pl['ids']):
            m = (combq == rg) & (r < pl['Rh'])
            if not m.any(): continue
            D = pl['D'][irow]
            addR[m] += np.interp(r[m], pl['rmid'], D[0])
            addG[m] += np.interp(r[m], pl['rmid'], D[1])
            addB[m] += np.interp(r[m], pl['rmid'], D[2])
    out = []
    for a in (addB, addG, addR):
        pl2 = cv2.resize(a.reshape(W // QR, W // QR), (W, W), interpolation=cv2.INTER_LINEAR)
        out.append(cv2.GaussianBlur(pl2, (0, 0), 1.5))
    return np.stack(out)

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
    sp = sharp_planes(npix)
    tot = up + (sp[None, None, :] if sp.ndim == 1 else np.moveaxis(sp, 0, 2))
    return np.rint(np.clip(head + tot, 0, 255)).astype(np.uint8)

if MODE == "preview":
    from scipy.spatial import cKDTree
    OUT = "apps/skymap-web/public/plate-eq-review"
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
    for tag, r0, d0, half in [("regor", 122.4, -47.3, 4.5), ("t1252", 354.4, 17.0, 3.5),
                              ("t1219", 0.0, 7.2, 3.5), ("cruxStrips", 187.0, -65.0, 5.0),
                              ("araNGC6193", 250.3, -48.8, 5.0), ("galcenter6", 266.0, -29.0, 6.0)]:
        vec = hp.ang2vec(r0, d0, lonlat=True)
        tiles = hp.query_disc(NST, vec, np.radians(half * 1.5 + 3), nest=True, inclusive=True)
        XI = []; ETA = []; BEF = []; AFT = []
        for t in tiles:
            t = int(t)
            bimg = cv2.imread(n4path(t))
            aimg = new_tile(t)
            if bimg is None or aimg is None: continue
            X, Y, ra, dec = subpix_sky(t)
            xi, eta = gno(ra, dec, r0, d0)
            sel = (np.abs(xi) < half) & (np.abs(eta) < half)
            if not sel.any(): continue
            X, Y = X[sel], Y[sel]
            BEF.append(bimg.astype(np.float32)[Y, X]); AFT.append(aimg.astype(np.float32)[Y, X])
            XI.append(xi[sel]); ETA.append(eta[sel])
        XI = np.concatenate(XI); ETA = np.concatenate(ETA)
        BEF = np.concatenate(BEF); AFT = np.concatenate(AFT)
        N = int(2 * half * 70)
        GX, GY = np.meshgrid(np.linspace(-half, half, N), np.linspace(half, -half, N))
        qi = cKDTree(np.stack([XI, ETA], 1)).query(np.stack([GX.ravel(), GY.ravel()], 1))[1]
        bv = np.clip(BEF[qi], 0, 255) / 255.0
        aa, bb = np.percentile(bv, 2), np.percentile(bv, 92)
        b_ = stretch(BEF[qi].reshape(N, N, 3), aa, bb); a_ = stretch(AFT[qi].reshape(N, N, 3), aa, bb)
        cv2.putText(b_, "current tiles", (8, 22), 0, 0.6, (0, 0, 255), 2)
        cv2.putText(a_, "rebuilt (v7 bands+graph)", (8, 22), 0, 0.6, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(OUT, "final_%s.png" % tag),
                    np.hstack([b_, np.full((N, 10, 3), 60, np.uint8), a_]))
        print(tag, "done", flush=True)
    print("PREVIEW DONE", flush=True)
    sys.exit(0)

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
