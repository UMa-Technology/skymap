"""Full-resolution true-boundary seam DC fix (luminance + chroma), robust.

For a tile we compute the EXACT per-pixel GSSS plate winner (red & blue mosaics),
measure the sharp step across every true plate boundary in a 1-3px band, and solve
per-plate-region DC offsets with a damped Huber IRLS graph (so slivers/weak-link
regions can't blow up). Correction is a per-region constant -> only shifts whole
plate regions to match neighbours; real structure (dust lanes NOT on a boundary)
is untouched by construction.

  cl : luminance DC on combined (red x blue) regions
  cr : R-G chroma DC on red regions ; cb : B-G chroma DC on blue regions
  addR = cl+cr ; addG = cl ; addB = cl+cb    (v5/v7 convention: L uniform, chroma pure)
"""
import os, sys, numpy as np, cv2, scipy.ndimage as ndi
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from gsss_winner import load_channel, sky_to_pixel
import healpy as hp

W = 512; NST = 16
CAP_L = 8.0; CAP_C = 4.0
_plates = None

def _load_plates():
    global _plates
    if _plates is not None:
        return _plates
    hdr = None
    for c in [SC + '/getimage/hdrs/DSSHeaders', SC + '/getimage/DSSHeaders']:
        if os.path.isdir(c):
            hdr = c; break
    pr = load_channel(hdr, ['XP', 'XS', 'ER', 'GR']); pb = load_channel(hdr, ['XJ', 'S'])
    vr = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in pr])
    vb = np.array([hp.ang2vec(p['ra'], p['dec'], lonlat=True) for p in pb])
    _plates = (pr, pb, vr, vb)
    return _plates

def _p1(n):
    n = n & 0xffff; n = (n | (n << 8)) & 0x00FF00FF; n = (n | (n << 4)) & 0x0F0F0F0F
    n = (n | (n << 2)) & 0x33333333; n = (n | (n << 1)) & 0x55555555; return n

def winner_maps(npix, res=W):
    """Exact per-(res-grid) GSSS plate winner, upsampled NEAREST to 512.
    res=512 full-res (2px sub within our 512 tile is 1px); res=256 -> 2px; res=128 -> 4px."""
    pr, pb, vr, vb = _load_plates()
    COSR = np.cos(np.radians(7.8))
    step = W // res
    yy = np.arange(0, W, step); Y, X = np.meshgrid(yy, yy, indexing='ij')
    sub = (_p1(Y.ravel()) | (_p1(X.ravel()) << 1)); nest = npix * (W * W) + sub
    ra, dec = hp.pix2ang(NST * W, nest, nest=True, lonlat=True)
    mv = np.array(hp.ang2vec(ra, dec, lonlat=True)).mean(0)
    def win(plates, vecs):
        cand = np.where(vecs @ mv > COSR)[0]
        best = np.full(len(ra), -1e9); w = np.full(len(ra), -1, np.int64)
        for ci in cand:
            pl = plates[ci]; x, y = sky_to_pixel(pl, ra, dec)
            m = np.minimum.reduce([x, y, pl['nx'] - x, pl['ny'] - y])
            u = (m > 0) & (m > best); best[u] = m[u]; w[u] = ci
        wr = w.reshape(res, res)
        if res != W:
            wr = cv2.resize(wr.astype(np.int32), (W, W), interpolation=cv2.INTER_NEAREST).astype(np.int64)
        return wr
    return win(pr, vr), win(pb, vb)

def _pairs(lab, val, minn=25):
    ids = np.unique(lab); idx = {int(v): i for i, v in enumerate(ids)}; N = len(ids)
    st = np.ones((3, 3), bool)
    I = []; J = []; S = []; Wt = []
    for i, a in enumerate(ids):
        ma = lab == a; dila = ndi.binary_dilation(ma, st); da = ndi.distance_transform_edt(~dila)
        for b in ids[i + 1:]:
            mb = lab == b
            if not (dila & mb).any():
                continue
            db = ndi.distance_transform_edt(~ndi.binary_dilation(mb, st))
            ea = ma & (db >= 1) & (db < 4); eb = mb & (da >= 1) & (da < 4)
            if ea.sum() < minn or eb.sum() < minn:
                continue
            va = val[ea]; vb_ = val[eb]
            step = float(np.median(va) - np.median(vb_))
            mad = 1.4826 * np.median(np.abs(va - np.median(va))) + 1e-3
            w = min(ea.sum(), eb.sum(), 1500) ** 0.5 / (1.0 + (mad / 6.0))
            I.append(idx[int(a)]); J.append(idx[int(b)]); S.append(step); Wt.append(w)
    return ids, N, np.array(I), np.array(J), np.array(S, float), np.array(Wt, float), lab

