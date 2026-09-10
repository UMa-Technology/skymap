"""Hybrid data-driven seam corrector (geometry-independent, decomposed).

Combines both signals, each gated INDEPENDENTLY on its own step-vs-distance
profile (flat = real DC discontinuity = artifact ; ramp = real structure):

  * luminance DC step (flat) -> level it by an EQUAL-DN subtract from R,G,B.
    Subtracting the same DN from all channels shifts L and leaves EVERY colour
    difference (R-B, R-G) unchanged -> removes a brightness seam, colour intact.
  * R-B DC step (flat), user's idea -> L-conserving R<->B transfer
    (dB = -2.62*dR, G held) -> removes the dead-blue colour cast, L intact.

The two operations are orthogonal (one moves L holding colour, the other moves
colour holding L) so they compose cleanly. A straight edge whose L OR R-B ramps
with distance is real structure and is left alone on that axis.

detect(rgb)  -> list of edges with both profiles + gate flags
apply(rgb,e) -> corrected rgb  (honours an optional keep-out weight `protect`)
CLI: python hybrid_seam.py <npix ...>  -> diag8/hybrid_<npix>.png contact sheet
"""
import os, sys, numpy as np, cv2
from chroma_seam import _chroma, _merge_lines, stf
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))

WL, WG, WB = 0.299, 0.587, 0.114
K = WL / WB                    # 2.623 : dB=-K*dR holds L with G fixed
GRAD_PCT, MIN_LEN = 96.5, 120
NARROW, WIDE = (1.0, 4.0), (14.0, 24.0)
DC_MIN_L, DC_MIN_RB = 5.0, 5.0    # <5 DN "seams" are marginal detections on near-empty
                                  # tiles (imperceptible in-app; only fix clearly-visible blocks)
DC_MAX_L, DC_MAX_RB = 16.0, 16.0    # above this a "flat" step is real structure, not a plate DC seam
FLAT_FRAC_L, FLAT_FRAC_RB, FLAT_ABS = 0.35, 0.35, 2.5   # tight: true DC seam barely ramps
CAP_L, CAP_RB = 16.0, 12.0    # in-range steps are already gate-vetted seams -> level fully
SEAM_MIN_LEN = 160.0           # plate boundaries are long straight lines
MAX_PER_TILE = 3              # a 3.7deg tile crosses <=2 plate boundaries
COLOR_ENABLED = False        # R<->B transfer desaturates real blue regions -> olive
                             # (can't tell a real blue field from a dead-blue cast,
                             #  and casts were already handled by castclean). Luminance
                             #  leveling is self-protecting; keep colour off by default.
MEMB_L, MEMB_RB = 8.0, 12.0    # luminance step sharp; chroma low-freq -> softer

def _band_steps(onseg, d, lo, hi, chans):
    pos = onseg & (d > lo) & (d < hi); neg = onseg & (d < -lo) & (d > -hi)
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
        sN = _band_steps(onseg, d, *NARROW, chans); sW = _band_steps(onseg, d, *WIDE, chans)
        if sN is None or sW is None:
            continue
        dLn = WL * sN['R'] + WG * sN['G'] + WB * sN['B']
        dLw = WL * sW['R'] + WG * sW['G'] + WB * sW['B']
        rbn, rbw = sN['R'] - sN['B'], sW['R'] - sW['B']
        L_flat = abs(dLw - dLn) <= max(FLAT_FRAC_L * abs(dLn), FLAT_ABS)
        RB_flat = abs(rbw - rbn) <= max(FLAT_FRAC_RB * abs(rbn), FLAT_ABS)
        long_enough = ln >= SEAM_MIN_LEN
        do_L = L_flat and DC_MIN_L <= abs(dLn) <= DC_MAX_L and long_enough
        do_RB = COLOR_ENABLED and RB_flat and DC_MIN_RB <= abs(rbn) <= DC_MAX_RB and long_enough
        edges.append(dict(seg=c['seg'], nx=nx, ny=ny, x0=x1, y0=y1, dx=dx, dy=dy, ln=ln,
                          dLn=dLn, dLw=dLw, rbn=rbn, rbw=rbw, do_L=do_L, do_RB=do_RB,
                          cL=float(np.clip(dLn, -CAP_L, CAP_L)),
                          cRB=float(np.clip(rbn, -CAP_RB, CAP_RB))))
    # geometric non-max suppression: the same physical seam is often detected as
    # several near-parallel segments; applying each would STACK the correction
    # (3x -8DN dark bands, 2x colour->olive). Keep the strongest per line-cluster.
    def _angoff(e):
        ang = np.degrees(np.arctan2(e['dy'], e['dx'])) % 180
        off = (e['x0'] * e['dy'] - e['y0'] * e['dx']) / e['ln']
        return ang, off
    active = sorted((e for e in edges if e['do_L'] or e['do_RB']),
                    key=lambda e: -(abs(e['cL']) + abs(e['cRB'])))
    kept = []
    for e in active:
        a1, o1 = _angoff(e)
        if any(min(abs(a1 - a2), 180 - abs(a1 - a2)) < 10 and abs(o1 - o2) < 40
               for a2, o2 in (_angoff(k) for k in kept)):
            e['do_L'] = e['do_RB'] = False          # duplicate line -> drop
        else:
            kept.append(e)
    # per-tile cap: a 3.7deg tile crosses <=2 plate boundaries; keep the longest.
    kept.sort(key=lambda e: -e['ln'])
    for e in kept[MAX_PER_TILE:]:
        e['do_L'] = e['do_RB'] = False
    edges.sort(key=lambda e: -(abs(e['dLn']) * e['do_L'] + abs(e['rbn']) * e['do_RB']))
    return edges

