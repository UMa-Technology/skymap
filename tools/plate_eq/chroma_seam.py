"""Data-driven chroma-edge seam corrector (geometry-independent).

Root cause found: the GetImage winner geometry is offset ~0.4deg from the real
CDS plate boundaries, so all prior seam work corrected the wrong locations.
Fix (built on the user's two insights): subtract L -> real structure lives in L
and vanishes, so a plate boundary is the ONLY straight line in the chroma (R-L,
B-L) gradient. Detect that straight line from the DATA, measure the per-channel
step across it, and membrane-level it AT the true edge.

detect_edges(rgb) -> list of (line, per-channel step, score)
apply_correction(rgb, edges) -> corrected rgb  (per-channel tanh membrane)
CLI: python chroma_seam.py <npix> -> diag8/cseam_<npix>.png (before|after|edges)
"""
import os, sys, numpy as np, cv2
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))

CHROMA_SIG = 8.0      # chroma smoothing to kill star noise
GRAD_PCT = 96.5       # gradient percentile for edge candidates
MIN_LEN = 120         # min straight-line length (px)
BAND = 26.0           # membrane half-width (px); tanh over ~this
STEP_MIN = 1.8        # min |L or chroma step| to bother correcting (DN)
MEDIAN_K = 5          # star-robust median filter for step measurement

def _chroma(rgb):
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    L = 0.299 * R + 0.587 * G + 0.114 * B
    return L, cv2.GaussianBlur(R - L, (0, 0), CHROMA_SIG), cv2.GaussianBlur(B - L, (0, 0), CHROMA_SIG)

def _merge_lines(segs, ang_tol=6, off_tol=22):
    """cluster Hough segments by (angle, perpendicular offset), keep one per cluster."""
    out = []
    for s in segs:
        x1, y1, x2, y2 = [float(v) for v in s]
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        # perpendicular offset of the line from origin
        dx, dy = x2 - x1, y2 - y1
        ln = np.hypot(dx, dy) + 1e-6
        off = (x1 * dy - y1 * dx) / ln
        L = ln
        merged = False
        for o in out:
            if min(abs(o['ang'] - ang), 180 - abs(o['ang'] - ang)) < ang_tol and abs(o['off'] - off) < off_tol:
                if L > o['len']:
                    o.update(ang=ang, off=off, len=L, seg=(x1, y1, x2, y2))
                merged = True; break
        if not merged:
            out.append(dict(ang=ang, off=off, len=L, seg=(x1, y1, x2, y2)))
    return out

def detect_edges(rgb):
    L, RL, BL = _chroma(rgb)
    g = np.hypot(cv2.Sobel(RL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(RL, cv2.CV_32F, 0, 1, 7)) \
        + np.hypot(cv2.Sobel(BL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(BL, cv2.CV_32F, 0, 1, 7))
    edm = cv2.dilate((g > np.percentile(g, GRAD_PCT)).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(edm, 1, np.pi / 360, threshold=45, minLineLength=MIN_LEN, maxLineGap=50)
    if lines is None:
        return []
    clusters = _merge_lines(lines.reshape(-1, 4))
    Rm = cv2.medianBlur(rgb[:, :, 0].astype(np.uint8), MEDIAN_K).astype(np.float32)
    Gm = cv2.medianBlur(rgb[:, :, 1].astype(np.uint8), MEDIAN_K).astype(np.float32)
    Bm = cv2.medianBlur(rgb[:, :, 2].astype(np.uint8), MEDIAN_K).astype(np.float32)
    H, W = L.shape
    yy, xx = np.mgrid[0:H, 0:W]
    edges = []
    for c in clusters:
        x1, y1, x2, y2 = c['seg']
        dx, dy = x2 - x1, y2 - y1
        ln = np.hypot(dx, dy) + 1e-6
        nx, ny = -dy / ln, dx / ln                     # unit normal
        d = (xx - x1) * nx + (yy - y1) * ny            # signed perp distance
        # restrict to the segment's extent along the line (+/- a margin)
        tpar = ((xx - x1) * dx + (yy - y1) * dy) / (ln * ln)
        onseg = (tpar > -0.1) & (tpar < 1.1)
        pos = onseg & (d > 4) & (d < 20)
        neg = onseg & (d < -4) & (d > -20)
        if pos.sum() < 300 or neg.sum() < 300:
            continue
        step = {}
        for ch, m in (('R', Rm), ('G', Gm), ('B', Bm)):
            step[ch] = float(np.median(m[pos]) - np.median(m[neg]))
        dL = 0.299 * step['R'] + 0.587 * step['G'] + 0.114 * step['B']
        dchr = abs((step['R'] - dL)) + abs((step['B'] - dL))
        if abs(dL) < STEP_MIN and dchr < STEP_MIN:
            continue
        edges.append(dict(seg=c['seg'], nx=nx, ny=ny, x0=x1, y0=y1, dx=dx, dy=dy, ln=ln,
                          step=step, dL=dL, dchr=dchr, score=abs(dL) + dchr))
    edges.sort(key=lambda e: -e['score'])
    return edges

def apply_correction(rgb, edges, band=BAND):
    H, W = rgb.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = rgb.astype(np.float32).copy()
    for e in edges:
        d = (xx - e['x0']) * e['nx'] + (yy - e['y0']) * e['ny']
        tpar = ((xx - e['x0']) * e['dx'] + (yy - e['y0']) * e['dy']) / (e['ln'] ** 2)
        # along-line window (feather beyond segment ends) so we don't shift unrelated areas
        walong = np.clip(1.5 - np.abs(tpar - 0.5) * 2.0, 0, 1)   # 1 within seg, ->0 past ends
        prof = np.tanh(d / (band * 0.5)) * walong                # -1..+1 membrane, windowed
        for ci, ch in enumerate('RGB'):
            out[:, :, ci] -= 0.5 * e['step'][ch] * prof
    return np.clip(out, 0, 255)

def stf(x):
    v = np.clip(x, 0, 255) / 255.0
    a = np.percentile(v, 4); b = max(np.percentile(v, 94), a + 0.02)
    return (np.clip((v - a) / (b - a), 0, 1) ** 0.55 * 255).astype(np.uint8)

if __name__ == "__main__":
    npix = int(sys.argv[1]) if len(sys.argv) > 1 else 2635
    im = cv2.imread(f"apps/skydata/surveys/dss-clean/Norder4/Dir0/Npix{npix}.webp")
    rgb = im[:, :, ::-1].astype(np.float32)            # RGB
    edges = detect_edges(rgb)
    print("detected %d correctable chroma edges:" % len(edges))
    for e in edges:
        print("  seg%s  dL=%+.1f dR=%+.1f dG=%+.1f dB=%+.1f  score %.1f"
              % (tuple(int(v) for v in e['seg']), e['dL'], e['step']['R'], e['step']['G'], e['step']['B'], e['score']))
    corr = apply_correction(rgb, edges)
    # panels
    before = stf(rgb[:, :, ::-1]); after = stf(corr[:, :, ::-1])
    ov = before.copy()
    for e in edges:
        x1, y1, x2, y2 = [int(v) for v in e['seg']]
        cv2.line(ov, (x1, y1), (x2, y2), (0, 255, 255), 2)
    panel = np.hstack([before, np.full((512, 5, 3), 80, np.uint8), after,
                       np.full((512, 5, 3), 80, np.uint8), ov])
    os.makedirs(SC + "/diag8", exist_ok=True)
    cv2.imwrite(SC + f"/diag8/cseam_{npix}.png", panel)
    print("wrote diag8/cseam_%d.png (before | after | detected-edges)" % npix)
