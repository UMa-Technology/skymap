"""Radial clone-stamp v2 for bright-star halos cut by plate boundaries.

Per star: per-region radial profiles H_k(r) (vs each region's own outer background).
For every adjacent region PAIR (k deficient vs j) the glow deficit D(r)=H_j-H_k>0 is
stamped onto k's pixels ONLY near the k|j boundary, with weight exp(-d/lambda)
(d = distance to that boundary) — so the glow continues smoothly across the cut and
decays back to k's own level away from it (dark nebulae far from the seam untouched).
Add-only, per channel, tapered to zero at the halo edge, exact plate geometry.

Usage: python halo_blend.py scan | apply   (run from repo root, SCRATCH env set)
"""
import numpy as np, cv2, os, subprocess, tempfile, sys, time
import healpy as hp
sys.path.insert(0, "tools")
from clean_dss.pyramid import child_ids, rebuild_parent
SC = os.environ["SCRATCH"]
sys.path.insert(0, SC)
from gsss_winner import load_channel, sky_to_pixel
from seamnet_common import load_state

W = 512; NST = 16; NS = 512; QR = 4
MODE = sys.argv[1] if len(sys.argv) > 1 else "scan"

STARS = [
 ("Sirius",101.2875,-16.7161),("Canopus",95.9880,-52.6957),("RigilKent",219.9021,-60.8340),
 ("Arcturus",213.9153,19.1824),("Vega",279.2347,38.7837),("Capella",79.1723,45.9980),
 ("Rigel",78.6345,-8.2016),("Procyon",114.8255,5.2250),("Achernar",24.4285,-57.2368),
 ("Betelgeuse",88.7929,7.4071),("Hadar",210.9559,-60.3730),("Altair",297.6958,8.8683),
 ("Acrux",186.6496,-63.0991),("Aldebaran",68.9802,16.5093),("Antares",247.3519,-26.4320),
 ("Spica",201.2983,-11.1613),("Pollux",116.3289,28.0262),("Fomalhaut",344.4127,-29.6222),
 ("Deneb",310.3580,45.2803),("Mimosa",191.9303,-59.6888),("Regulus",152.0929,11.9672),
 ("Adhara",104.6564,-28.9721),("Shaula",263.4022,-37.1038),("Castor",113.6494,31.8883),
 ("Gacrux",187.7915,-57.1133),("Bellatrix",81.2828,6.3497),("Elnath",81.5730,28.6075),
 ("Miaplacidus",138.3000,-69.7172),("Alnilam",84.0534,-1.2019),("Alnair",332.0582,-46.9610),
 ("Alnitak",85.1897,-1.9426),("Mirfak",51.0807,49.8612),("Wezen",107.0979,-26.3932),
 ("Sargas",264.3297,-42.9978),("KausAustralis",276.0430,-34.3846),("Avior",125.6285,-59.5095),
 ("Menkalinan",89.8822,44.9474),("Atria",252.1662,-69.0277),("Alhena",99.4276,16.3993),
 ("Peacock",306.4119,-56.7351),("DeltaVel",131.1760,-54.7088),("Mirzam",95.6749,-17.9559),
 ("Alphard",141.8968,-8.6586),("Polaris",37.9546,89.2641),("Diphda",10.8974,-17.9866)]

RBINS = np.geomspace(0.03, 2.2, 36)
RMID = np.sqrt(RBINS[:-1] * RBINS[1:])
NB = len(RMID)
DCAP = 20.0

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb_coarse = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
cshr = np.zeros(len(comb_coarse), np.float32)
ii = np.searchsorted(U0, comb_coarse)
ok = (ii < len(U0)) & (U0[np.clip(ii, 0, len(U0) - 1)] == comb_coarse)
cshr[ok] = CREG[ii[ok]]
lumadd = drest['dR'] + resid4 + cshr
CUR = {'R': R + lumadd, 'G': G + lumadd, 'B': B + lumadd}
LC = 0.299 * CUR['R'] + 0.587 * CUR['G'] + 0.114 * CUR['B']
NEIGH = None  # lazy global neighbour table

