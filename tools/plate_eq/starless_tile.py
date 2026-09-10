"""Full-tile starless inference with mask-and-composite (the fidelity contract).

  raw(512) + real-neighbor apron(64) -> net (fully conv, whole 640 at once)
  star_mask = (net residual > thr, dilated, feathered)
              MINUS protect_mask (extended DSOs / dark nebulae)
              MINUS extended_suspect star discs
  out = raw outside mask (bit-exact), net output inside mask (feathered blend)

CLI: python starless_tile.py <ckpt> <npix> [...] -> diag8/starless_<npix>.png (A/B/residual)
     add --save <dir> to write webp tiles instead.
"""
import os, sys, numpy as np, cv2, torch
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from apron import assemble_apron
from starnet8 import StarNet8
from star_detect import detect_stars
from protect_mask import protect_mask

APRON = 64
STAR_THR_DN = 1.5     # net residual luminance threshold for the star mask
DILATE = 3
FEATHER = 1.2

_dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
_model = None

def load_model(ckpt):
    global _model
    _model = StarNet8().to(_dev)
    ck = torch.load(ckpt, map_location=_dev)
    _model.load_state_dict(ck['model'])
    _model.eval()
    print("loaded", ckpt, "step", ck.get('step'), flush=True)

def starless(npix, order=4, hole_peak_min=15):
    sub, _ = assemble_apron(order, npix, APRON)      # (640,640,3) RGB float
    x = torch.from_numpy(sub / 127.5 - 1.0).permute(2, 0, 1)[None].float().to(_dev)
    with torch.no_grad():
        out, r = _model(x)
    a = APRON
    out = ((out[0].permute(1, 2, 0).cpu().numpy() + 1) * 127.5)[a:-a, a:-a]
    resid = (r[0].permute(1, 2, 0).cpu().numpy() * 127.5)[a:-a, a:-a]
    raw = sub[a:-a, a:-a]
    rl = 0.299 * resid[:, :, 0] + 0.587 * resid[:, :, 1] + 0.114 * resid[:, :, 2]

    stars = detect_stars(raw)
    pm, info = protect_mask(raw, apron_rgb_640=sub)

    m = (rl > STAR_THR_DN).astype(np.uint8)
    m = cv2.dilate(m, np.ones((2 * DILATE + 1, 2 * DILATE + 1), np.uint8))
    # add detector point-star discs (belt & suspenders for faint cores the net grazed)
    H, W = m.shape
    for s in stars:
        if not s['is_point']:
            continue
        rr = int(min(max(2.5 * s['hfr'], 2), 10))
        cv2.circle(m, (int(round(s['x'])), int(round(s['y']))), rr, 1, -1)
    # extended_suspect discs are UNTOUCHABLE (possible compact galaxies/knots);
    # extended-region protection itself is enforced on w below (star holes allowed)
    for s in stars:
        if s['extended_suspect'] and not s['is_point']:
            rr = int(min(max(3.0 * s['hfr'], 3), 14))
            cv2.circle(m, (int(round(s['x'])), int(round(s['y']))), rr, 0, -1)
    # high-confidence point stars may punch small holes in the protection
    # (foreground stars sit ON galaxies/Milky-Way glow; removing them is the point).
    # hole_peak_min raises the bar inside protected regions: for LMC/SMC (resolved
    # member stars ARE the object) only the brightest foreground stars punch through,
    # preserving the granular texture.
    holes = np.zeros_like(m)
    for s in stars:
        if s['is_point'] and (s['peak_dn'] >= hole_peak_min or s['saturated']):
            rr = int(min(max(2.5 * s['hfr'], 2), 8))
            cv2.circle(holes, (int(round(s['x'])), int(round(s['y']))), rr, 1, -1)
    w = cv2.GaussianBlur(m.astype(np.float32), (0, 0), FEATHER)
    w[pm & ~holes.astype(bool)] = 0.0   # protection bit-exact except star holes
    w = w[:, :, None]
    comp = raw * (1 - w) + out * w
    comp = np.clip(comp, 0, 255)
    return raw, comp, resid, m.astype(bool), pm, holes.astype(bool)

def stretch(x):
    v = np.clip(x, 0, 255) / 255.0
    a = np.percentile(v, 2); b = max(np.percentile(v, 95), a + 0.02)
    return (np.clip((v - a) / (b - a), 0, 1) ** 0.6 * 255).astype(np.uint8)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    save_dir = None
    if "--save" in args:
        i = args.index("--save"); save_dir = args[i + 1]; del args[i:i + 2]
    ckpt = args[0]
    load_model(ckpt)
    os.makedirs(SC + "/diag8", exist_ok=True)
    for tok in args[1:]:
        npix = int(tok)
        raw, comp, resid, sm, pm, holes = starless(npix)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            cv2.imwrite(os.path.join(save_dir, f"Npix{npix}.webp"),
                        np.rint(comp[:, :, ::-1]).astype(np.uint8),
                        [cv2.IMWRITE_WEBP_QUALITY, 101])
        rs = np.clip(np.abs(resid) * 6, 0, 255).astype(np.uint8)
        panel = np.hstack([stretch(raw), np.full((512, 6, 3), 80, np.uint8),
                           stretch(comp), np.full((512, 6, 3), 80, np.uint8), rs])
        cv2.imwrite(SC + f"/diag8/starless_{npix}.png", panel[:, :, ::-1])
        d = np.abs(comp - raw).max(axis=2)
        strict = pm & ~holes
        print("npix %d: star-mask %.1f%% protect %.1f%% holes %.1f%% | max|d| strict-protect %.2f DN | mean|d| outside %.3f"
              % (npix, 100 * sm.mean(), 100 * pm.mean(), 100 * holes.mean(),
                 d[strict].max() if strict.any() else 0,
                 d[~sm & ~pm].mean()), flush=True)
    print("DONE")
