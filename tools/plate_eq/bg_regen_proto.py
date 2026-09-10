"""Track A prototype: deterministic BACKGROUND REGENERATION (Gemini-look, controllable).

Per tile:
  B   = median-filter background (stars rejected)          [k]
  Bs  = strongly smoothed B                                 [sigma]
  S   = local structure amplitude of B -> gate w (protect real extended structure)
  bg  = w*B + (1-w)*Bs        (quiet sky gets regenerated, structured sky kept)
  D   = img - B; keep-gain g = smoothstep(|D_L|; t0, t1) (same gain all channels
        -> no color noise at threshold); out = bg + g*D
Renders orig|processed pairs for judging. Variants over (k, sigma, t0, t1, gate).
"""
import os, sys, numpy as np, cv2
import healpy as hp
SC = os.environ["SCRATCH"]

SRC = "apps/skydata/surveys/dss"
def n4path(npix): return os.path.join(SRC, "Norder4", f"Dir{(npix//10000)*10000}", f"Npix{npix}.webp")

def regen(img, k=31, sigma=10.0, t0=1.2, t1=3.0, gate_lo=1.2, gate_hi=4.0):
    f = img.astype(np.float32)
    u8 = np.clip(f, 0, 255).astype(np.uint8)
    B = np.stack([cv2.medianBlur(u8[:, :, c], k).astype(np.float32) for c in range(3)], 2)
    Bs = cv2.GaussianBlur(B, (0, 0), sigma)
    BL = 0.114 * B[:, :, 0] + 0.587 * B[:, :, 1] + 0.299 * B[:, :, 2]
    S = np.abs(BL - cv2.GaussianBlur(BL, (0, 0), sigma * 2))
    S = cv2.GaussianBlur(S, (0, 0), 8)
    w = np.clip((S - gate_lo) / (gate_hi - gate_lo), 0, 1)[:, :, None]
    bg = w * B + (1 - w) * Bs
    D = f - B
    DL = np.abs(0.114 * D[:, :, 0] + 0.587 * D[:, :, 1] + 0.299 * D[:, :, 2])
    g = np.clip((DL - t0) / (t1 - t0), 0, 1)
    g = (g * g * (3 - 2 * g))[:, :, None]
    out = bg + g * D
    return np.clip(out, 0, 255), float(w.mean()), float(g.mean())

def stretch(x, a, b, gamma=0.6):
    v = np.clip(x, 0, 255) / 255.0
    return (np.clip((v - a) / max(b - a, 1e-3), 0, 1) ** gamma * 255).astype(np.uint8)

TILES = {
    "t1252": 1252, "t1219": 1219,
    "acrux": int(hp.ang2pix(16, 186.65, -63.10, nest=True, lonlat=True)),
    "ngc253": int(hp.ang2pix(16, 11.888, -25.288, nest=True, lonlat=True)),
    "m31": int(hp.ang2pix(16, 10.685, 41.269, nest=True, lonlat=True)),
    "lmc": int(hp.ang2pix(16, 80.0, -69.0, nest=True, lonlat=True)),
}
VARIANTS = [
    dict(tag="soft", k=31, sigma=10, t0=1.2, t1=3.0),
    dict(tag="strong", k=31, sigma=16, t0=2.0, t1=4.5),
]
os.makedirs(SC + "/diag7", exist_ok=True)
for name, npix in TILES.items():
    img = cv2.imread(n4path(npix))
    if img is None:
        print("missing", name, npix); continue
    f = img.astype(np.float32)
    L = 0.114 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.299 * f[:, :, 2]
    a = np.percentile(L, 2) / 255.0; b = max(np.percentile(L, 92) / 255.0, a + 0.03)
    panels = [stretch(f, a, b)]
    for vv in VARIANTS:
        out, wm, gm = regen(f, k=vv['k'], sigma=vv['sigma'], t0=vv['t0'], t1=vv['t1'])
        panels.append(stretch(out, a, b))
        print("%s %-6s w_keepstruct %.2f g_keepdetail %.2f" % (name, vv['tag'], wm, gm), flush=True)
    sep = np.full((512, 8, 3), 60, np.uint8)
    row = panels[0]
    for p in panels[1:]:
        row = np.hstack([row, sep, p])
    cv2.putText(row, "orig | soft | strong", (8, 20), 0, 0.55, (0, 0, 255), 2)
    cv2.imwrite(SC + "/diag7/bgregen_%s.png" % name, row)
    print("saved", name, npix, flush=True)
print("DONE")
