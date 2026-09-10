"""Streak corrector for confirmed DSS trail tiles. Removes a satellite/aircraft/scratch
trail by subtracting, per channel, the trail's own perpendicular brightness profile
(a robust median over the line), scaled by the local along-track amplitude. This works
at ANY colour balance -- unlike cross-channel guided reconstruction, it does not assume
a clean guide channel, which real DSS trails never provide (research: red trails bleed
R:G:B ~ 1:0.71:0.53, i.e. >=53% into every channel). Crossing stars survive because the
profile is a median over the line: a star's flux is an along-track outlier that the
median does not capture, so only the trail component is subtracted. See spec 2026-07-11
§3.3 and docs/superpowers/plans/notes/dss-phase2-research/CALIBRATION.md."""
import numpy as np
import cv2
from skimage.feature import peak_local_max
from . import streaks_hp

STRIP_HALF = 14       # profile_subtract corridor half-width (px); also the touched-region footprint


def strip_footprint(fit, size, half=STRIP_HALF):
    """Boolean (size,size) geometric strip the corrector can touch: within +/-half px of
    the fitted line over its span. This is exactly where profile_subtract writes, so the
    guardrails use it as the touched region (nothing changes outside it)."""
    u = np.asarray(fit["u"], np.float32); n = np.asarray(fit["n"], np.float32)
    cx = np.float32(fit["cx"]); cy = np.float32(fit["cy"]); a0, a1 = fit["span"]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rx, ry = xx - cx, yy - cy
    along = rx * u[0] + ry * u[1]
    perp = rx * n[0] + ry * n[1]
    return (np.abs(perp) <= half) & (along >= a0) & (along <= a1)


def streak_support_mask(hp, fit, size, half=5, extend=40, grow_thresh=2.5, dilate=2):
    """Boolean (size,size) corridor mask following the trail's actual support: within
    +/-half px of the fitted line over [span0-extend, span1+extend] where the high-pass
    response exceeds grow_thresh (so it skips dash gaps), dilated by `dilate` px but kept
    inside the corridor so it never balloons off the line. Used to bound the guardrail
    checks and to report the touched region -- the profile subtraction itself works on
    the full line strip, not this mask."""
    u = np.asarray(fit["u"], np.float32); n = np.asarray(fit["n"], np.float32)
    cx = np.float32(fit["cx"]); cy = np.float32(fit["cy"]); a0, a1 = fit["span"]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rx, ry = xx - cx, yy - cy
    along = rx * u[0] + ry * u[1]
    perp = rx * n[0] + ry * n[1]
    corridor = (np.abs(perp) <= half) & (along >= a0 - extend) & (along <= a1 + extend)
    d = np.clip(hp.max(axis=2), 0, None)
    support = corridor & (d > grow_thresh)
    k = np.ones((2 * dilate + 1, 2 * dilate + 1), np.uint8)
    grown = cv2.dilate(support.astype(np.uint8), k).astype(bool)
    return grown & corridor


def _line_grid(field, fit, size, half):
    """Sample a 2D `field` on the (along x perp) grid of the fitted line. Returns
    (vals[T,O] with NaN off-tile, yi[T,O], xi[T,O], ok[T,O], offs[O])."""
    u = np.asarray(fit["u"], float); n = np.asarray(fit["n"], float)
    c = np.array([fit["cx"], fit["cy"]], float)
    a0, a1 = fit["span"]
    ts = np.arange(a0, a1, 1.0)
    offs = np.arange(-half, half + 1)
    pts = c[None, None, :] + ts[:, None, None] * u[None, None, :] + offs[None, :, None] * n[None, None, :]
    X = pts[..., 0]; Y = pts[..., 1]
    ok = (X >= 0) & (X < size - 1) & (Y >= 0) & (Y < size - 1)
    xi = np.clip(X, 0, size - 1).astype(int); yi = np.clip(Y, 0, size - 1).astype(int)
    vals = np.where(ok, field[yi, xi], np.nan)
    return vals, yi, xi, ok, offs


