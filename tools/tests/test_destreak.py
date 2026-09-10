import numpy as np
import pytest
from tools.clean_dss.fixtures import make_streak_tile
from tools.clean_dss import streaks_hp as HP
from tools.clean_dss.destreak import (streak_support_mask, strip_footprint, _star_protect_mask,
                                      _line_grid, profile_subtract, destreak_image)
from tools.clean_dss.validate import stars_preserved, no_ghost_edges


def _fit_from_gt(gt):
    th = np.deg2rad(gt["angle_deg"])
    u = np.array([np.cos(th), np.sin(th)])
    return {"cx": 256.0, "cy": 256.0, "angle": gt["angle_deg"],
            "u": u, "n": np.array([-u[1], u[0]]), "span": (-256.0, 256.0)}


# ---- support mask (bounds the guardrails / union region) -------------------------

def test_support_mask_covers_the_streak_and_stays_thin():
    img, gt = make_streak_tile(angle_deg=20, amp_dn=45.0, fwhm=1.5, mix=(1.0, 0.5, 0.1), seed=1)
    hp = HP.highpass(img)
    m = streak_support_mask(hp, _fit_from_gt(gt), size=512)
    recall = (m & gt["mask"]).sum() / max(gt["mask"].sum(), 1)
    assert recall > 0.85
    assert m.mean() < 0.06                       # stays in a narrow corridor


def test_support_mask_follows_dashes_not_the_bare_corridor():
    # the support term must follow the actual signal: on a dashed trail the mask is
    # materially sparser than the bare geometric corridor (grow_thresh below noise floor).
    img, gt = make_streak_tile(angle_deg=0, amp_dn=45.0, fwhm=1.5, duty=0.4,
                               mix=(1.0, 0.5, 0.1), seed=5)
    hp = HP.highpass(img)
    fit = _fit_from_gt(gt)
    m = streak_support_mask(hp, fit, size=512)
    corridor = streak_support_mask(hp, fit, size=512, grow_thresh=-1.0)   # always-true => bare corridor
    assert m.sum() < 0.8 * corridor.sum()
    assert (m & gt["mask"]).sum() / max(gt["mask"].sum(), 1) > 0.75


# ---- profile subtraction (the fill primitive) -----------------------------------

@pytest.mark.parametrize("mix,label", [((1.0, 0.3, 0.05), "clean"),
                                       ((1.0, 0.6, 0.2), "mid"),
                                       ((1.0, 0.71, 0.53), "real-red")])
def test_profile_subtract_reduces_streak_at_any_contamination(mix, label):
    # the whole point of profile subtraction: it does NOT depend on a clean guide, so it
    # removes the dominant-channel trail at every colour balance (guided reconstruction
    # actively worsened the real-red case -- see CALIBRATION.md).
    img, gt = make_streak_tile(angle_deg=15, amp_dn=48.0, fwhm=1.5, mix=mix, seed=9)
    fit = _fit_from_gt(gt)
    out = profile_subtract(img, fit, size=512)
    union = streak_support_mask(HP.highpass(img), fit, 512)
    clean = gt["clean"].astype(float)
    before = np.abs(img[..., 0].astype(float) - clean[..., 0])[union].mean()
    after = np.abs(out[..., 0].astype(float) - clean[..., 0])[union].mean()
    assert after < 0.6 * before, f"{label}: red residual ratio {after / before:.2f} not < 0.6"


def test_profile_subtract_preserves_a_crossing_star():
    # a bright star sits ON a real-contamination red trail; it must survive (profile is a
    # median over the line, so the star's flux is not part of what gets subtracted).
    img, gt = make_streak_tile(angle_deg=0, amp_dn=48.0, fwhm=1.5, mix=(1.0, 0.71, 0.53), seed=9)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    star = 230.0 * np.exp(-(((xx - 300) ** 2 + (yy - 256) ** 2) / (2 * 1.4 ** 2)))   # on the y=256 line
    dirty = np.clip(img.astype(np.float32) + star[..., None], 0, 255).astype(np.uint8)
    clean_with_star = np.clip(gt["clean"].astype(np.float32) + star[..., None], 0, 255).astype(np.uint8)
    out = profile_subtract(dirty, _fit_from_gt(gt), size=512)
    # star core still clearly a bright star (dims only slightly from removing the trail under it)
    assert out[256, 300].max() > 210
    # position/contrast preserved per the guardrail
    assert stars_preserved(clean_with_star, out)


