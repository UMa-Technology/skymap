import numpy as np
from tools.clean_dss.correct import poisson_reconstruct, correct_seam

def test_poisson_removes_step_preserves_gradient():
    # ground-truth field: a smooth ramp (real structure) + a hard step (seam)
    gh = np.linspace(0, 20, 32)[None, :].repeat(32, 0).astype(np.float32)  # smooth ramp
    labels = np.zeros((32, 32), int); labels[:, 16:] = 1
    seam = np.where(labels == 1, 9.0, 0.0).astype(np.float32)
    bg = gh + seam
    out = correct_seam(bg[..., None].repeat(3, 2), labels)[..., 0]         # per-channel API
    # step across the seam must be gone: columns 15 vs 16 differ only by the ramp slope
    ramp_slope = 20.0 / 31
    jump = abs((out[:, 16] - out[:, 15]).mean())
    assert jump < 2.0 * ramp_slope                # seam step (~9) removed
    # smooth ramp preserved: far-from-seam left half keeps its gradient
    assert abs((out[:, 10] - out[:, 2]).mean() - (bg[:, 10] - bg[:, 2]).mean()) < 1.5

def test_correct_seam_preserves_mean():
    bg = np.random.default_rng(0).normal(20, 3, (32, 32, 3)).astype(np.float32)
    labels = np.zeros((32, 32), int); labels[16:] = 1
    bg[16:] += 7.0
    out = correct_seam(bg, labels)
    assert abs(float(out.mean() - bg.mean())) < 0.5   # per-tile DC preserved (no new tile-edge seam)

from tools.clean_dss.correct import apply_correction
from tools.clean_dss.background import coarse_bg
from tools.clean_dss.fixtures import make_seam_tile

def test_apply_correction_flattens_full_res_seam():
    img, gt = make_seam_tile(angle_deg=0, step_dn=10.0, seed=5)   # vertical seam
    bg = coarse_bg(img)
    out = apply_correction(img, bg, correct_seam(bg, gt["labels"]))
    assert out.shape == img.shape and out.dtype == np.uint8
    # coarse bg of the result has a much smaller cross-seam step than the input
    b2 = coarse_bg(out)
    # locate the actual seam column from ground truth (for seed=5 it is not at 15/16)
    seam_col = int(np.where(gt["labels"][0, :-1] != gt["labels"][0, 1:])[0][0]) + 1
    before = abs((bg[:, seam_col] - bg[:, seam_col - 1]).mean())
    after  = abs((b2[:, seam_col] - b2[:, seam_col - 1]).mean())
    assert after < 0.4 * before
