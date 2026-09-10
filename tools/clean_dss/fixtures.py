"""Synthetic 512x512 RGB tiles with ground truth, for TDD of detect/correct.
A 'real nebula' is a smooth low-order field; a 'seam' is a straight
piecewise-constant DC step added on top; stars are bright Gaussians."""
import numpy as np

DASH_PERIOD_PX = 40.0  # px, along-track dash period for streak fixtures

def _smooth_field(rng, amp):
    # sum of a few broad 2D gaussians -> curved, smooth (real-nebula proxy)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    f = np.zeros((512, 512), np.float32)
    for _ in range(rng.integers(2, 4)):
        cx, cy = rng.uniform(0, 512, 2)
        s = rng.uniform(120, 260)
        f += rng.uniform(0.4, 1.0) * np.exp(-((xx-cx)**2 + (yy-cy)**2) / (2*s*s))
    f -= f.min()
    return amp * f / (f.max() + 1e-6)

def _add_stars(img, rng, n=40):
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    for _ in range(n):
        cx, cy = rng.uniform(0, 512, 2)
        pk = rng.uniform(40, 220); s = rng.uniform(0.8, 2.2)
        img += pk * np.exp(-((xx-cx)**2 + (yy-cy)**2) / (2*s*s))[..., None]
    return img

def _base(rng):
    base = np.full((512, 512, 3), 6.0, np.float32)               # dark floor
    neb = _smooth_field(rng, amp=rng.uniform(6, 22))             # real structure
    tint = rng.uniform(0.6, 1.4, 3)
    img = base + neb[..., None] * tint
    img = _add_stars(img, rng)
    img += rng.normal(0, 1.2, img.shape).astype(np.float32)      # noise
    return img

def _coarse_labels(mask512):
    m = mask512[:512, :512].reshape(32, 16, 32, 16).mean((1, 3))
    return (m > 0.5).astype(int)

def make_seam_tile(angle_deg, step_dn, seed=0):
    rng = np.random.default_rng(seed)
    img = _base(rng)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg); nx, ny = np.cos(th), np.sin(th)
    proj = xx*nx + yy*ny
    lo, hi = float(proj.min()), float(proj.max())
    margin = 0.30 * (hi - lo)                                    # keep the seam well inside, both regions non-trivial
    rho = rng.uniform(lo + margin, hi - margin)
    side = (proj > rho).astype(np.float32)                       # half-plane
    img += (step_dn * side)[..., None]                          # per-channel DC step
    gt = {"labels": _coarse_labels(side), "step_dn": float(step_dn)}
    return np.clip(img, 0, 255).astype(np.uint8), gt

def make_clean_tile(seed=0):
    rng = np.random.default_rng(seed)
    img = _base(rng)
    return np.clip(img, 0, 255).astype(np.uint8), {"labels": None}

def make_streak_tile(angle_deg, amp_dn, fwhm=1.5, duty=1.0,
                     mix=(1.0, 0.71, 0.53), seed=0):
    """A clean base tile (fixtures._base) with a thin straight trail added on top.
    The trail has a Gaussian cross-profile of the given FWHM, per-channel amplitude
    amp_dn*mix, and optional along-track dashing (duty<1). Ground truth returns the
    pre-streak `clean` tile and the boolean `mask` = the streak's geometric support
    (cross-profile core, ~1.5 sigma of the line), independent of amp_dn."""
    rng = np.random.default_rng(seed)
    clean = _base(rng)                                          # float32 (512,512,3)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg)
    ux, uy = np.cos(th), np.sin(th)                            # along
    nx, ny = -uy, ux                                           # perpendicular
    cx, cy = 256.0, 256.0
    perp = (xx - cx) * nx + (yy - cy) * ny
    along = (xx - cx) * ux + (yy - cy) * uy
    sigma = max(fwhm / 2.3548, 0.5)
    cross = np.exp(-(perp ** 2) / (2 * sigma * sigma))         # 1.0 on the line
    if duty < 1.0:
        period = DASH_PERIOD_PX
        phase = np.mod(along, period) / period
        cross = cross * (phase < duty)                        # beaded/dashed
    mix = np.asarray(mix, np.float32)
    streak = cross[..., None] * (amp_dn * mix)[None, None, :]
    img = clean + streak
    mask = cross >= (np.exp(-(1.0 ** 2) / 2) * 0.5)           # core within ~1.5 sigma (1.545 sigma) of the line
    gt = {"clean": np.clip(clean, 0, 255).astype(np.uint8),
          "mask": mask,
          "mix": tuple(float(m) for m in mix),
          "amp_dn": float(amp_dn),
          "angle_deg": float(angle_deg)}
    return np.clip(img, 0, 255).astype(np.uint8), gt

