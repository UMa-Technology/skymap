import numpy as np
from tools.clean_dss.background import coarse_bg, upsample_smooth
from tools.clean_dss.fixtures import make_clean_tile

def test_coarse_bg_shape_and_star_robustness():
    img, _ = make_clean_tile(seed=3)
    bg = coarse_bg(img)
    assert bg.shape == (32, 32, 3)
    # a bright star must not lift the coarse background of its cell much:
    img2 = img.astype(np.float32).copy()
    img2[8:12, 8:12] = 255.0                     # slam a 4x4 star into one cell
    bg2 = coarse_bg(img2.astype(np.uint8))
    r, c = 8 // 16, 8 // 16
    assert abs(float(bg2[r, c].mean() - bg[r, c].mean())) < 6.0

def test_upsample_smooth_no_hard_edges():
    lo = np.zeros((32, 32), np.float32); lo[:, :16] = 10.0        # a step in coarse map
    hi = upsample_smooth(lo, 512)
    assert hi.shape == (512, 512)
    col = hi[256]                                                 # transition should be gradual
    assert (np.abs(np.diff(col)).max()) < 10.0                   # not a 1-px cliff
