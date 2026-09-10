"""TDD for the trail-vs-DSO discriminator (tools/clean_dss/discriminate.py).

Physics: a REAL trail is a thin ridge that persists along the whole track at ONE
perpendicular offset (ballistic, straight) -- but a real trail may be FAINT and
INTERMITTENT (dashed). A DSO (galaxy edge / nebula filament) is WIDE/diffuse. The
decision feature is `thinScore`: an excess-of-core-over-flank measured on a
p90 (90th-percentile) along-track projection of the star-suppressed high-pass,
normalised by the ridge FWHM. The p90 (not the median) is the key: it keeps a
faint DASHED trail that a MEDIAN projection would wash out, while a wide diffuse
DSO scores near zero (its FWHM is huge so the normalisation kills it).

Rule: is_trail = detected AND thinScore > THINSCORE_MIN (3.0). Synthetic fixtures
(fast, no survey tree): straight streak -> True; wide diffuse blob -> False; a
DASHED thin streak (the exact failure mode of the old median gate) -> True.
Real-tile integration asserts run only if the DSS survey tree is present.
"""
import os

import numpy as np
import pytest

from tools.clean_dss import discriminate
from tools.clean_dss import streaks_hp as HP
from tools.clean_dss.discriminate import trail_vs_dso, THINSCORE_MIN
from tools.clean_dss.fixtures import make_streak_tile


# ----------------------------- synthetic (always run) -----------------------------

def test_no_detection_is_not_a_trail():
    out = trail_vs_dso(np.zeros((64, 64, 3), np.uint8), None)
    assert out["is_trail"] is False
    assert out["features"]["detected"] is False


def test_straight_streak_is_a_trail():
    img, _ = make_streak_tile(angle_deg=20, amp_dn=55.0, fwhm=2.0, mix=(1.0, 0.71, 0.53), seed=1)
    fit = discriminate.get_fit(img)
    assert fit is not None, "scanner should detect the straight trail"
    out = trail_vs_dso(img, fit)
    assert out["is_trail"] is True
    assert out["features"]["thinscore"] > THINSCORE_MIN


def _wide_blob_tile(angle_deg=35.0, amp_dn=60.0, fwhm=28.0, seed=2):
    """A WIDE diffuse extended source (galaxy/nebula proxy): a broad Gaussian ridge with
    FWHM ~28px (>> a trail's ~2px). It trips the scanner's straight-line fit but must be
    KEPT -- its huge FWHM drives thinScore near zero. Returns (img, fit)."""
    rng = np.random.default_rng(seed)
    from tools.clean_dss.fixtures import _base
    img = _base(rng)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg)
    ux, uy = np.cos(th), np.sin(th)
    nx, ny = -uy, ux
    cx, cy = 256.0, 256.0
    perp = (xx - cx) * nx + (yy - cy) * ny
    along = (xx - cx) * ux + (yy - cy) * uy
    sigma = fwhm / 2.3548
    span = 180.0
    cross = np.exp(-(perp ** 2) / (2 * sigma * sigma)) * (np.abs(along) <= span)
    img = img + cross[..., None] * (amp_dn * np.asarray((1.0, 0.9, 0.8), np.float32))[None, None, :]
    img = np.clip(img, 0, 255).astype(np.uint8)
    fit = dict(cx=cx, cy=cy, angle=float(angle_deg % 180),
               u=np.array([ux, uy]), n=np.array([nx, ny]), span=(-span, span))
    return img, fit


def test_wide_diffuse_blob_is_not_a_trail():
    img, fit = _wide_blob_tile()
    out = trail_vs_dso(img, fit)
    assert out["is_trail"] is False
    assert out["features"]["thinscore"] <= THINSCORE_MIN
    assert out["features"]["fwhm"] > 6.0            # genuinely wide