def apply(rgb, edges, protect_color=None):
    """Luminance leveling is UNGATED (its flat-gate already excludes real
    structure -- real DSO edges ramp, so do_L is only True on flat DC seams,
    and an equal-DN shift preserves all texture+colour). The colour transfer
    CAN desaturate real nebula colour, so it is gated by protect_color."""
    H, W = rgb.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = rgb.astype(np.float32).copy()
    keep_c = 1.0 if protect_color is None else (1.0 - protect_color.astype(np.float32))
    for e in edges:
        if not (e['do_L'] or e['do_RB']):
            continue
        d = (xx - e['x0']) * e['nx'] + (yy - e['y0']) * e['ny']
        tpar = ((xx - e['x0']) * e['dx'] + (yy - e['y0']) * e['dy']) / (e['ln'] ** 2)
        walong = np.clip(1.5 - np.abs(tpar - 0.5) * 2.0, 0, 1)
        if e['do_L']:
            c = 0.5 * e['cL'] * np.tanh(d / (MEMB_L * 0.6)) * walong
            out[:, :, 0] -= c; out[:, :, 1] -= c; out[:, :, 2] -= c
        if e['do_RB']:
            prof = np.tanh(d / (MEMB_RB * 0.6)) * walong * keep_c
            dR = (-0.5 * e['cRB'] * prof) / (1.0 + K)
            out[:, :, 0] += dR; out[:, :, 2] += -K * dR
    return np.clip(out, 0, 255)

# ---- robust single-tile correction (used by the batch) ---------------------
def _raw_rgb(src_dir, npix):
    import cv2
    im = cv2.imread(f"{src_dir}/Norder4/Dir{(npix // 10000) * 10000}/Npix{npix}.webp")
    return im[:, :, ::-1].astype(np.float32)

def correct_tile(order, npix, src_dir, apron=64, use_protect=True):
    """Detect+correct one tile. Uses the real-neighbour apron for cross-tile
    consistency ONLY when its central 512 matches the raw tile (assemble has a
    face-boundary bug that corrupts the centre on ~10% of tiles); otherwise
    falls back to the bare raw tile. A final delta-clamp guarantees the written
    tile never deviates from the raw tile by more than the correction caps."""
    import apron as apron_mod, assemble
    assemble.RAW = src_dir
    raw = _raw_rgb(src_dir, npix)                               # ground-truth tile (RGB)
    a = apron
    clean, sub = False, None
    try:
        sub, _ = apron_mod.assemble_apron(order, npix, apron)
        sub = sub[:, :, :3].astype(np.float32)
        clean = float(np.abs(sub[a:a + 512, a:a + 512] - raw).max()) < 2.0
    except Exception:
        clean = False
    frame, off = (sub, a) if clean else (raw, 0)               # 640 apron or bare 512
    edges = detect(frame)
    active = [e for e in edges if e['do_L'] or e['do_RB']]
    if not active:
        return None, edges
    prot = None
    if use_protect and any(e['do_RB'] for e in active):
        from protect_mask import protect_mask
        tile = frame[off:off + 512, off:off + 512]
        pm, _ = protect_mask(tile, frame if clean else None)
        pf = cv2.GaussianBlur(pm.astype(np.float32), (0, 0), 3.0)
        pf[pm] = 1.0                       # bit-exact 0 colour change inside protection
        prot = np.zeros(frame.shape[:2], np.float32)
        prot[off:off + 512, off:off + 512] = pf
    corr = apply(frame, edges, protect_color=prot)
    out = corr[off:off + 512, off:off + 512]
    delta = np.clip(out - raw, -(CAP_L + CAP_RB + 4), CAP_L + CAP_RB + 4)  # safety net
    return np.clip(raw + delta, 0, 255), edges

if __name__ == "__main__":
    npixs = [int(x) for x in sys.argv[1:]] or [2635]
    import apron as apron_mod, assemble
    assemble.RAW = "apps/skydata/surveys/dss-clean"
    rows = []
    for npix in npixs:
        sub, _ = apron_mod.assemble_apron(4, npix, 64)
        rgb = sub[:, :, :3].astype(np.float32)
        edges = detect(rgb)
        corr, _ = correct_tile(4, npix, "apps/skydata/surveys/dss-clean", use_protect=False)
        a = 64
        before = stf(rgb[a:a + 512, a:a + 512][:, :, ::-1])
        after = before.copy() if corr is None else stf(corr[:, :, ::-1])
        nL = sum(e['do_L'] for e in edges); nC = sum(e['do_RB'] for e in edges)
        cv2.putText(before, "t%d" % npix, (6, 22), 0, 0.7, (0, 255, 255), 2)
        cv2.putText(after, "L:%d C:%d" % (nL, nC), (6, 22), 0, 0.7, (0, 255, 255), 2)
        rows.append(np.hstack([before, np.full((512, 4, 3), 80, np.uint8), after]))
        print("t%d: %d edges, %d level-L, %d transfer-RB  %s"
              % (npix, len(edges), nL, nC,
                 " ".join("[%s dL%+.0f rb%+.0f%s%s]" % (
                     ",".join(str(int(v)) for v in e['seg']), e['dLn'], e['rbn'],
                     " L" if e['do_L'] else "", " C" if e['do_RB'] else "")
                     for e in edges if e['do_L'] or e['do_RB'])))
    sheet = np.vstack([np.hstack([r, np.full((512, 4, 3), 80, np.uint8)]) if False else r for r in rows]) \
        if len(rows) == 1 else np.vstack([np.pad(r, ((0, 6), (0, 0), (0, 0)), constant_values=80) for r in rows])
    os.makedirs(SC + "/diag8", exist_ok=True)
    cv2.imwrite(SC + "/diag8/hybrid_sheet.png", sheet)
    print("wrote diag8/hybrid_sheet.png")
