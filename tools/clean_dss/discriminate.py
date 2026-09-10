"""Trail-vs-DSO discriminator for scanner-detected candidate lines in DSS2 tiles.

The streak scanner (streaks.scan_image) fires on any coherent thin over-density
along a straight line. But not every such line is a satellite/aircraft TRAIL that
should be cleaned: a galaxy's edge-on disk, a nebula filament/ridge, or just a
straight cut through a dense star/dust field also trip it. Cleaning those erases
REAL astronomy, so we need a discriminator that keeps only genuine trails.

PHYSICS (the anchor): a real trail is BALLISTIC. It is a straight line (zero
curvature) and its bright ridge PERSISTS along the whole track at ONE perpendicular
offset. A galaxy disk / nebula filament CURVES or meanders and is wide; a dense
field has no coherent thin over-density on the line at all -- it only fakes a bright
line via a few saturated stars that happen to sit on it.

DECISION METHOD (thinScore, p90 projection): sample the star-suppressed high-pass on
a rotated ROI (along-track x perpendicular) about the scanner fit, then project each
perpendicular offset with the 90th PERCENTILE over the along-track axis. The p90 (not
a median) is the key fix: a real trail may be FAINT and INTERMITTENT (dashed), and a
median-over-track projection hits the dashes' gaps and washes such a trail out -- the
median gate mis-rejected the batch-1-approved faint reals 491/212/236/18. The p90
keeps a ridge that is present even 10-20% of the track, while a wide diffuse DSO
(galaxy/nebula extended source) still projects to a broad hump. From the p90 profile:

    exc       = core (max p90 within |ds|<=1.5) - flank (median p90 over 5<=|ds|<=12)
    fwhm      = full width of the p90 profile above half its peak
    thinScore = exc / (1 + max(0, fwhm - 2))        (on-line excess, thinness-normalised)

The FWHM normalisation is what rejects WIDE diffuse DSOs: a galaxy/nebula ridge is
~28px wide so its thinScore collapses even with a large excess, while a ~2px trail
keeps its excess. Decision: is_trail = detected AND thinScore > THINSCORE_MIN. Note the
policy is AGGRESSIVE-thin: we gate on thinness + on-line excess and do NOT additionally
require straightness, so thin-but-slightly-curved-in-nebulosity trails are also cleaned;
only WIDE diffuse DSOs are rejected.

CALIBRATION (labeled DSS ground truth, PER-FIT over every fit of each order-3 region):
    reject ceiling across ALL fits of every DSO/dense tile = 1.70 (tile 160); the only
    non-trail fits above that are the plate-seam gradient 104 (2.34) and the star-chain
    374 (2.73). Real trails clear it: 227~7.2, 491~98.9, and crucially the faint FRAGMENTED
    real trail 40 whose collinear segments score 3.14/3.82 (its TOP fit is a vertical seam
    at 0.39). THINSCORE_MIN = 2.5 (aggressive) stays above the 1.70 DSO/dense ceiling and
    seam 104 (2.34) but ADMITS star-chain 374 (2.73) -- surfaced for human review, not
    auto-trusted. per-fit gating stays safe for DSO/dense because none reach 2.5.

SECONDARY (reported only, do NOT gate): the legacy median-over-track Radon `sharpness`
and its `prom` (the corrector uses `prom` to lower the support gate for faint reals),
plus the single-line `ridge_rms`. These are computed for inspection/wiring and are NOT
part of the decision.
"""
import numpy as np

from . import streaks_hp as HP

# --- primary Radon-sharpness geometry ---
ANGLE_SPAN_DEG = 8.0       # +/- search around the scanner fit angle (deg)
N_ANGLES = 33              # orientations sampled across the span
PERP_HALF = 14.0           # perpendicular ROI half-extent (px)
PERP_STEP = 0.5            # perpendicular sampling step (px)

# --- decision threshold ---
# thinScore = p90-projection on-line excess, thinness-normalised (see module docstring).
# Calibrated PER-FIT on labeled DSS (over every fit of each order-3 region, not just the
# top fit): the reject ceiling across ALL fits of every DSO/dense tile is 1.70 (tile 160);
# the highest non-trail fits above it are seam 104 (2.34) and star-chain 374 (2.73). Real
# trails clear it (faint fragmented tile 40 at 3.14/3.82; 227~7.2; 491~98.9).
# THINSCORE_MIN = 2.0 (most aggressive, user-selected for empirical review): only 0.3 above
# the 1.70 DSO/dense ceiling, so it admits every borderline non-trail above 2.0 -- seam 104
# (2.34), star-chain 374 (2.73), emission-nebula 206 (2.96), plus anything in [2.0, 2.5).
# These are ALL surfaced in the review gallery for a human exclude/keep call, NOT auto-
# trusted. (3.0 rejects all of them with a 1.3 margin; 2.5 admits 206+374; see git history.)
THINSCORE_MIN = 2.0

