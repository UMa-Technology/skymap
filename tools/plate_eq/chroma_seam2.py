"""Conservative data-driven seam corrector (v2): DC-only, profile-gated.

v1 failed because it measured the step over a WIDE band (d=4..20px) and so
picked up real nebula structure (star-cloud / dust-lane edges ramp to 15-30 DN
away from the line). v2 uses the step-vs-distance PROFILE to keep only true
plate seams:

  * measure per-channel step at a narrow band (d~1.5-3px, ~ the discontinuity)
    and a wide band (d~16-24px, ~ includes real structure)
  * a DC seam is FLAT: |wide-narrow| small vs narrow -> real discontinuity
  * a structure edge RAMPS: wide >> narrow -> skip it entirely
  * correct only FLAT edges, with the NARROW-band step and a NARROW membrane

detect(rgb) -> edges (only flat/DC ones, with narrow-band step)
apply(rgb, edges) -> corrected rgb
CLI: python chroma_seam2.py <npix> -> diag8/cseam2_<npix>.png (before|after|edges)
"""
import os, sys, numpy as np, cv2
from chroma_seam import _chroma, _merge_lines, stf
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))

GRAD_PCT = 96.5
MIN_LEN = 120
NARROW = (1.0, 4.0)     # DC band: right at the discontinuity
WIDE = (14.0, 24.0)     # structure band: far from the line
MEMB = 4.5              # membrane half-width (px) -- narrow, matches a real DC step
DC_MIN = 3.0           # min |DC step| (L or chroma) to bother correcting (DN)
FLAT_FRAC = 0.6        # flat if |ramp| <= max(FLAT_FRAC*|DC|, FLAT_ABS)
FLAT_ABS = 2.5

def _band_step(onseg, d, lo, hi, chans):
    pos = onseg & (d > lo) & (d < hi)
    neg = onseg & (d < -lo) & (d > -hi)
    if pos.sum() < 150 or neg.sum() < 150:
        return None
    return {ch: float(np.median(m[pos]) - np.median(m[neg])) for ch, m in chans}

def detect(rgb):
    L, RL, BL = _chroma(rgb)
    g = np.hypot(cv2.Sobel(RL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(RL, cv2.CV_32F, 0, 1, 7)) \
        + np.hypot(cv2.Sobel(BL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(BL, cv2.CV_32F, 0, 1, 7))
    edm = cv2.dilate((g > np.percentile(g, GRAD_PCT)).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(edm, 1, np.pi / 360, threshold=45, minLineLength=MIN_LEN, maxLineGap=50)
    if lines is None:
        return []
    clusters = _merge_lines(lines.reshape(-1, 4))
    chans = [(ch, cv2.medianBlur(rgb[:, :, i].astype(np.uint8), 5).astype(np.float32))
             for i, ch in enumerate('RGB')]
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
        sN = _band_step(onseg, d, *NARROW, chans)
        sW = _band_step(onseg, d, *WIDE, chans)
        if sN is None or sW is None:
            continue
        dcL = 0.299 * sN['R'] + 0.587 * sN['G'] + 0.114 * sN['B']
        wideL = 0.299 * sW['R'] + 0.587 * sW['G'] + 0.114 * sW['B']
        ramp = wideL - dcL
        dcchr = abs(sN['R'] - dcL) + abs(sN['B'] - dcL)
        flat = abs(ramp) <= max(FLAT_FRAC * abs(dcL), FLAT_ABS)
        strong = abs(dcL) >= DC_MIN or dcchr >= DC_MIN
        keep = flat and strong
        edges.append(dict(seg=c['seg'], nx=nx, ny=ny, x0=x1, y0=y1, dx=dx, dy=dy, ln=ln,
                          step=sN, dL=dcL, ramp=ramp, dchr=dcchr, keep=keep,
                          verdict="SEAM" if keep else ("weak" if flat else "structure")))
    edges.sort(key=lambda e: -abs(e['dL']))
    return edges

def apply(rgb, edges, band=MEMB):
    H, W = rgb.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = rgb.astype(np.float32).copy()
    for e in edges:
        if not e['keep']:
            continue
        d = (xx - e['x0']) * e['nx'] + (yy - e['y0']) * e['ny']
        tpar = ((xx - e['x0']) * e['dx'] + (yy - e['y0']) * e['dy']) / (e['ln'] ** 2)
        walong = np.clip(1.5 - np.abs(tpar - 0.5) * 2.0, 0, 1)
        prof = np.tanh(d / (band * 0.6)) * walong
        for ci, ch in enumerate('RGB'):
            out[:, :, ci] -= 0.5 * e['step'][ch] * prof
    return np.clip(out, 0, 255)

if __name__ == "__main__":
    npix = int(sys.argv[1]) if len(sys.argv) > 1 else 2635
    im = cv2.imread(f"apps/skydata/surveys/dss-clean/Norder4/Dir0/Npix{npix}.webp")
    rgb = im[:, :, ::-1].astype(np.float32)
    edges = detect(rgb)
    ncorr = sum(e['keep'] for e in edges)
    print("tile %d: %d candidate lines, %d classified as correctable DC seams" % (npix, len(edges), ncorr))
    for e in edges:
        x1, y1, x2, y2 = [int(v) for v in e['seg']]
        print("  seg(%d,%d,%d,%d) len=%.0f  DC_L=%+.1f chr=%.1f ramp=%+.1f  -> %s"
              % (x1, y1, x2, y2, e['ln'], e['dL'], e['dchr'], e['ramp'], e['verdict']))
    before = stf(rgb[:, :, ::-1])
    sep = np.full((512, 5, 3), 80, np.uint8)
    panels = [before, sep]
    for bw in (4.5, 8.0, 12.0):
        after = stf(apply(rgb, edges, band=bw)[:, :, ::-1])
        cv2.putText(after, "band=%.0f" % bw, (6, 22), 0, 0.7, (0, 255, 255), 2)
        panels += [after, sep]
    panel = np.hstack(panels[:-1])
    os.makedirs(SC + "/diag8", exist_ok=True)
    cv2.imwrite(SC + f"/diag8/cseam2_{npix}.png", panel)
    print("wrote diag8/cseam2_%d.png (before | band4.5 | band8 | band12)" % npix)