def star_plan(ra0, dec0):
    global NEIGH
    v0 = np.array(hp.ang2vec(ra0, dec0, lonlat=True))
    pix = hp.query_disc(NS, v0, np.radians(2.2), nest=True)
    vv = np.array(hp.pix2vec(NS, pix, nest=True)).T
    r = np.degrees(np.arccos(np.clip(vv @ v0, -1, 1)))
    reg = comb_coarse[pix]
    binid = np.digitize(r, RBINS) - 1
    inb = (binid >= 0) & (binid < NB)
    prof = {}
    for rg in np.unique(reg):
        m = (reg == rg) & inb
        if m.sum() < 20: continue
        P = np.full((3, NB), np.nan)
        for kb in np.unique(binid[m]):
            mb = m & (binid == kb)
            if mb.sum() < 6: continue
            for ci, ch in enumerate('RGB'):
                P[ci, kb] = np.median(CUR[ch][pix[mb]])
        Bo = np.nanmedian(P[:, RMID > 1.6], axis=1)
        if np.any(np.isnan(Bo)):
            Bo = np.nanmedian(P[:, RMID > 1.2], axis=1)
        if np.any(np.isnan(Bo)): continue
        prof[int(rg)] = P - Bo[:, None]          # halo component per channel
    if len(prof) < 2: return None
    HL = {rg: np.nan_to_num(0.299 * H[0] + 0.587 * H[1] + 0.114 * H[2], nan=0.0)
          for rg, H in prof.items()}
    env = np.max(np.stack(list(HL.values())), axis=0)
    sig = np.where(env > 0.75)[0]
    if len(sig) < 3: return None
    Rh = min(float(RBINS[min(sig.max() + 2, NB)]), 2.0)
    # azimuthal symmetry of the brightest contributor (nebular-field guard)
    kmax = max(HL, key=lambda k: HL[k].max())
    gm = (reg == kmax) & inb & (r > 0.15)
    syms = []
    for kb in np.unique(binid[gm]):
        if HL[kmax][kb] < 1.0: continue
        mb = gm & (binid == kb)
        if mb.sum() < 8: continue
        v = LC[pix[mb]]
        syms.append(np.median(np.abs(v - np.median(v))) / max(HL[kmax][kb], 1.0))
    sym = float(np.median(syms)) if len(syms) >= 3 else -1.0
    if sym > 1.05: return dict(rej=sym)
    if sym > 0.7 or sym < 0:                      # mixed field: strong-core only
        sig2 = np.where(env > 2.0)[0]
        if len(sig2) < 2: return dict(rej=sym)
        Rh = min(Rh, float(RBINS[min(sig2.max() + 2, NB)]))
    lam = max(0.3 * Rh, 0.18)
    if NEIGH is None:
        NEIGH = hp.get_all_neighbours(NS, np.arange(hp.nside2npix(NS)), nest=True).T
    rl = np.full(hp.nside2npix(NS), -9, np.int64)
    rl[pix] = reg
    nb = NEIGH[pix]
    adj = set()
    for kk in range(8):
        q = nb[:, kk]
        okq = q >= 0
        a = reg[okq]; bq = rl[q[okq]]
        m2 = (bq != -9) & (bq != a)
        for x, yq in zip(a[m2], bq[m2]):
            adj.add((int(x), int(yq)))
    pairs = []
    for k in prof:
        for j in prof:
            if k == j or (k, j) not in adj: continue
            D = np.zeros((3, NB), np.float32)
            for ci in range(3):
                d = np.nan_to_num(prof[j][ci] - prof[k][ci], nan=0.0)
                d = np.clip(d, 0, DCAP)
                d[RMID > Rh] = 0.0
                d = np.maximum.accumulate(d[::-1])[::-1]
                d = d * np.clip((Rh - RMID) / 0.15, 0, 1)
                D[ci] = np.convolve(d, np.ones(3) / 3, mode='same')
            dl = 0.299 * D[0] + 0.587 * D[1] + 0.114 * D[2]
            if (dl > 1.0).sum() >= 2:
                pairs.append((k, j, D))
    if not pairs: return None
    return dict(Rh=Rh, lam=lam, sym=sym, pairs=pairs, pix=pix, reg=reg)

def pair_weight_map(pix, reg, k, j, lam):
    """exp(-d/lam) on region-k pixels, d = BFS distance (deg) to the k|j boundary."""
    rl = np.full(hp.nside2npix(NS), -9, np.int64)
    rl[pix] = reg
    ink = pix[reg == k]
    nbk = NEIGH[ink]
    isb = np.zeros(len(ink), bool)
    for kk in range(8):
        q = nbk[:, kk]
        isb |= (q >= 0) & (rl[q] == j)
    depth = np.full(hp.nside2npix(NS), 1e9, np.float32)
    frontier = ink[isb]
    depth[frontier] = 0
    for dstep in range(1, 14):
        nb2 = NEIGH[frontier].ravel()
        nb2 = nb2[nb2 >= 0]
        nb2 = nb2[(rl[nb2] == k) & (depth[nb2] > 1e8)]
        if len(nb2) == 0: break
        nb2 = np.unique(nb2)
        depth[nb2] = dstep
        frontier = nb2
    w = np.zeros(hp.nside2npix(NS), np.float32)
    mk = depth < 1e8
    w[mk] = np.exp(-depth[mk] * 0.115 / lam)
    return w

print("scanning bright stars...", flush=True)
plans = {}
for name, ra0, dec0 in STARS:
    pl = star_plan(ra0, dec0)
    if pl and 'rej' in pl:
        print("  %-14s REJECTED (sym %.2f nebular)" % (name, pl['rej']), flush=True)
    elif pl:
        mx = max(float((0.299*D[0]+0.587*D[1]+0.114*D[2]).max()) for _, _, D in pl['pairs'])
        print("  %-14s Rh %.2f lam %.2f sym %.2f pairs %d max-add %.1f DN" %
              (name, pl['Rh'], pl['lam'], pl['sym'], len(pl['pairs']), mx), flush=True)
        plans[name] = (ra0, dec0, pl)
