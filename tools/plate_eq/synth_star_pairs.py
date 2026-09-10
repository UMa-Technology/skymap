"""Synthetic training-pair generator for the DSS star-removal net.

Recipe (StarNet-inverted, starrem2k13-validated):
  base   = real tile with detected point-stars infilled (annulus-median) — keeps
           real fog texture, extended DSOs, unresolved Milky Way granulation as
           the PRESERVE class by construction
  input  = base + pasted real-DSS star stamps (starcut_lib.npz), density matched
           to the tile's stratum, additive with random gain
  target = base
  y_mask = soft alpha of the pasted layer (exact ground truth)
10% identity samples (no stars pasted) teach "leave clean sky alone".
"""
import os, sys, numpy as np, cv2
import healpy as hp
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from star_detect import detect_stars

SRC = "apps/skydata/surveys/dss"
PATCH = 256

def n4path(npix):
    return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

def gal_b(npix):
    ra, dec = hp.pix2ang(16, npix, nest=True, lonlat=True)
    r = hp.Rotator(coord=['C', 'G'])
    th, ph = r(np.radians(90 - dec), np.radians(ra))
    return 90 - np.degrees(th)

class StampLib:
    def __init__(self, path):
        z = np.load(path)
        self.buckets = []
        for s in (12, 16, 24, 32, 48, 64):
            k = f"stamps_{s}"
            if k in z and len(z[k]):
                self.buckets.append((s, z[k].astype(np.float32),
                                     z[f"masks_{s}"].astype(np.float32),
                                     z[f"meta_{s}"].astype(np.float32)))
        self.sat = []
        for s in (12, 16, 24, 32, 48, 64):
            k = f"sat_stamps_{s}"
            if k in z and len(z[k]):
                self.sat.append((s, z[k].astype(np.float32), z[f"sat_masks_{s}"].astype(np.float32)))
        n = sum(len(b[1]) for b in self.buckets)
        print(f"stamp lib: {n} stamps in {len(self.buckets)} buckets, {sum(len(b[1]) for b in self.sat)} saturated")

    def sample(self, rng, saturated=False):
        pool = self.sat if (saturated and self.sat) else self.buckets
        # weight buckets by count, then favor small stamps (power-law-ish sky)
        wts = np.array([len(b[1]) / (i + 1.0) for i, b in enumerate(pool)])
        bi = rng.choice(len(pool), p=wts / wts.sum())
        b = pool[bi]
        j = rng.integers(len(b[1]))
        return b[1][j], b[2][j]

class TileBase:
    """decoded tile + star-infilled base, cached."""
    def __init__(self, npix):
        img = cv2.imread(n4path(npix))
        if img is None:
            raise FileNotFoundError(npix)
        self.rgb = img[:, :, ::-1].astype(np.float32)     # RGB
        stars = detect_stars(self.rgb)
        base = self.rgb.copy()
        H, W = base.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W]
        order = np.argsort(-stars['peak_dn'])
        for i in order:
            s = stars[i]
            if not s['is_point']:
                continue
            r = float(min(max(2.5 * s['hfr'], 2.0), 12.0))
            cx, cy = float(s['x']), float(s['y'])
            x0, x1 = max(int(cx - 4 * r), 0), min(int(cx + 4 * r) + 1, W)
            y0, y1 = max(int(cy - 4 * r), 0), min(int(cy + 4 * r) + 1, H)
            d2 = (xx[y0:y1, x0:x1] - cx) ** 2 + (yy[y0:y1, x0:x1] - cy) ** 2
            disc = d2 <= r * r
            ann = (d2 > (1.4 * r) ** 2) & (d2 <= (2.2 * r) ** 2)
            if disc.sum() == 0 or ann.sum() < 8:
                continue
            sub = base[y0:y1, x0:x1]
            for c in range(3):
                fill = np.median(sub[:, :, c][ann])
                ch = sub[:, :, c]
                ch[disc] = fill
        self.base = base