# --- decision threshold (legacy, retained for the SECONDARY reported `sharpness`) ---
# The old median-over-track Radon sharpness gate; kept ONLY for back-compat reporting.
# It is no longer the decision feature -- it washed out faint dashed trails.
SHARPNESS_THRESH = 3.0

# --- corroborating single-line ridge RMS (reported only, does NOT gate) ---
RIDGE_THR = 3.0            # high-pass response gate for the ridge centroid
RIDGE_HALF = 12.0         # perpendicular half-extent for the ridge scan (px)


def _bilinear(R, x, y):
    """Bilinear sample of 2D field R at fractional (x, y) (clamped to the border)."""
    h, w = R.shape
    x0 = np.clip(np.floor(x).astype(int), 0, w - 2)
    y0 = np.clip(np.floor(y).astype(int), 0, h - 2)
    fx = x - x0
    fy = y - y0
    return (R[y0, x0] * (1 - fx) * (1 - fy) + R[y0, x0 + 1] * fx * (1 - fy)
            + R[y0 + 1, x0] * (1 - fx) * fy + R[y0 + 1, x0 + 1] * fx * fy)


def _radon_sharpness(resp, fit):
    """Median-over-track Radon sharpness around the fit orientation.

    Returns (sharpness, prom, fwhm, ang_ratio). At each of N_ANGLES orientations
    spanning +/-ANGLE_SPAN_DEG around the fit angle, sample the response on a rotated
    ROI (along-track x perpendicular), take the MEDIAN over the along-track axis to
    get a perpendicular profile, and keep the orientation whose profile has the
    tallest peak-above-median. sharpness = peak prominence / FWHM of that profile.
    """
    cx, cy = fit["cx"], fit["cy"]
    ux, uy = fit["u"]
    ang0 = np.arctan2(uy, ux)
    s0, s1 = fit["span"]
    L = s1 - s0

    ts = np.linspace(-L / 2.0, L / 2.0, int(max(16, min(500, abs(L)))))
    ds = np.arange(-PERP_HALF, PERP_HALF + 0.01, PERP_STEP)
    dstep = ds[1] - ds[0]
    angs = np.deg2rad(np.linspace(-ANGLE_SPAN_DEG, ANGLE_SPAN_DEG, N_ANGLES))

    ang_peaks = []
    profs = []
    for da in angs:
        a = ang0 + da
        u = np.array([np.cos(a), np.sin(a)])
        n = np.array([-np.sin(a), np.cos(a)])
        T, Dd = np.meshgrid(ts, ds)
        X = cx + T * u[0] + Dd * n[0]
        Y = cy + T * u[1] + Dd * n[1]
        pm = np.median(_bilinear(resp, X, Y), axis=1)   # MEDIAN over along-track -> star-robust
        ang_peaks.append(pm.max() - np.median(pm))
        profs.append(pm)
    ang_peaks = np.array(ang_peaks)
    ib = int(np.argmax(ang_peaks))
    prof = profs[ib]
    bg = np.median(prof)
    pk = prof.max() - bg
    ipk = int(np.argmax(prof))
    half = bg + pk / 2.0
    above = prof >= half
    lo = hi = ipk
    while lo > 0 and above[lo - 1]:
        lo -= 1
    while hi < len(above) - 1 and above[hi + 1]:
        hi += 1
    fwhm = (hi - lo + 1) * dstep
    sharpness = pk / max(fwhm, 1e-6)
    ang_ratio = float(ang_peaks.max() / max(np.median(ang_peaks), 1e-6))
    return float(sharpness), float(pk), float(fwhm), ang_ratio


def _thin_score(resp, fit):
    """p90-projection thinScore -- the DECISION feature (see module docstring).

    `resp` is the star-suppressed positive high-pass max-over-channels field
    (HP.response recipe / clip(highpass.max(2),0,None)), the SAME field scan_image
    passes in. Sample it on a rotated ROI (along-track ts x perpendicular ds) about
    the fit, project each perpendicular offset with the 90th PERCENTILE over the
    along-track axis (p90 keeps a faint/dashed ridge a median would wash out), then:
        exc = core (max p90 within |ds|<=1.5) - flank (median p90 over 5<=|ds|<=12)
        fwhm = full width of the p90 profile above half its peak
        thinScore = exc / (1 + max(0, fwhm - 2))
    Returns (thinscore, {"exc_p90":.., "fwhm":..}).
    """
    c = np.array([fit["cx"], fit["cy"]], float)
    u = np.asarray(fit["u"], float)
    n = np.asarray(fit["n"], float)
    s0, s1 = fit["span"]
    ts = np.arange(s0, s1, 1.0)
    ds = np.arange(-14, 14.01, 0.5)
    if ts.size == 0:
        return 0.0, {"exc_p90": 0.0, "fwhm": 99.0}
    M = np.zeros((len(ds), len(ts)))
    for j, t in enumerate(ts):
        b = c + t * u
        M[:, j] = _bilinear(resp, b[0] + ds * n[0], b[1] + ds * n[1])
    p90 = np.percentile(M, 90, axis=1)                     # p90 over along-track
    core = float(p90[np.abs(ds) <= 1.5].max())
    flank = float(np.median(p90[(np.abs(ds) >= 5) & (np.abs(ds) <= 12)]))
    exc = core - flank
    pk = p90.max()
    half = pk * 0.5
    ab = ds[p90 >= half]
    fwhm = float(ab.max() - ab.min()) if ab.size else 99.0
    thinscore = exc / (1.0 + max(0.0, fwhm - 2.0))
    return float(thinscore), {"exc_p90": round(exc, 1), "fwhm": round(fwhm, 1)}