def _star_protect_mask(img, size, star_pct=99.9, star_pad=1, min_distance=3,
                       sat_thr=235.0, sat_pad=2, fit=None, aniso_margin=0.12, aniso_d=4):
    """Boolean (size,size) mask over bright-star cores where the trail clamp is
    suppressed, so a real star sitting ON a bright trail keeps its flux. Parts, UNION-ed:

    - top-`star_pct` luminance peak cores (+/-star_pad) — but if `fit` is given, a peak is
      protected only if it is ROUND, not a trail BEAD: a bead lies on the ridge so its
      luminance stays high ALONG the trail (fit["u"]) and drops off PERPENDICULAR, while a
      round star drops off both ways. A peak with along-ratio minus perp-ratio (sampled at
      +/-aniso_d px) above `aniso_margin` is judged a bead and is NOT protected, so the
      clamp removes the whole trail line including its beads.
    - saturated plateaus (lum >= sat_thr, dilated) — always protected (a flat >=235 core
      peak_local_max may localise off-centre; and a saturated source is a genuine bright
      star, never a faint bead).
    """
    lum = img.astype(np.float32).mean(2)
    thr = float(np.percentile(lum, star_pct))
    peaks = peak_local_max(lum, min_distance=min_distance, threshold_abs=thr)
    prot = np.zeros((size, size), bool)
    if fit is not None and len(peaks):
        u = np.asarray(fit["u"], float); n = np.asarray(fit["n"], float)
        ys, xs = peaks[:, 0], peaks[:, 1]
        pk = np.maximum(lum[ys, xs], 1.0)
        def _ring(vec):
            r = 0.0
            for s in (-aniso_d, aniso_d):
                yy = np.clip(np.round(ys + s * vec[1]).astype(int), 0, size - 1)
                xx = np.clip(np.round(xs + s * vec[0]).astype(int), 0, size - 1)
                r = r + lum[yy, xx]
            return r / 2.0
        is_bead = (_ring(u) - _ring(n)) / pk > aniso_margin           # bright along, dim across = bead
        keep = peaks[~is_bead]
    else:
        keep = peaks
    for (y, x) in keep:
        prot[max(0, y - star_pad):y + star_pad + 1, max(0, x - star_pad):x + star_pad + 1] = True
    sat = lum >= sat_thr
    if sat.any():
        prot |= cv2.dilate(sat.astype(np.uint8), np.ones((2 * sat_pad + 1, 2 * sat_pad + 1), np.uint8)).astype(bool)
    return prot


def _row_mean(vals, colmask):
    """Per-row (along) mean over the selected columns (perp offsets), NaN-safe and
    warning-free: rows with no valid sample return NaN."""
    sel = np.where(colmask[None, :], vals, np.nan)
    cnt = np.sum(~np.isnan(sel), axis=1)
    ssum = np.nansum(sel, axis=1)
    return np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan)