class PairGen:
    def __init__(self, lib_path, seed=0, quiet_frac=0.45, med_frac=0.35):
        self.rng = np.random.default_rng(seed)
        self.lib = StampLib(lib_path)
        rng2 = np.random.default_rng(1234)
        allpix = rng2.permutation(3072)
        self.strata = {'quiet': [], 'medium': [], 'dense': []}
        for p in allpix:
            b = abs(gal_b(int(p)))
            k = 'quiet' if b > 30 else ('medium' if b > 10 else 'dense')
            if len(self.strata[k]) < 60:
                self.strata[k].append(int(p))
        self.dens = {'quiet': 45, 'medium': 130, 'dense': 320}
        self.frac = [('quiet', quiet_frac), ('medium', med_frac), ('dense', 1 - quiet_frac - med_frac)]
        self.cache = {}

    def _tile(self, npix):
        if npix not in self.cache:
            if len(self.cache) > 24:
                self.cache.pop(next(iter(self.cache)))
            self.cache[npix] = TileBase(npix)
        return self.cache[npix]

    def sample(self):
        rng = self.rng
        u = rng.random(); acc = 0.0
        for k, f in self.frac:
            acc += f
            if u <= acc: stratum = k; break
        else: stratum = 'dense'
        npix = int(rng.choice(self.strata[stratum]))
        try:
            tb = self._tile(npix)
        except FileNotFoundError:
            return self.sample()
        y0 = rng.integers(0, 512 - PATCH + 1); x0 = rng.integers(0, 512 - PATCH + 1)
        target = tb.base[y0:y0 + PATCH, x0:x0 + PATCH].copy()
        inp = target.copy()
        mask = np.zeros((PATCH, PATCH), np.float32)
        if rng.random() > 0.10:                       # 10% identity samples
            K = rng.poisson(self.dens[stratum])
            for _ in range(K):
                sat = rng.random() < 0.02
                stamp, alpha = self.lib.sample(rng, saturated=sat)
                s = stamp.shape[0]
                gain = rng.uniform(0.7, 1.4)
                py = rng.integers(-s // 2, PATCH - s // 2)
                px = rng.integers(-s // 2, PATCH - s // 2)
                sy0, sx0 = max(0, -py), max(0, -px)
                sy1 = min(s, PATCH - py); sx1 = min(s, PATCH - px)
                if sy1 <= sy0 or sx1 <= sx0: continue
                ty0, tx0 = py + sy0, px + sx0
                st = stamp[sy0:sy1, sx0:sx1] * gain
                inp[ty0:ty0 + sy1 - sy0, tx0:tx0 + sx1 - sx0] += st
                al = alpha[sy0:sy1, sx0:sx1]
                mm = mask[ty0:ty0 + sy1 - sy0, tx0:tx0 + sx1 - sx0]
                np.maximum(mm, np.clip(al * min(gain, 1.0), 0, 1), out=mm)
        inp = np.clip(inp, 0, 255)
        # paired augmentation
        k = rng.integers(4)
        if k: inp, target, mask = (np.rot90(a, k).copy() for a in (inp, target, mask))
        if rng.random() < 0.5:
            inp, target, mask = (np.fliplr(a).copy() for a in (inp, target, mask))
        if rng.random() < 0.5:                        # small per-channel offset (color-cast robustness)
            off = rng.uniform(-3, 3, 3).astype(np.float32)
            inp = np.clip(inp + off, 0, 255); target = np.clip(target + off, 0, 255)
        return inp, target, mask

if __name__ == "__main__":
    g = PairGen(SC + "/starcut_lib.npz", seed=7)
    rows = []
    for i in range(6):
        inp, tgt, m = g.sample()
        st = lambda x: (np.clip(np.arcsinh((x - np.median(x)) / 3.0) / 4.0 + 0.35, 0, 1) * 255).astype(np.uint8)
        rows.append(np.hstack([st(inp), st(tgt), np.repeat((m[:, :, None] * 255).astype(np.uint8), 3, 2)]))
    os.makedirs(SC + "/diag8", exist_ok=True)
    cv2.imwrite(SC + "/diag8/synth_pairs.png", np.vstack(rows)[:, :, ::-1])
    print("wrote diag8/synth_pairs.png")