def _solve(N, I, J, S, W0, areas, cap, lam=0.4):
    if len(I) == 0:
        return np.zeros(N)
    area_w = np.sqrt(np.maximum(areas, 1.0)); area_w /= area_w.max()
    w = W0.copy(); o = np.zeros(N)
    for it in range(6):
        A = np.zeros((N, N)); bvec = np.zeros(N)
        for k in range(len(I)):
            i, j, s, wk = I[k], J[k], S[k], w[k]
            A[i, i] += wk; A[j, j] += wk; A[i, j] -= wk; A[j, i] -= wk
            bvec[i] += -wk * s; bvec[j] += wk * s
        A += np.diag(lam * area_w + 1e-6)   # anchor toward 0, stronger for big regions
        o = np.linalg.solve(A, bvec); o -= np.median(o)
        r = o[I] - o[J] - (-S)              # residual vs target (o_i-o_j = -step)
        sc = 1.345 * max(1.4826 * np.median(np.abs(r)), 0.3)
        w = W0 * np.minimum(1.0, sc / np.maximum(np.abs(r), 1e-6))
    return np.clip(o, -cap, cap)

def seam_correction(npix, img_rgb, res=W):
    """img_rgb: HxWx3 float (RGB). Returns addR,addG,addB float32 planes + info."""
    wr, wb = winner_maps(npix, res)
    R, G, B = img_rgb[:, :, 0], img_rgb[:, :, 1], img_rgb[:, :, 2]
    L = 0.299 * R + 0.587 * G + 0.114 * B
    comb = wr.astype(np.int64) * 10000 + wb
    # luminance on combined regions
    ids, N, I, J, S, Wt, lab = _pairs(comb, L)
    areas = np.array([(comb == v).sum() for v in ids], float)
    cl = _solve(N, I, J, S, Wt, areas, CAP_L)
    cl_map = cl[np.vectorize(lambda v: {int(x): k for k, x in enumerate(ids)}[int(v)])(comb)]
    # chroma R-G on red, B-G on blue
    idr, Nr, Ir, Jr, Sr, Wr_, _ = _pairs(wr, R - G)
    ar = np.array([(wr == v).sum() for v in idr], float)
    cr = _solve(Nr, Ir, Jr, Sr, Wr_, ar, CAP_C)
    cr_map = cr[np.vectorize(lambda v: {int(x): k for k, x in enumerate(idr)}[int(v)])(wr)]
    idb, Nb, Ib, Jb, Sb, Wb_, _ = _pairs(wb, B - G)
    ab = np.array([(wb == v).sum() for v in idb], float)
    cb = _solve(Nb, Ib, Jb, Sb, Wb_, ab, CAP_C)
    cb_map = cb[np.vectorize(lambda v: {int(x): k for k, x in enumerate(idb)}[int(v)])(wb)]
    addR = cl_map + cr_map; addG = cl_map.copy(); addB = cl_map + cb_map
    for a in (addR, addG, addB):
        pass
    addR = cv2.GaussianBlur(addR.astype(np.float32), (0, 0), 1.2)
    addG = cv2.GaussianBlur(addG.astype(np.float32), (0, 0), 1.2)
    addB = cv2.GaussianBlur(addB.astype(np.float32), (0, 0), 1.2)
    info = dict(cl=dict(zip(ids.tolist(), cl.round(1))), maxL=float(np.abs(cl_map).max()),
                nseamL=int((np.abs(S) > 1.5).sum()))
    return addR, addG, addB, (wr, wb)

def stretch(x):
    v = np.clip(x, 0, 255) / 255.0
    a = np.percentile(v, 3); b = max(np.percentile(v, 95), a + 0.02)
    return (np.clip((v - a) / (b - a), 0, 1) ** 0.6 * 255).astype(np.uint8)

if __name__ == "__main__":
    npix = int(sys.argv[1]) if len(sys.argv) > 1 else 2451
    src = "apps/skydata/surveys/dss-starless"
    im = cv2.imread(f"{src}/Norder4/Dir0/Npix{npix}.webp").astype(np.float32)[:, :, ::-1]  # RGB
    aR, aG, aB, (wr, wb) = seam_correction(npix, im)
    out = np.clip(im + np.stack([aR, aG, aB], 2), 0, 255)
    imb = im[:, :, ::-1]; outb = out[:, :, ::-1]      # back to BGR for cv2
    def edges(m):
        e = np.zeros(m.shape, bool); e[:-1] |= m[:-1] != m[1:]; e[:, :-1] |= m[:, :-1] != m[:, 1:]; return e
    vis = stretch(imb).copy(); vis[edges(wr)] = [0, 255, 0]; vis[edges(wb)] = [255, 128, 0]
    full = np.hstack([stretch(imb), np.full((512, 5, 3), 80, np.uint8), stretch(outb),
                      np.full((512, 5, 3), 80, np.uint8), vis])
    cv2.imwrite(SC + f"/diag8/seamfix2_{npix}_full.png", full)
    def crop(x): return cv2.resize(stretch(x)[300:, 300:], (600, 600), interpolation=cv2.INTER_NEAREST)
    br = np.hstack([crop(imb), np.full((600, 6, 3), 80, np.uint8), crop(outb)])
    cv2.imwrite(SC + f"/diag8/seamfix2_{npix}_br.png", br)
    d = np.abs(outb - imb).max(2)
    print("npix %d  |add| max %.1f mean %.2f DN  changed>0.5DN %.1f%%"
          % (npix, d.max(), d.mean(), 100 * (d > 0.5).mean()), flush=True)
    print("DONE -> seamfix2_%d_full.png / _br.png" % npix)