def _line_se(angle_deg, length=9):
    """A line structuring element (uint8) of `length` px at `angle_deg`, for a directional
    opening that keeps trail-elongated support and drops isolated bright pixels."""
    r = (length - 1) // 2
    t = np.deg2rad(angle_deg); dx, dy = np.cos(t), np.sin(t)
    se = np.zeros((length, length), np.uint8)
    for s in range(-r, r + 1):
        x = int(round(length // 2 + s * dx)); y = int(round(length // 2 + s * dy))
        se[y, x] = 1
    return se


def _wall_per_along(chan, fit, size, ts, offs, wing, sky_ch):
    """Local perpendicular WALL background per along-position: median of the RAW channel
    at |offset| >= wing, sampled on the (along x perp) grid. NaN rows fall back to sky."""
    u = np.asarray(fit["u"], float); n = np.asarray(fit["n"], float)
    c = np.array([fit["cx"], fit["cy"]], float)
    pts = c[None, None, :] + ts[:, None, None] * u[None, None, :] + offs[None, :, None] * n[None, None, :]
    X = pts[..., 0]; Y = pts[..., 1]
    ok = (X >= 0) & (X < size - 1) & (Y >= 0) & (Y < size - 1)
    xi = np.clip(np.round(X), 0, size - 1).astype(int); yi = np.clip(np.round(Y), 0, size - 1).astype(int)
    v = np.where(ok, chan[yi, xi], np.nan)
    wm = np.abs(offs) >= wing
    sel = np.where(wm[None, :], v, np.nan)                    # (T, wings)
    valid = np.isfinite(sel).any(axis=1)                     # rows with >=1 wing sample
    wall = np.full(len(ok), float(sky_ch), np.float64)
    if valid.any():
        with np.errstate(invalid="ignore"):
            wall[valid] = np.nanmedian(sel[valid], axis=1)
    return wall


def profile_subtract(img, fit, size, half=STRIP_HALF, wing=9, grow_thresh=2.5, dilate=2,
                     clamp_margin=2.0, span_ext=40.0, star_pct=99.9, star_pad=1,
                     fill_noise=True, noise_cap=6.0):
    """Remove a trail by CLAMPING its support pixels down to the local perpendicular WALL
    background (the trail's true height above local sky), rather than subtracting an
    under-reading high-pass profile — this is what actually takes bright/faint/curved
    trails down to sky. Two things make it safe:

    - SUPPORT GATE: only pixels inside the corridor (+/-half px of the line, span extended
      by `span_ext`) whose star-suppressed high-pass response exceeds `grow_thresh` are
      clamped (dilated by `dilate`). This follows the ACTUAL trail — including curves and
      dashes — and, crucially, does NOT flatten the wide geometric band, so faint diffuse
      structure (nebulosity/small galaxies) that merely lies near the trail is preserved.
    - FLOOR: the clamp target is `max(local wall - clamp_margin, global tile sky)`. The
      per-along local wall preserves broad structure that fills the wings; the global-sky
      floor prevents digging dark holes and prevents the background under a protected
      bead/star from collapsing (which would spuriously RAISE its measured contrast).

    Bright compact sources (`_star_protect_mask`: top-`star_pct` peaks + saturated
    plateaus) are excluded from the clamp so crossing stars keep their flux. Returns the
    cleaned uint8 image. Reworked for curved/faint trails; see CALIBRATION.md."""
    out = img.astype(np.float32).copy()
    prot = _star_protect_mask(img, size, star_pct, star_pad, fit=fit)   # aniso gate: keep round stars, clamp beads
    sky = np.median(img.reshape(-1, 3), axis=0)
    resp = np.clip(streaks_hp.highpass(img).max(2), 0, None)
    u = np.asarray(fit["u"], np.float32); n = np.asarray(fit["n"], np.float32)
    cx = np.float32(fit["cx"]); cy = np.float32(fit["cy"]); a0, a1 = fit["span"]
    a0 -= span_ext; a1 += span_ext
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rx, ry = xx - cx, yy - cy
    along = rx * u[0] + ry * u[1]
    perp = rx * n[0] + ry * n[1]
    corridor = (np.abs(perp) <= half) & (along >= a0) & (along <= a1)
    raw = (corridor & (resp > grow_thresh)).astype(np.uint8)
    # elongation gate: a directional opening along the trail keeps only genuinely
    # elongated support (the trail), dropping isolated bright pixels — a compact star/
    # nebula bump or a dash-gap flicker in the corridor — so they are NOT clamped.
    line = _line_se(fit["angle"], length=9)
    opened = cv2.morphologyEx(raw, cv2.MORPH_OPEN, line)
    support = cv2.dilate(opened, np.ones((2 * dilate + 1, 2 * dilate + 1), np.uint8)).astype(bool)
    support = support & corridor & (~prot)                   # actual trail pixels only, stars excluded
    if support.sum() == 0:
        return out.astype(np.uint8)
    ts = np.arange(a0, a1, 1.0)
    offs = np.arange(-half, half + 1).astype(float)
    al = along[support]
    for ch in range(3):
        chan = out[..., ch]
        wall = _wall_per_along(chan, fit, size, ts, offs, wing, sky[ch])
        floor = np.maximum(np.interp(al, ts, wall) - clamp_margin, sky[ch])
        chan[support] = np.minimum(chan[support], np.maximum(floor, 0.0))
    if fill_noise:
        # the clamp leaves the band unnaturally SMOOTH (mean is right but there is no
        # noise texture, so it reads as a flat streak). Add Gaussian noise matched to the
        # local background: robust sigma from a star-excluded ring just outside the band.
        m8 = support.astype(np.uint8)
        lum = img.astype(np.float32).mean(2)
        star = lum > np.percentile(lum, 99.0)
        ring = (cv2.dilate(m8, np.ones((13, 13), np.uint8)).astype(bool)) & (~support) & (~star)
        rng = np.random.default_rng(int(cx) * 4096 + int(cy))    # deterministic per trail
        npix = int(support.sum())
        for ch in range(3):
            ref = out[..., ch][ring]
            if ref.size > 20:
                sig = float(1.4826 * np.median(np.abs(ref - np.median(ref))))
            else:
                sig = 1.0
            sig = min(max(sig, 0.8), noise_cap)
            out[..., ch][support] += rng.normal(0, sig, npix).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def destreak_image(img, fits, seed=0, grow_thresh=None):
    """Clean every fitted trail in `img` by per-channel profile subtraction. Returns
    (cleaned_uint8, union_mask_bool, info list). `union` is the touched footprint of all
    trails (the exact region profile_subtract can write — used by the guardrails so the
    'change confined to corridor' check sees zero change just outside it); `seed` is
    unused (kept for a stable signature with the seam cleaner).

    `grow_thresh` sets the high-pass support gate passed to profile_subtract. It may be a
    scalar applied to every fit, or a list aligned with `fits` (per-trail; None entries
    keep profile_subtract's default). Lower it (~1.2) for faint-but-real trails whose
    response sits below the default 2.5 gate, so the trail is actually clamped to sky.
    Default None => profile_subtract keeps its own default (2.5), unchanged behaviour."""
    out = img
    size = img.shape[0]
    union = np.zeros((size, size), bool)
    info = []
    for i, fit in enumerate(fits):
        gt = grow_thresh[i] if isinstance(grow_thresh, (list, tuple)) else grow_thresh
        hp = streaks_hp.highpass(out)
        foot = strip_footprint(fit, size)
        if foot.sum() == 0:
            info.append({"method": "skip", "area": 0}); continue
        support = streak_support_mask(hp, fit, size)         # bright trail support (for reporting)
        ps_kw = {} if gt is None else {"grow_thresh": gt}
        out = profile_subtract(out, fit, size, **ps_kw)
        union |= foot
        peaks = [round(float(np.clip(hp[..., c], 0, None)[support].max()), 1) if support.any() else 0.0
                 for c in range(3)]
        info.append({"method": "profile", "area": int(support.sum()), "peak_rgb": peaks})
    return out, union, info
