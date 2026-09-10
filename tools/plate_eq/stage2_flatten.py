"""Stage 2: background regeneration / plate-fog texture erasure on the STARLESS layer.

Now that resolved stars are gone, background estimation is clean. We split the
starless sky into three scales via masked normalized convolution:
    bg_coarse (~sigma 24px, real large-scale gradients + big nebulosity -> KEEP)
    mottle    (bg_coarse..~6px correlated mid-scale = plate emulsion fog -> ERASE where gated)
    pixnoise  (~1px grain -> KEEP, avoids the plastic look)
Output = bg_coarse + pixnoise + (1-gate)*mottle, with protect_mask bit-exact.

gate = level_gate * amp_gate:
  - level_gate: 1 on dark quiet sky, ->0 on bright Milky Way (bright glow is real,
    never flattened; same philosophy as the old |b| gate but per-pixel on clean data)
  - amp_gate: 1 on low-amplitude mottle (1-3 DN fog), ->0 on high-amplitude
    mid-scale structure (nebula filaments / real clumping)
Estimation uses a real-neighbor apron for tile-border consistency.

CLI: python stage2_flatten.py <npix>... [--strength S]  -> diag8/flat_<npix>.png (A/B/gate)
"""
import os, sys, numpy as np, cv2
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
import assemble
assemble.RAW = os.path.join(assemble.ROOT, "apps", "skydata", "surveys", "dss-starless")
assemble.CAST = "/nonexistent"
from apron import assemble_apron
from protect_mask import protect_mask

APRON = 64
# defaults (tunable); DN units on 8-bit
LVL_DARK, LVL_BRIGHT = 22.0, 46.0    # level_gate: full flatten below DARK, none above BRIGHT
AMP_LO, AMP_HI = 2.2, 5.5            # amp_gate: full flatten below LO |mottle|, none above HI
SIG_COARSE = 24.0                    # px, the "keep" large scale
SIG_MOTTLE = 6.0                     # px, correlated mottle band upper cut

def _smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a + 1e-6), 0, 1)
    return t * t * (3 - 2 * t)

def normconv(img, valid, sigma):
    """masked normalized convolution (deterministic)."""
    v = valid.astype(np.float32)
    num = cv2.GaussianBlur(img * v, (0, 0), sigma)
    den = cv2.GaussianBlur(v, (0, 0), sigma)
    return num / np.maximum(den, 1e-3)

PRESETS = {  # (lvl_bright, amp_hi, sig_mottle)  -- higher = more aggressive fog removal
    "gentle": (40.0, 4.0, 5.0),
    "medium": (46.0, 5.5, 6.0),
    "strong": (58.0, 8.5, 9.0),
}

def flatten(npix, order=4, strength=1.0, preset="medium"):
    lvl_bright, amp_hi, sig_mottle = PRESETS[preset]
    sub, _ = assemble_apron(order, npix, APRON)         # (640,640,3) RGB float, starless
    a = APRON
    raw = sub[a:-a, a:-a]
    pm, info = protect_mask(raw, apron_rgb_640=sub)
    # estimation validity: exclude protected + very bright residual (compact DSO cores)
    Lsub = 0.299 * sub[:, :, 0] + 0.587 * sub[:, :, 1] + 0.114 * sub[:, :, 2]
    pm_ap = np.zeros(sub.shape[:2], bool)
    pm_ap[a:-a, a:-a] = pm
    valid = ~pm_ap & (Lsub < 200)
    coarse_stack, mott_stack, pixn_stack = [], [], []
    for c in range(3):
        ch = sub[:, :, c]
        bg = normconv(ch, valid, SIG_COARSE)
        resid = ch - bg
        mott = normconv(resid, valid, sig_mottle)
        pixn = resid - mott
        coarse_stack.append(bg[a:-a, a:-a])
        mott_stack.append(mott[a:-a, a:-a])
        pixn_stack.append(pixn[a:-a, a:-a])
    coarse = np.stack(coarse_stack, -1)
    mott = np.stack(mott_stack, -1)
    pixn = np.stack(pixn_stack, -1)
    coarseL = 0.299 * coarse[:, :, 0] + 0.587 * coarse[:, :, 1] + 0.114 * coarse[:, :, 2]
    mottL = 0.299 * mott[:, :, 0] + 0.587 * mott[:, :, 1] + 0.114 * mott[:, :, 2]
    mottamp = cv2.GaussianBlur(np.abs(mottL), (0, 0), 6.0)
    level_gate = 1.0 - _smoothstep(coarseL, LVL_DARK, lvl_bright)
    amp_gate = 1.0 - _smoothstep(mottamp, AMP_LO, amp_hi)
    gate = np.clip(level_gate * amp_gate * strength, 0, 1)
    gate = cv2.GaussianBlur(gate, (0, 0), 3.0)
    gate3 = gate[:, :, None]
    comp = coarse + pixn + (1.0 - gate3) * mott
    # protect bit-exact
    comp[pm] = raw[pm]
    comp = np.clip(comp, 0, 255)
    return raw, comp, gate, pm, mottL

def stretch(x):
    v = np.clip(x, 0, 255) / 255.0
    a = np.percentile(v, 2); b = max(np.percentile(v, 96), a + 0.02)
    return (np.clip((v - a) / (b - a), 0, 1) ** 0.6 * 255).astype(np.uint8)

if __name__ == "__main__":
    args = sys.argv[1:]
    strength = 1.0
    if "--strength" in args:
        i = args.index("--strength"); strength = float(args[i + 1]); del args[i:i + 2]
    os.makedirs(SC + "/diag8", exist_ok=True)
    for tok in args:
        npix = int(tok)
        raw, comp, gate, pm, mottL = flatten(npix, strength=strength)
        d = np.abs(comp - raw).max(axis=2)
        gv = (np.clip(gate, 0, 1) * 255).astype(np.uint8)
        gv = cv2.cvtColor(gv, cv2.COLOR_GRAY2BGR)
        panel = np.hstack([stretch(raw), np.full((512, 5, 3), 80, np.uint8),
                           stretch(comp), np.full((512, 5, 3), 80, np.uint8), gv])
        cv2.imwrite(SC + f"/diag8/flat_{npix}.png", panel[:, :, ::-1])
        print("npix %d: max|d| protect %.2f | mean|d| flattened %.2f DN | gate>0.5 %.1f%%"
              % (npix, d[pm].max() if pm.any() else 0,
                 (d[gate > 0.3]).mean() if (gate > 0.3).any() else 0, 100 * (gate > 0.5).mean()),
              flush=True)
    print("DONE")
