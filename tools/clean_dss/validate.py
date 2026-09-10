"""Post-clean safety checks. stars_preserved: bright stars keep their position and
their CONTRAST above local background. edge_step: mean abs step across the tile's
own centre column/row (proxy for whether cleaning introduced a new hard
discontinuity)."""
import numpy as np
from skimage.feature import peak_local_max


def _peaks(img, bright_pct):
    lum = img.astype(np.float32).mean(2)
    thr = np.percentile(lum, bright_pct)
    pk = peak_local_max(lum, min_distance=4, threshold_abs=thr)
    return pk, lum


def _local_bg(lum, y, x, r=6):
    y0, y1 = max(0, y - r), min(lum.shape[0], y + r + 1)
    x0, x1 = max(0, x - r), min(lum.shape[1], x + r + 1)
    return float(np.median(lum[y0:y1, x0:x1]))


def stars_preserved(before, after, bright_pct=99.9, max_shift=1.5,
                    max_frac=0.08, min_ok=0.90):
    """True if >= min_ok of the BRIGHT stars keep their position (<= max_shift px)
    and their contrast above local background (within max_frac).

    We check CONTRAST (peak minus local-median background), not absolute flux,
    because a background-leveling repair *intentionally* shifts the sky level under
    stars too — the star still rides the same amount above its surroundings. We use
    only reliably bright peaks (top ~0.1%); faint peaks on 8-bit re-encoded tiles are
    noise-dominated and not a meaningful damage signal."""
    pb, lb = _peaks(before, bright_pct)
    pa, la = _peaks(after, bright_pct)
    if len(pb) == 0:
        return True
    ok = 0
    for (y, x) in pb:
        d = np.hypot(pa[:, 0] - y, pa[:, 1] - x) if len(pa) else np.array([9e9])
        if d.min() > max_shift:
            continue
        j = d.argmin()
        yb, xb = pa[j]
        cb = lb[y, x] - _local_bg(lb, y, x)
        ca = la[yb, xb] - _local_bg(la, yb, xb)
        if abs(ca - cb) <= max_frac * max(cb, 1):
            ok += 1
    return ok >= min_ok * len(pb)


def edge_step(img):
    lum = img.astype(np.float32).mean(2)
    v = abs(lum[:, 256] - lum[:, 255]).mean()
    h = abs(lum[256, :] - lum[255, :]).mean()
    return float(max(v, h))


def streak_cleared(before, after, mask, ksize=31, min_drop=0.4, star_pct=99.9, hot_thresh=3.0):
    """True if the trail's high-pass response dropped by at least min_drop after repair.
    The measurement runs on the actual trail SUPPORT — pixels inside `mask` whose response
    was above hot_thresh before — not the whole (wide) footprint, whose background-
    dominated median is noise-floor-limited for a thin trail. Bright stars are excluded:
    the corrector deliberately leaves stars that cross a trail intact, and those unchanged
    peaks would otherwise mask a genuine reduction. Too little trail signal -> True."""
    import cv2
    def resp(im):
        d = np.zeros(im.shape[:2], np.float32)
        for c in range(3):
            bg = cv2.medianBlur(im[..., c].astype(np.uint8), ksize).astype(np.float32)
            d = np.maximum(d, im[..., c].astype(np.float32) - bg)
        return d
    lb = before.astype(np.float32).mean(2); la = after.astype(np.float32).mean(2)
    star = (lb > np.percentile(lb, star_pct)) | (la > np.percentile(la, star_pct))
    star = cv2.dilate(star.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    rb_map = resp(before)
    hot = mask & ~star & (rb_map > hot_thresh)               # the actual (non-star) trail support
    if hot.sum() < 20:
        return True                                          # negligible trail signal to clean
    rb = float(np.median(rb_map[hot]))
    ra = float(np.median(resp(after)[hot]))
    return ra <= (1.0 - min_drop) * rb + 1e-6


def no_ghost_edges(before, after, mask, band=3, tol=1.5):
    """True if the repair is confined to the corridor: in a thin band just OUTSIDE
    the mask, the mean absolute per-pixel change stays below tol DN (no bleed / no
    corridor-outline 'ghost edge'). Empty band -> True."""
    import cv2
    m8 = mask.astype(np.uint8)
    ring = (cv2.dilate(m8, np.ones((2 * band + 1, 2 * band + 1), np.uint8)).astype(bool)) & (~mask)
    if ring.sum() == 0:
        return True
    diff = np.abs(after.astype(np.float32) - before.astype(np.float32)).mean(2)
    return float(diff[ring].mean()) < tol