def test_profile_subtract_keeps_star_colour_on_a_bright_red_trail():
    # a WHITE star on a RED-dominant BRIGHT trail must keep ALL THREE channels. An
    # aggressive approach that strips R/G to collapse the trail (leaving a dark-blue
    # speck) passes the contrast-only stars_preserved boolean but destroys the star's
    # colour — this guards against that regression (bright trails removed by amp_cap up
    # to 3.5 must not eat the crossing star's red/green).
    img, gt = make_streak_tile(angle_deg=0, amp_dn=95.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=4)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    star = 205.0 * np.exp(-(((xx - 256) ** 2 + (yy - 256) ** 2) / (2 * 1.6 ** 2)))   # white star on the trail
    dirty = np.clip(img.astype(np.float32) + star[..., None], 0, 255).astype(np.uint8)
    out = profile_subtract(dirty, _fit_from_gt(gt), size=512)
    r, g, b = (int(v) for v in out[256, 256])
    assert min(r, g, b) > 150        # star stays a bright WHITE point in every channel


def test_profile_subtract_removes_bright_trail_line_keeps_saturated_star():
    # the local-wall clamp must collapse a BRIGHT trail's on-line core to near the local
    # sky. CONFIRMED aggressive policy: the whole trail LINE goes (beads + non-saturated
    # mid/faint stars on it), but a SATURATED bright star on the trail is kept.
    img, gt = make_streak_tile(angle_deg=0, amp_dn=140.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=2)
    fit = _fit_from_gt(gt)
    out = profile_subtract(img, fit, size=512)

    def core_wall(im):
        rv, _, _, _, offs = _line_grid(im[..., 0].astype(float), fit, 512, 8)   # dominant = R
        c = np.nanmedian(np.where((np.abs(offs) <= 1)[None, :], rv, np.nan))
        w = np.nanmedian(np.where(((np.abs(offs) > 6) & (np.abs(offs) <= 8))[None, :], rv, np.nan))
        return float(c - w)

    assert core_wall(out) < 0.5 * core_wall(img)   # on-line trail collapsed toward sky

    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    def with_star(peak, x0):
        st = peak * np.exp(-(((xx - x0) ** 2 + (yy - 256) ** 2) / (2 * 1.5 ** 2)))   # round star on the y=256 trail
        return np.clip(img.astype(np.float32) + st[..., None], 0, 255).astype(np.uint8)
    assert profile_subtract(with_star(300, 300), fit, 512)[256, 300].max() >= 250   # saturated star kept
    assert profile_subtract(with_star(90, 340), fit, 512)[256, 340].max() < 70      # non-saturated star removed with the line


def test_star_protection_shields_a_star_on_a_bright_trail():
    # a star on a BRIGHT trail would be over-dimmed without star protection (the trail
    # inflates the local amplitude estimate). Protection suppresses subtraction at the
    # star core; a huge star_pad (protect nothing extra is impossible, so instead compare
    # against pad=0 which barely shields it) dims the star more.
    img, gt = make_streak_tile(angle_deg=0, amp_dn=95.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=4)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    star = 205.0 * np.exp(-(((xx - 256) ** 2 + (yy - 256) ** 2) / (2 * 1.6 ** 2)))   # on the y=256 trail
    dirty = np.clip(img.astype(np.float32) + star[..., None], 0, 255).astype(np.uint8)
    clean_with_star = np.clip(gt["clean"].astype(np.float32) + star[..., None], 0, 255).astype(np.uint8)
    protected = profile_subtract(dirty, _fit_from_gt(gt), size=512)                  # star_pct=99.9, pad=2
    narrow = profile_subtract(dirty, _fit_from_gt(gt), size=512, star_pad=0)          # only the exact core
    # the wider protection keeps the star's wings brighter than a bare-core shield...
    assert protected[254:259, 254:259].max() >= narrow[254:259, 254:259].max()
    assert protected[256, 256].max() > 180                                           # star clearly survives
    assert stars_preserved(clean_with_star, protected)                               # guardrail passes


def test_profile_subtract_makes_no_dark_hole_in_dash_gaps():
    # the aggressive clamp may lightly touch a dash-gap pixel that carries real response,
    # but it must NEVER dig a gap below the local sky (no dark scar between beads).
    img, gt = make_streak_tile(angle_deg=0, amp_dn=48.0, fwhm=1.5, duty=0.4,
                               mix=(1.0, 0.71, 0.53), seed=5)
    out = profile_subtract(img, _fit_from_gt(gt), size=512)
    sky = np.median(img.reshape(-1, 3), axis=0)              # per-channel tile sky
    for x in (284, 324, 364):                                # gap centres along y=256
        assert (out[256, x].astype(float) >= sky - 2).all()  # never driven below sky


