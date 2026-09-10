import numpy as np
from tools.clean_dss.fixtures import make_seam_tile, make_clean_tile

def test_seam_tile_has_known_step():
    img, gt = make_seam_tile(angle_deg=30, step_dn=8.0, seed=1)
    assert img.shape == (512, 512, 3) and img.dtype == np.uint8
    # ground truth carries the region mask (at coarse 32x32) and the injected step
    assert gt["labels"].shape == (32, 32)
    assert set(np.unique(gt["labels"])) == {0, 1}
    assert abs(gt["step_dn"] - 8.0) < 1e-6

def test_clean_tile_has_no_step():
    img, gt = make_clean_tile(seed=2)
    assert img.shape == (512, 512, 3)
    assert gt["labels"] is None  # no seam

import pytest

@pytest.mark.parametrize("angle", list(range(0, 360, 15)))
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_seam_always_splits_two_regions(angle, seed):
    _, gt = make_seam_tile(angle_deg=angle, step_dn=8.0, seed=seed)
    assert set(np.unique(gt["labels"])) == {0, 1}


from tools.clean_dss.fixtures import make_streak_tile


def test_make_streak_tile_injects_a_thin_colored_line():
    img, gt = make_streak_tile(angle_deg=20, amp_dn=40.0, fwhm=1.5,
                               mix=(1.0, 0.5, 0.1), seed=3)
    assert img.shape == (512, 512, 3) and img.dtype == np.uint8
    # ground truth carries the pre-streak clean tile and the streak support mask
    assert gt["clean"].shape == (512, 512, 3) and gt["clean"].dtype == np.uint8
    assert gt["mask"].shape == (512, 512) and gt["mask"].dtype == bool
    # the streak really is there: dominant (red) channel is much brighter on the mask
    delta = img.astype(np.float32) - gt["clean"].astype(np.float32)
    on = gt["mask"]
    assert delta[..., 0][on].mean() > 15.0            # red pumped up on the line
    assert delta[..., 0][~on].mean() < 2.0            # untouched off the line
    # thin: mask covers a small fraction of the tile
    assert 0.001 < on.mean() < 0.05
    # dashes: a duty<1 streak leaves gaps -> fewer masked pixels than a solid one
    _, gt_solid = make_streak_tile(angle_deg=20, amp_dn=40.0, duty=1.0, seed=3)
    _, gt_dash = make_streak_tile(angle_deg=20, amp_dn=40.0, duty=0.5, seed=3)
    assert gt_dash["mask"].sum() < gt_solid["mask"].sum()
