import numpy as np
from tools.clean_dss.fixtures import make_streak_tile, make_clean_tile
from tools.clean_dss import streaks


def test_scan_image_finds_a_bright_trail_with_usable_fit():
    img, gt = make_streak_tile(angle_deg=20, amp_dn=55.0, fwhm=2.0, duty=1.0, mix=(1.0, 0.6, 0.2), seed=1)
    scan = streaks.scan_image(img)
    assert scan["ngroups"] >= 1
    g = max(scan["groups"], key=lambda r: r["score"])
    assert g["score"] > 6.0
    da = abs((g["fit"]["angle"] - 20.0 + 90) % 180 - 90)
    assert da < 6.0
    for key in ("cx", "cy", "u", "n", "span", "angle"):
        assert key in g["fit"]


def test_scan_image_is_quiet_on_a_clean_tile():
    img, _ = make_clean_tile(seed=3)
    scan = streaks.scan_image(img)
    assert all(r["score"] < 6.0 for r in scan["groups"])


def test_scan_image_negative_polarity_finds_a_dark_trail():
    img, gt = make_streak_tile(angle_deg=0, amp_dn=40.0, mix=(1.0, 1.0, 1.0), seed=2)
    streak = img.astype(np.float32) - gt["clean"].astype(np.float32)
    dark = np.clip(np.full_like(img, 80, np.float32) - streak, 0, 255).astype(np.uint8)
    best = lambda s: max([r["score"] for r in s["groups"]] + [0.0])
    assert best(streaks.scan_image(dark, polarity=-1)) > best(streaks.scan_image(dark, polarity=1))