def test_profile_subtract_fills_cleaned_band_with_matched_noise():
    # the clamp alone leaves the band unnaturally SMOOTH (a flat streak); the noise fill
    # restores background-like texture so it blends. Deterministic per trail.
    img, gt = make_streak_tile(angle_deg=15, amp_dn=100.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=3)
    fit = _fit_from_gt(gt)
    flat = profile_subtract(img, fit, 512, fill_noise=False)
    filled = profile_subtract(img, fit, 512, fill_noise=True)
    band = np.abs(flat.astype(float) - img.astype(float)).max(2) > 2
    assert flat[..., 0][band].astype(float).std() < 1.0     # clamp-only band is too smooth
    assert filled[..., 0][band].astype(float).std() > 2.0   # noise fill restores texture
    assert np.array_equal(filled, profile_subtract(img, fit, 512, fill_noise=True))  # deterministic


def test_profile_subtract_preserves_off_ridge_nebula():
    # the support gate + elongation opening must NOT flatten the wide corridor band: a
    # smooth nebula that merely lies near the trail (off its ridge) is preserved (this is
    # the rectangular-scar regression — a blanket ±half clamp would fail it).
    img, gt = make_streak_tile(angle_deg=0, amp_dn=90.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=8)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    neb = 40.0 * np.exp(-(((xx - 256) ** 2 + (yy - 220) ** 2) / (2 * 22.0 ** 2)))   # blob ~36px off the y=256 line
    dirty = np.clip(img.astype(np.float32) + neb[..., None] * np.array([0.6, 0.8, 1.0]), 0, 255).astype(np.uint8)
    out = profile_subtract(dirty, _fit_from_gt(gt), size=512)
    # the nebula blob centre (well off the trail ridge) is essentially untouched
    assert np.abs(out[220, 256].astype(float) - dirty[220, 256].astype(float)).max() < 4.0


@pytest.mark.parametrize("angle", [20, 45, 63, 100, 135])
def test_profile_subtract_no_aliasing_on_diagonal_trails(angle):
    # per-pixel (interpolated) subtraction must not over-subtract on off-axis trails.
    # The old rotated-unit-grid scatter aliased: ~15% of touched pixels double-subtracted
    # (residual < -8 DN, digging below true background). Per-pixel touches each once, so
    # only a small residual near bright-star wings remains (< 8%, cosmetic + hidden by the
    # star); the aliasing comb (~15%) would fail this bound.
    img, gt = make_streak_tile(angle_deg=angle, amp_dn=60.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=9)
    fit = _fit_from_gt(gt)
    out = profile_subtract(img, fit, size=512)
    touched = strip_footprint(fit, 512) & ~_star_protect_mask(img, 512)   # excludes kept star cores
    resid = (out[..., 0].astype(float) - gt["clean"][..., 0].astype(float))[touched]
    assert (resid < -8).mean() < 0.08        # no over-subtraction comb (aliasing would give ~0.15)


def test_no_ghost_edges_holds_for_a_wide_trail():
    # guardrail union is the actual footprint (half=STRIP_HALF), so the "just outside"
    # ring sees zero change even for a wide/bloomed trail whose profile reaches offset 6-8.
    img, gt = make_streak_tile(angle_deg=20, amp_dn=150.0, fwhm=8.0, mix=(1.0, 0.6, 0.2), seed=2)
    cleaned, union, _ = destreak_image(img, [_fit_from_gt(gt)])
    assert no_ghost_edges(img, cleaned, union)


# ---- orchestrator ----------------------------------------------------------------

def test_destreak_image_reduces_trail_and_returns_union():
    img, gt = make_streak_tile(angle_deg=15, amp_dn=48.0, fwhm=1.5, mix=(1.0, 0.71, 0.53), seed=9)
    cleaned, union, info = destreak_image(img, [_fit_from_gt(gt)])
    assert cleaned.shape == img.shape and cleaned.dtype == np.uint8
    assert union.dtype == bool and union.sum() > 0
    assert info and info[0]["method"] == "profile" and info[0]["area"] > 0
    clean = gt["clean"].astype(float)
    before = np.abs(img[..., 0].astype(float) - clean[..., 0])[union].mean()
    after = np.abs(cleaned[..., 0].astype(float) - clean[..., 0])[union].mean()
    assert after < 0.6 * before


def test_destreak_image_no_fits_is_a_noop():
    img, gt = make_streak_tile(angle_deg=15, amp_dn=48.0, seed=3)
    cleaned, union, info = destreak_image(img, [])
    assert np.array_equal(cleaned, img) and union.sum() == 0 and info == []