def _dashed_streak_tile(angle_deg=20.0, amp_dn=55.0, fwhm=2.0, seed=1, period=50, duty=0.4):
    """A thin straight trail that is DASHED: ~60% of its length is zeroed in periodic
    along-track chunks (duty=0.4 kept). This is the exact failure mode of the OLD
    median-over-track gate -- the along-track median at the ridge offset sits in a dash
    gap most of the time and washes the ridge out -- but a p90 projection keeps it, so
    thinScore stays high. Returns (img, fit) with `fit` the straight-line geometry (the
    scanner's Hough linker drops these coarse dashes, so we hand it the true fit exactly
    as the wide/dense fixtures do; the point under test is the discriminator, not Hough)."""
    img, gt = make_streak_tile(angle_deg=angle_deg, amp_dn=amp_dn, fwhm=fwhm,
                               mix=(1.0, 0.71, 0.53), seed=seed)
    clean = gt["clean"].astype(np.float32)
    streak = img.astype(np.float32) - clean
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    th = np.deg2rad(angle_deg)
    ux, uy = np.cos(th), np.sin(th)
    nx, ny = -uy, ux
    along = (xx - 256.0) * ux + (yy - 256.0) * uy
    keep = (np.mod(along, period) / period) < duty     # periodic along-track dashes
    dashed = clean + streak * keep[..., None]
    span = 240.0
    fit = dict(cx=256.0, cy=256.0, angle=float(angle_deg % 180),
               u=np.array([ux, uy]), n=np.array([nx, ny]), span=(-span, span))
    return np.clip(dashed, 0, 255).astype(np.uint8), fit


def _old_median_sharpness(img, fit):
    """The OLD decision feature (median-over-track Radon sharpness) for the regression
    contrast -- proves the dashed trail would have been mis-rejected by the old gate."""
    resp = HP.response(img)
    sharp, _prom, _fwhm, _ar = discriminate._radon_sharpness(resp, fit)
    return sharp


def test_dashed_trail_is_a_trail_regression():
    # The critical regression: a faint intermittent trail the old median gate washed out.
    img, fit = _dashed_streak_tile()
    out = trail_vs_dso(img, fit)
    assert out["is_trail"] is True                       # p90 keeps it
    assert out["features"]["thinscore"] > THINSCORE_MIN
    # and the OLD median-sharpness gate would have (near-)rejected it: p90 >> median here.
    old = _old_median_sharpness(img, fit)
    assert out["features"]["thinscore"] > old, (
        f"thinScore ({out['features']['thinscore']:.1f}) must beat the old median "
        f"sharpness ({old:.1f}) on a dashed trail")


def test_straight_beats_wide_in_thinscore():
    s_img, _ = make_streak_tile(angle_deg=20, amp_dn=55.0, fwhm=2.0, seed=1)
    s_fit = discriminate.get_fit(s_img)
    w_img, w_fit = _wide_blob_tile()
    s = trail_vs_dso(s_img, s_fit)["features"]["thinscore"]
    w = trail_vs_dso(w_img, w_fit)["features"]["thinscore"]
    assert s > w


def _ridge_resp(exc, sigma=0.85, size=256, flank=0.0):
    """A star-suppressed high-pass response field (as scan_image passes to trail_vs_dso)
    holding ONE thin horizontal ridge of core-over-flank excess `exc` and width ~2*sigma.
    With no along-track dashing the p90 projection == the ridge value, so thinScore ~= exc
    for a ~2px FWHM ridge -- letting us land a value in the (3.0, 4.0) band."""
    yy = np.arange(size)[:, None].astype(np.float32)
    prof = flank + exc * np.exp(-((yy - size / 2.0) ** 2) / (2 * sigma * sigma))
    return np.repeat(prof, size, axis=1)


def _horiz_fit(size=256, span=80.0):
    return dict(cx=size / 2.0, cy=size / 2.0, angle=0.0,
                u=np.array([1.0, 0.0]), n=np.array([0.0, 1.0]), span=(-span, span))