def make_curved_ridge_tile(angle_deg, amp_dn, amplitude=10.0, period=120.0, fwhm=2.0,
                           mix=(1.0, 0.9, 0.8), seed=0):
    """A base tile with a THIN but MEANDERING bright ridge (a galaxy edge / nebula
    filament proxy): the ridge oscillates in perp as perp = amplitude*sin(2*pi*along/
    period) instead of hugging a straight line, so no single straight orientation
    captures it persistently and the along-track MEDIAN never concentrates at one
    offset. Returns (img, fit) where `fit` is the STRAIGHT-line (chord) scanner fit a
    detector would report through it -- the discriminator must classify this as NOT a
    trail. With amplitude=10 over a +/-180 span the ridge wanders +/-10 px."""
    rng = np.random.default_rng(seed)
    img = _base(rng)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg)
    ux, uy = np.cos(th), np.sin(th)                            # along
    nx, ny = -uy, ux                                           # perpendicular
    cx, cy = 256.0, 256.0
    perp = (xx - cx) * nx + (yy - cy) * ny
    along = (xx - cx) * ux + (yy - cy) * uy
    sigma = max(fwhm / 2.3548, 0.5)
    ridge_off = amplitude * np.sin(2 * np.pi * along / period)  # meandering bow in perp
    cross = np.exp(-((perp - ridge_off) ** 2) / (2 * sigma * sigma))
    span = 180.0
    cross = cross * (np.abs(along) <= span)
    mixv = np.asarray(mix, np.float32)
    img = img + cross[..., None] * (amp_dn * mixv)[None, None, :]
    img = np.clip(img, 0, 255).astype(np.uint8)
    fit = dict(cx=cx, cy=cy, angle=float(angle_deg % 180),
               u=np.array([ux, uy]), n=np.array([nx, ny]),
               span=(-span, span))
    return img, fit


def make_dense_field_tile(angle_deg, n_line_stars=8, seed=0):
    """A DENSE star field (no coherent thin ridge) with a handful of bright stars that
    happen to sit ON a straight line -- the classic dense-field false positive: a naive
    max-projection sees a bright line, but there is no persistent thin over-density.
    Returns (img, fit) with `fit` the straight line through those on-line stars. The
    discriminator must reject it: the along-track MEDIAN throws the few stars away."""
    rng = np.random.default_rng(seed)
    img = _base(rng)
    img = _add_stars(img, rng, n=120)                         # dense field
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg)
    ux, uy = np.cos(th), np.sin(th)
    nx, ny = -uy, ux
    cx, cy = 256.0, 256.0
    span = 180.0
    # sprinkle a few bright compact stars exactly on the line (along-track outliers)
    for a in np.linspace(-span, span, n_line_stars):
        sx, sy = cx + a * ux, cy + a * uy
        pk = rng.uniform(180, 240); s = rng.uniform(0.9, 1.8)
        img[..., 0] += (pk * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * s * s)))
        img[..., 1] += (0.9 * pk * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * s * s)))
        img[..., 2] += (0.8 * pk * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * s * s)))
    img = np.clip(img, 0, 255).astype(np.uint8)
    fit = dict(cx=cx, cy=cy, angle=float(angle_deg % 180),
               u=np.array([ux, uy]), n=np.array([nx, ny]),
               span=(-span, span))
    return img, fit


def make_color_seam_tile(angle_deg, cast_rgb, seed=0):
    """Like make_seam_tile but injects a per-channel COLOUR cast (cast_rgb) across
    one half-plane -> a colour-block seam. Ground truth = the coarse region mask."""
    rng = np.random.default_rng(seed)
    img = _base(rng)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg); nx, ny = np.cos(th), np.sin(th)
    proj = xx*nx + yy*ny
    lo, hi = float(proj.min()), float(proj.max())
    margin = 0.30 * (hi - lo)
    rho = rng.uniform(lo + margin, hi - margin)
    side = (proj > rho).astype(np.float32)
    cast = np.asarray(cast_rgb, np.float32)
    img += side[..., None] * cast
    gt = {"labels": _coarse_labels(side), "cast_rgb": tuple(float(c) for c in cast_rgb)}
    return np.clip(img, 0, 255).astype(np.uint8), gt
