"""Luminance-conserving R<->B chroma seam equalizer (user's idea).

Instead of leveling brightness (v2 changed L, risking real structure), fix ONLY
the color cast: transfer signal between R and B across the seam while holding L
= 0.299R + 0.587G + 0.114B EXACTLY constant (G untouched).

  L-conserving transfer, G fixed:  0.299*dR + 0.114*dB = 0  ->  dB = -2.623*dR
  so lowering R by x is compensated by raising B by 2.623x  (and vice versa).

Because L is conserved, real structure (which lives in L) is untouched by
construction -- we only rotate color along the dead-blue R-B axis, exactly the
plate-boundary color-cast artifact.

Per seam: measure the R-B step across the line, then apply an antisymmetric
membrane that removes it, split half to each side, as an L-conserving R<->B
transfer.  Selection: 'flat' (only chroma-DC seams) or 'all' (every straight
chroma edge).  Gate uses the R-B step profile (flat=cast seam, ramp=real).
"""
import os, sys, numpy as np, cv2
from chroma_seam import _chroma, _merge_lines, stf
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))

WL, WG, WB = 0.299, 0.587, 0.114
K = WL / WB          # 2.623 : dB = -K*dR keeps L fixed with G held
GRAD_PCT = 96.5
MIN_LEN = 120
NARROW = (1.0, 4.0)
WIDE = (14.0, 24.0)
MEMB = 12.0          # chroma is low-freq -> a wide, soft blend looks natural
RB_MIN = 3.0        # min |R-B chroma step| (DN) to bother
FLAT_FRAC = 0.7
FLAT_ABS = 3.0

def _band(onseg, d, lo, hi, ch):
    pos = onseg & (d > lo) & (d < hi); neg = onseg & (d < -lo) & (d > -hi)
    if pos.sum() < 150 or neg.sum() < 150:
        return None
    return float(np.median(ch[pos]) - np.median(ch[neg]))

def detect(rgb):
    L, RL, BL = _chroma(rgb)
    g = np.hypot(cv2.Sobel(RL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(RL, cv2.CV_32F, 0, 1, 7)) \
        + np.hypot(cv2.Sobel(BL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(BL, cv2.CV_32F, 0, 1, 7))
    edm = cv2.dilate((g > np.percentile(g, GRAD_PCT)).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(edm, 1, np.pi / 360, threshold=45, minLineLength=MIN_LEN, maxLineGap=50)
    if lines is None:
        return []
    clusters = _merge_lines(lines.reshape(-1, 4))
    Rm = cv2.medianBlur(rgb[:, :, 0].astype(np.uint8), 5).astype(np.float32)
    Bm = cv2.medianBlur(rgb[:, :, 2].astype(np.uint8), 5).astype(np.float32)
    RB = Rm - Bm                                   # the dead-blue axis
    H, W = L.shape
    yy, xx = np.mgrid[0:H, 0:W]
    edges = []
    for c in clusters:
        x1, y1, x2, y2 = c['seg']
        dx, dy = x2 - x1, y2 - y1
        ln = np.hypot(dx, dy) + 1e-6
        if ln < MIN_LEN:
            continue
        nx, ny = -dy / ln, dx / ln
        d = (xx - x1) * nx + (yy - y1) * ny
        tpar = ((xx - x1) * dx + (yy - y1) * dy) / (ln * ln)
        onseg = (tpar > 0.0) & (tpar < 1.0)
        rbN = _band(onseg, d, *NARROW, RB); rbW = _band(onseg, d, *WIDE, RB)
        if rbN is None or rbW is None:
            continue
        ramp = rbW - rbN
        flat = abs(ramp) <= max(FLAT_FRAC * abs(rbN), FLAT_ABS)
        strong = abs(rbN) >= RB_MIN
        edges.append(dict(seg=c['seg'], nx=nx, ny=ny, x0=x1, y0=y1, dx=dx, dy=dy, ln=ln,
                          rb=rbN, ramp=ramp, flat=flat, strong=strong,
                          verdict="CAST" if (flat and strong) else ("weak" if flat else "structure")))
    edges.sort(key=lambda e: -abs(e['rb']))
    return edges

def apply(rgb, edges, sel='flat', band=MEMB):
    H, W = rgb.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = rgb.astype(np.float32).copy()
    for e in edges:
        use = e['strong'] and (e['flat'] if sel == 'flat' else True)
        if not use:
            continue
        d = (xx - e['x0']) * e['nx'] + (yy - e['y0']) * e['ny']
        tpar = ((xx - e['x0']) * e['dx'] + (yy - e['y0']) * e['dy']) / (e['ln'] ** 2)
        walong = np.clip(1.5 - np.abs(tpar - 0.5) * 2.0, 0, 1)
        prof = np.tanh(d / (band * 0.6)) * walong        # antisym membrane, -1..+1
        # remove the R-B step: want d(R-B) = -rb*prof/2 on each side (half+half)
        # via L-conserving transfer dB=-K*dR: d(R-B)=dR-dB=dR(1+K)
        dR = (-0.5 * e['rb'] * prof) / (1.0 + K)
        out[:, :, 0] += dR
        out[:, :, 2] += -K * dR
    return np.clip(out, 0, 255)

if __name__ == "__main__":
    npix = int(sys.argv[1]) if len(sys.argv) > 1 else 2635
    im = cv2.imread(f"apps/skydata/surveys/dss-clean/Norder4/Dir0/Npix{npix}.webp")
    rgb = im[:, :, ::-1].astype(np.float32)
    edges = detect(rgb)
    print("tile %d: %d straight edges" % (npix, len(edges)))
    for e in edges:
        x1, y1, x2, y2 = [int(v) for v in e['seg']]
        print("  seg(%d,%d,%d,%d) len=%.0f  R-B step=%+.1f ramp=%+.1f -> %s"
              % (x1, y1, x2, y2, e['ln'], e['rb'], e['ramp'], e['verdict']))
    corr_flat = apply(rgb, edges, sel='flat')
    corr_all = apply(rgb, edges, sel='all')
    # verify L conservation
    def lum(a): return WL * a[:, :, 0] + WG * a[:, :, 1] + WB * a[:, :, 2]
    print("max |dL| flat=%.3f  all=%.3f DN (should be ~0)"
          % (np.abs(lum(corr_flat) - lum(rgb)).max(), np.abs(lum(corr_all) - lum(rgb)).max()))
    before = stf(rgb[:, :, ::-1])
    af = stf(corr_flat[:, :, ::-1]); aa = stf(corr_all[:, :, ::-1])
    cv2.putText(af, "flat only", (6, 22), 0, 0.7, (0, 255, 255), 2)
    cv2.putText(aa, "all straight", (6, 22), 0, 0.7, (0, 255, 255), 2)
    sep = np.full((512, 5, 3), 80, np.uint8)
    panel = np.hstack([before, sep, af, sep, aa])
    os.makedirs(SC + "/diag8", exist_ok=True)
    cv2.imwrite(SC + f"/diag8/cseam3_{npix}.png", panel)
    print("wrote diag8/cseam3_%d.png (before | flat-only | all-straight)" % npix)
