"""Decisive DC-vs-structure test for a tile's candidate chroma edges.

For each detected straight line, measure the per-channel step across it at a
series of band *distances* from the line:  d in {1.5, 3, 6, 10, 16, 24} px.

  - TRUE plate DC seam  -> step is a DISCONTINUITY at the line, so the measured
    step is already full at d=1.5 and stays ~FLAT as d grows.
  - REAL structure edge (star cloud / dust lane) -> the brightness keeps
    changing away from the line, so the step RAMPS UP with d.

The DC component = the value the profile extrapolates to at d->0 (use the
narrow d=1.5 band). The ramp = (wide - narrow). Print both so we can see, per
edge, how much is a correctable offset vs real structure.
"""
import os, sys, numpy as np, cv2
from chroma_seam import _chroma, _merge_lines, detect_edges
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))

def main(npix):
    im = cv2.imread(f"apps/skydata/surveys/dss-clean/Norder4/Dir0/Npix{npix}.webp")
    rgb = im[:, :, ::-1].astype(np.float32)
    L, RL, BL = _chroma(rgb)
    g = np.hypot(cv2.Sobel(RL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(RL, cv2.CV_32F, 0, 1, 7)) \
        + np.hypot(cv2.Sobel(BL, cv2.CV_32F, 1, 0, 7), cv2.Sobel(BL, cv2.CV_32F, 0, 1, 7))
    edm = cv2.dilate((g > np.percentile(g, 96.5)).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(edm, 1, np.pi / 360, threshold=45, minLineLength=120, maxLineGap=50)
    clusters = _merge_lines(lines.reshape(-1, 4))
    # median-filtered channels for robust step measurement
    Rm = cv2.medianBlur(rgb[:, :, 0].astype(np.uint8), 5).astype(np.float32)
    Gm = cv2.medianBlur(rgb[:, :, 1].astype(np.uint8), 5).astype(np.float32)
    Bm = cv2.medianBlur(rgb[:, :, 2].astype(np.uint8), 5).astype(np.float32)
    H, W = L.shape
    yy, xx = np.mgrid[0:H, 0:W]
    DS = [1.5, 3, 6, 10, 16, 24]
    print(f"=== tile {npix}: step-vs-distance profile (DC=flat, structure=ramp) ===")
    for c in sorted(clusters, key=lambda c: -c['len']):
        x1, y1, x2, y2 = c['seg']
        dx, dy = x2 - x1, y2 - y1
        ln = np.hypot(dx, dy) + 1e-6
        if ln < 100:
            continue
        nx, ny = -dy / ln, dx / ln
        d = (xx - x1) * nx + (yy - y1) * ny
        tpar = ((xx - x1) * dx + (yy - y1) * dy) / (ln * ln)
        onseg = (tpar > 0.0) & (tpar < 1.0)
        ang = np.degrees(np.arctan2(dy, dx)) % 180
        print(f"\n seg(%d,%d,%d,%d) len=%.0f ang=%.0f" % (x1, y1, x2, y2, ln, ang))
        print("   d(px) :   dL    dR    dG    dB   (R-L) (B-L)")
        prof_dL = []
        for dd in DS:
            lo, hi = dd - 1.5, dd + 1.5
            pos = onseg & (d > lo) & (d < hi)
            neg = onseg & (d < -lo) & (d > -hi)
            if pos.sum() < 150 or neg.sum() < 150:
                print(f"   {dd:5.1f} :  (too few px)")
                continue
            s = {ch: float(np.median(m[pos]) - np.median(m[neg])) for ch, m in
                 (('R', Rm), ('G', Gm), ('B', Bm))}
            dL = 0.299 * s['R'] + 0.587 * s['G'] + 0.114 * s['B']
            prof_dL.append((dd, dL))
            print(f"   {dd:5.1f} : %+5.1f %+5.1f %+5.1f %+5.1f  %+5.1f %+5.1f"
                  % (dL, s['R'], s['G'], s['B'], s['R'] - dL, s['B'] - dL))
        if len(prof_dL) >= 2:
            dc = prof_dL[0][1]                 # narrow-band ~ DC component
            wide = prof_dL[-1][1]
            ramp = wide - dc
            verdict = "DC-SEAM (flat)" if abs(ramp) < 0.5 * abs(dc) + 1.0 else "STRUCTURE (ramps)"
            print(f"   -> DC~{dc:+.1f}  wide~{wide:+.1f}  ramp={ramp:+.1f}  => {verdict}")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2635)
