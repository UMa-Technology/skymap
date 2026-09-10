import numpy as np
from tools.clean_dss.segment import segment, chroma_features
from tools.clean_dss.background import coarse_bg
from tools.clean_dss.fixtures import make_color_seam_tile
from tools.clean_dss.correct import correct_seam, apply_correction

def test_segment_separates_colour_block():
    img, gt = make_color_seam_tile(angle_deg=25, cast_rgb=(14, 0, -12), seed=3)
    labels = segment(coarse_bg(img), k=2)
    a = (labels == gt["labels"]).mean(); b = (labels != gt["labels"]).mean()
    assert max(a, b) > 0.85            # 2 clusters recover the colour split

def test_segment_deterministic():
    img, _ = make_color_seam_tile(20, (8, 0, -8), seed=1)
    bg = coarse_bg(img)
    assert np.array_equal(segment(bg, k=5), segment(bg, k=5))

def test_segment_k1_is_single_region():
    img, _ = make_color_seam_tile(10, (8, 0, -8), seed=2)
    labels = segment(coarse_bg(img), k=1)
    assert labels.shape == (32, 32) and set(np.unique(labels)) == {0}

def test_repair_reduces_colour_cast():
    img, gt = make_color_seam_tile(angle_deg=0, cast_rgb=(12, 0, -10), seed=5)
    bg = coarse_bg(img)
    labels = segment(bg, k=4)
    out = apply_correction(img, bg, correct_seam(bg, labels))
    def cast_gap(im):
        b = coarse_bg(im); m = gt["labels"].astype(bool)
        rb = b[..., 0] - b[..., 2]      # R-B opponent
        return abs(rb[m].mean() - rb[~m].mean())
    assert cast_gap(out) < 0.5 * cast_gap(img)