print("stars to blend: %d" % len(plans), flush=True)
if MODE == "scan":
    sys.exit(0)

# ---------------- apply ----------------
print("building boundary weight maps...", flush=True)
for name, (ra0, dec0, pl) in plans.items():
    pl['wmaps'] = {(k, j): pair_weight_map(pl['pix'], pl['reg'], k, j, pl['lam'])
                   for k, j, _ in pl['pairs']}

print("parsing GSSS headers...", flush=True)
hdr = None
for cand in [os.path.join(SC, 'getimage/hdrs/DSSHeaders'), os.path.join(SC, 'getimage/DSSHeaders')]:
    if os.path.isdir(cand): hdr = cand; break
plates_r = load_channel(hdr, ['XP', 'XS', 'ER', 'GR'])
plates_b = load_channel(hdr, ['XJ', 'S'])
vec_r = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_r])
vec_b = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in plates_b])
COSR = np.cos(np.radians(7.8))

def p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n
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

SRC = "apps/skydata/surveys/dss"; DSTM = "apps/skydata/surveys/dss-mono"
def n4path(npix): return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
def n3path(npix): return os.path.join(SRC, "Norder3", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")
def save_lossless(bgr, dst):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        cv2.imwrite(tf.name, bgr); s = tf.name
    try:
        rr = subprocess.run(["cwebp", "-quiet", "-lossless", "-m", "6", "-o", dst, s], capture_output=True)
        if rr.returncode != 0: raise RuntimeError(rr.stderr.decode()[:200])
    finally:
        os.unlink(s)

work = {}
for name, (ra0, dec0, pl) in plans.items():
    v0 = hp.ang2vec(ra0, dec0, lonlat=True)
    for t in hp.query_disc(NST, v0, np.radians(pl['Rh'] + 0.3), nest=True, inclusive=True):
        work.setdefault(int(t), []).append((np.array(v0), pl))
print("tiles to update:", len(work), flush=True)

t0 = time.time(); changed = []
for npix, jobs in sorted(work.items()):
    img = cv2.imread(n4path(npix))
    if img is None: continue
    nest = npix * (W * W) + qsub
    th, ph = hp.pix2ang(NST * W, nest, nest=True)
    ra = np.degrees(ph); dec = 90.0 - np.degrees(th)
    pv = np.array(hp.ang2vec(ra, dec, lonlat=True))
    mv = pv.mean(0)
    wr_ = winner_at(mv, ra, dec, plates_r, vec_r)
    wb_ = winner_at(mv, ra, dec, plates_b, vec_b)
    combq = wr_ * BMAX + (wb_ + 1)
    addq = np.zeros((3, len(combq)), np.float32)
    touched = False
    for v0, pl in jobs:
        r = np.degrees(np.arccos(np.clip(pv @ v0, -1, 1)))
        for k, j, D in pl['pairs']:
            m = (combq == k) & (r < pl['Rh'])
            if not m.any(): continue
            wloc = hp.get_interp_val(pl['wmaps'][(k, j)], th[m], ph[m], nest=True).astype(np.float32)
            if wloc.max() < 0.02: continue
            for ci in range(3):
                addq[ci][m] += np.interp(r[m], RMID, D[ci]) * wloc
            touched = True
    if not touched: continue
    addq = np.clip(addq, 0, 20.0)      # total cap: overlapping stars must not stack
    add = np.stack([cv2.GaussianBlur(cv2.resize(a.reshape(W // QR, W // QR), (W, W),
                    interpolation=cv2.INTER_LINEAR), (0, 0), 1.5) for a in addq])
    bkdir = os.path.join(SC, "halo_backup")
    os.makedirs(bkdir, exist_ok=True)
    bk = os.path.join(bkdir, f"Npix{npix}.webp")
    if not os.path.exists(bk):
        import shutil
        shutil.copy2(n4path(npix), bk)
    out = np.rint(np.clip(img.astype(np.float32) + np.stack([add[2], add[1], add[0]], 2), 0, 255)).astype(np.uint8)
    save_lossless(out, n4path(npix))
    L = (0.114 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.299 * out[:, :, 2])
    save_lossless(np.repeat(np.rint(np.clip(L, 0, 255)).astype(np.uint8)[:, :, None], 3, 2),
                  n4path(npix).replace(SRC, DSTM))
    changed.append(npix)
    print("tile", npix, "done", int(time.time() - t0), "s", flush=True)

for parent in sorted({t // 4 for t in changed}):
    ch = [cv2.imread(n4path(k)) for k in child_ids(parent)]
    if any(x is None for x in ch): continue
    save_lossless(rebuild_parent(ch), n3path(parent))
    chm = [cv2.imread(n4path(k).replace(SRC, DSTM)) for k in child_ids(parent)]
    if any(x is None for x in chm): continue
    save_lossless(rebuild_parent(chm), n3path(parent).replace(SRC, DSTM))
print("APPLY DONE: %d tiles, %d parents (%ds)" % (len(changed), len({t // 4 for t in changed}), int(time.time() - t0)), flush=True)