def _ridge_rms(resp, fit):
    """Corroborating (reported only) weighted RMS of the response-weighted perpendicular
    ridge centroid about a robust straight-line fit. Large for curved/meandering DSO
    ridges, small for straight trails. Returns 99.0 if too few ridge points."""
    cx, cy = fit["cx"], fit["cy"]
    uu = np.array(fit["u"], float)
    nn = np.array(fit["n"], float)
    s0, s1 = fit["span"]
    dg = np.arange(-RIDGE_HALF, RIDGE_HALF + 0.01, 0.5)
    tsr = np.arange(np.floor(s0), np.ceil(s1) + 1, 1.0)
    rd, rw, rt = [], [], []
    for t in tsr:
        pr = _bilinear(resp, cx + t * uu[0] + dg * nn[0], cy + t * uu[1] + dg * nn[1])
        if pr.max() > RIDGE_THR:
            w = np.clip(pr - RIDGE_THR, 0, None)
            if w.sum() > 0:
                rd.append((w * dg).sum() / w.sum())
                rw.append(pr.max())
                rt.append(t)
    if len(rd) < 4:
        return 99.0
    rd = np.array(rd)
    rw = np.array(rw)
    rt = np.array(rt)
    A = np.vstack([rt, np.ones_like(rt)]).T
    Wt = rw.copy()
    coef = np.array([0.0, 0.0])
    for _ in range(5):
        sw = np.sqrt(Wt)
        coef, *_ = np.linalg.lstsq(A * sw[:, None], rd * sw, rcond=None)
        res = rd - A @ coef
        sc = np.median(np.abs(res)) * 1.4826 + 1e-6
        Wt = rw * (np.abs(res) < 3 * sc)
    return float(np.sqrt(np.average((rd - A @ coef) ** 2, weights=rw)))


def trail_vs_dso(img, fit, resp=None):
    """REAL ballistic trail (clean it) vs DSO / dense-field false positive (keep it).

    Pure function of a uint8 RGB DSS tile (any square size; the scanner uses 512 tiles
    or the 1024 region stitch) and the scanner fit dict with keys cx, cy, u=[ux,uy]
    along-track unit, n=[nx,ny] perp unit, span=(s0,s1). A None fit (no detection)
    returns is_trail=False.

    DECISION feature: p90-projection `thinscore` (see module docstring).
    Decision: is_trail = detected AND thinscore > THINSCORE_MIN. The legacy Radon
    `sharpness`/`prom`, `ang_ratio` and the single-line `ridge_rms` are computed and
    returned for inspection/wiring (the corrector reads `prom` to lower the support gate
    for faint reals) but DO NOT gate the decision.

    `resp` (the scanner high-pass response, HP.response(img)) may be passed in to avoid
    recomputing it when a caller already has it (e.g. scan_image annotating every
    group); if None it is computed here so the function stays self-contained.

    Returns {"is_trail": bool, "features": {detected, thinscore, exc_p90, fwhm,
    sharpness, prom, ang_ratio, ridge_rms}}. `fwhm` is the thinScore ridge FWHM.
    """
    if fit is None:
        return dict(is_trail=False, features=dict(
            detected=False, thinscore=0.0, exc_p90=0.0, fwhm=99.0,
            sharpness=0.0, prom=0.0, ang_ratio=0.0, ridge_rms=99.0))

    if resp is None:
        resp = HP.response(img)

    thinscore, tinfo = _thin_score(resp, fit)                 # DECISION feature
    sharpness, prom, _sfwhm, ang_ratio = _radon_sharpness(resp, fit)  # secondary (reported)
    ridge_rms = _ridge_rms(resp, fit)                         # secondary (reported)

    is_trail = bool(thinscore > THINSCORE_MIN)
    return dict(is_trail=is_trail, features=dict(
        detected=True, thinscore=float(thinscore), exc_p90=float(tinfo["exc_p90"]),
        fwhm=float(tinfo["fwhm"]), sharpness=float(sharpness), prom=float(prom),
        ang_ratio=float(ang_ratio), ridge_rms=float(ridge_rms)))


def get_fit(big_uint8):
    """Convenience: the top-scoring scanner fit the discriminator expects, or None."""
    from .streaks import scan_image
    groups = scan_image(big_uint8)["groups"]
    if not groups:
        return None
    return max(groups, key=lambda g: g["score"])["fit"]
