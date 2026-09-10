"""Pre-generate base crops for SeamNet training (clean-ish = current tile state).
Saves seamnet/train_crops.npz + val_crops.npz: img (N,3,SZ,SZ) f16 [R,G,B],
labr/labb (N,SZ,SZ) i16, gb (N,SZ,SZ) f16."""
import os, time
import numpy as np
import healpy as hp
from seamnet_common import SC, NS, NPIX, SZ, load_state, load_labels, crop_dirs, sample_crop

OUT = SC + "/seamnet"
os.makedirs(OUT, exist_ok=True)
N_TRAIN, N_VAL = 4096, 64

R, G, B, gb = load_state()
labr_map, labb_map = load_labels()
rng = np.random.default_rng(7)

# Milky-Way-weighted crop centers (the problem zone), rest of sky still covered.
def draw_centers(n):
    acc = []
    while len(acc) < n:
        p = rng.integers(0, NPIX, 8192)
        keep = rng.random(8192) < 0.3 + 0.7 * np.exp(-(gb[p] / 22.0) ** 2)
        acc.extend(p[keep].tolist())
    return np.array(acc[:n])

def build(n, tag):
    cen = draw_centers(n)
    psi = rng.random(n) * 2 * np.pi
    img = np.empty((n, 3, SZ, SZ), np.float16)
    lr = np.empty((n, SZ, SZ), np.int16)
    lb = np.empty((n, SZ, SZ), np.int16)
    gbc = np.empty((n, SZ, SZ), np.float16)
    t0 = time.time()
    for i in range(n):
        c = np.array(hp.pix2vec(NS, int(cen[i]), nest=True))
        V = crop_dirs(c, psi[i])
        (r, g, b, gc), (a, bb) = sample_crop(V, [R, G, B, gb], [labr_map, labb_map])
        img[i] = np.stack([r, g, b]).astype(np.float16)
        lr[i] = a.astype(np.int16)
        lb[i] = bb.astype(np.int16)
        gbc[i] = gc.astype(np.float16)
        if (i + 1) % 256 == 0:
            print(tag, i + 1, "/", n, int(time.time() - t0), "s", flush=True)
    np.savez(os.path.join(OUT, tag + "_crops.npz"), img=img, labr=lr, labb=lb, gb=gbc)
    print("saved", tag, flush=True)

build(N_VAL, "val")
build(N_TRAIN, "train")
print("PREP DONE")
