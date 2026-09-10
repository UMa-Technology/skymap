import numpy as np
from tools.clean_dss.validate import stars_preserved, edge_step
from tools.clean_dss.fixtures import make_color_seam_tile
from tools.clean_dss.background import coarse_bg
from tools.clean_dss.segment import segment
from tools.clean_dss.correct import correct_seam, apply_correction


def test_stars_preserved_after_cleaning():
    img, gt = make_color_seam_tile(angle_deg=20, cast_rgb=(12, 0, -10), seed=7)
    bg = coarse_bg(img)
    out = apply_correction(img, bg, correct_seam(bg, segment(bg, k=4)))
    # background leveling shifts sky level under stars, but bright stars keep their
    # contrast above local background:
    assert stars_preserved(img, out)


def test_stars_not_preserved_when_star_erased():
    img, _ = make_color_seam_tile(angle_deg=20, cast_rgb=(12, 0, -10), seed=7)
    wrecked = img.copy()
    wrecked[:] = img.mean(axis=(0, 1)).astype(img.dtype)   # flatten everything -> no stars
    assert not stars_preserved(img, wrecked)


def test_edge_step_metric_monotonic():
    a = np.zeros((512, 512, 3), np.uint8)
    b = a.copy(); b[:, :256] += 30
    assert edge_step(b) > edge_step(a)


import numpy as np
from tools.clean_dss.fixtures import make_streak_tile
from tools.clean_dss import streaks_hp as HP
from tools.clean_dss.destreak import streak_support_mask, destreak_image
from tools.clean_dss.validate import streak_cleared, no_ghost_edges


def _fit(gt):
    th = np.deg2rad(gt["angle_deg"]); u = np.array([np.cos(th), np.sin(th)])
    return {"cx": 256.0, "cy": 256.0, "angle": gt["angle_deg"],
            "u": u, "n": np.array([-u[1], u[0]]), "span": (-256.0, 256.0)}


def test_streak_cleared_true_after_repair_false_before():
    img, gt = make_streak_tile(angle_deg=25, amp_dn=50.0, mix=(1.0, 0.5, 0.1), seed=11)
    fit = _fit(gt)
    cleaned, union, _ = destreak_image(img, [fit])
    assert streak_cleared(img, cleaned, union)             # repair dropped the response
    assert not streak_cleared(img, img, union)             # no-op does not clear it


def test_no_ghost_edges_true_for_confined_repair():
    img, gt = make_streak_tile(angle_deg=25, amp_dn=50.0, mix=(1.0, 0.5, 0.1), seed=12)
    fit = _fit(gt)
    cleaned, union, _ = destreak_image(img, [fit])
    assert no_ghost_edges(img, cleaned, union)             # change confined to corridor
    # a repair that smears the whole tile trips it
    smeared = np.clip(img.astype(float) + 5.0, 0, 255).astype(np.uint8)
    assert not no_ghost_edges(img, smeared, union)


def test_streak_cleared_measures_the_trail_support_not_the_wide_corridor():
    # a THIN trail fills only ~30% of the footprint; the footprint-wide median would be
    # noise-floor-dominated and flip on quantization. streak_cleared measures the hot
    # support, so a genuinely-cleaned faint narrow trail reads as cleared.
    img, gt = make_streak_tile(angle_deg=25, amp_dn=22.0, fwhm=1.5, mix=(1.0, 0.5, 0.1), seed=7)
    fit = _fit(gt)
    cleaned, union, _ = destreak_image(img, [fit])
    assert streak_cleared(img, cleaned, union)             # thin faint trail still reads as cleared
    assert not streak_cleared(img, img, union)             # no-op does not