def test_threshold_is_2_0():
    assert THINSCORE_MIN == 2.0


def test_thinscore_in_new_2_0_to_3_band_is_a_trail_now():
    """A fit whose thinScore lands in (2.0, 3.0) is is_trail=True at the most-aggressive 2.0
    gate -- it would have been REJECTED at 3.0. This band the user opted into for empirical
    review; it also admits borderline non-trails (seam 104 ~2.34, star-chain 374 ~2.73,
    nebula 206 ~2.96), all flagged in the gallery for a human keep/exclude call."""
    img = np.zeros((256, 256, 3), np.uint8)
    out = trail_vs_dso(img, _horiz_fit(), resp=_ridge_resp(exc=2.4))
    ts = out["features"]["thinscore"]
    assert 2.0 < ts < 3.0, f"expected thinscore in (2.0, 3.0), got {ts:.2f}"
    assert out["is_trail"] is True                       # admitted at 2.0, was rejected at 3.0


def test_dso_dense_ceiling_below_2_0_is_not_a_trail():
    """A fit whose thinScore sits at the measured DSO/dense ceiling (1.70, tile 160) stays
    is_trail=False -- even the most-aggressive 2.0 gate keeps its (thin) 0.3 margin above
    every galaxy/nebula/dense-field fit."""
    img = np.zeros((256, 256, 3), np.uint8)
    out = trail_vs_dso(img, _horiz_fit(), resp=_ridge_resp(exc=1.7))
    assert out["features"]["thinscore"] < 2.0
    assert out["is_trail"] is False


def test_features_shape_and_keys():
    img, _ = make_streak_tile(angle_deg=20, amp_dn=55.0, seed=1)
    fit = discriminate.get_fit(img)
    out = trail_vs_dso(img, fit)
    # primary + secondary (sharpness/prom kept for reporting + the faint-trail grow gate)
    for k in ("detected", "thinscore", "exc_p90", "fwhm", "sharpness", "prom"):
        assert k in out["features"]
    assert isinstance(out["is_trail"], bool)


# --------------------------- real-tile integration -------------------------------
# The DSS survey tree (order-4 webp children) is large and may be absent; skip then.

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Pinned DIRTY-tile fixtures (order-4 children of the tiles these tests exercise), extracted
# from git before the survey tree was cleaned. Real-tile asserts must run against a tile that
# still contains its trail; the live survey tree gets those trails cleaned out, so we decouple.
_SRC = os.path.join(_REPO, "tools/tests/fixtures/dss_dirty")


def _have_tree(parent):
    return all(os.path.exists(f"{_SRC}/Norder4/Dir0/Npix{4 * parent + k}.webp") for k in range(4))


def _stitch(parent):
    import importlib.util
    from tools.clean_dss.io import load_rgb  # noqa: F401 (ensures package importable)
    spec = importlib.util.spec_from_file_location("cds", os.path.join(_REPO, "tools/clean-dss-survey.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    kids = [4 * parent + k for k in range(4)]
    return m._stitch_children([f"{_SRC}/Norder4/Dir0/Npix{c}.webp" for c in kids])


@pytest.mark.parametrize("parent,expected", [
    (227, True),    # the hard faint REAL trail -> must clean
    (491, True),    # batch-1-approved faint trail the old median gate mis-rejected
    (338, False),   # nebula -> must keep
    (594, False),   # the hard nebula (worst DSO) -> must keep
    (592, False),   # nebula -> must keep
])
def test_real_tiles(parent, expected):
    if not _have_tree(parent):
        pytest.skip(f"DSS survey tree absent for region {parent}")
    big = _stitch(parent)
    fit = discriminate.get_fit(big)
    out = trail_vs_dso(big, fit)
    assert out["is_trail"] is expected, (
        f"region {parent}: thinscore={out['features']['thinscore']:.2f} "
        f"expected is_trail={expected}")
