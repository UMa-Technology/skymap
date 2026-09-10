import numpy as np
from tools.clean_dss.pyramid import rebuild_parent, child_ids

def test_child_ids():
    assert child_ids(161) == [644, 645, 646, 647]

def test_rebuild_parent_layout():
    # four distinct-valued children -> parent quadrants (TL,TR,BL,BR)=(c0,c2,c1,c3)
    c = [np.full((512,512,3), v, np.uint8) for v in (10,20,30,40)]
    p = rebuild_parent(c)
    assert p.shape == (512,512,3)
    assert p[0,0,0]     == 10   # TL = child0
    assert p[0,-1,0]    == 30   # TR = child2
    assert p[-1,0,0]    == 20   # BL = child1
    assert p[-1,-1,0]   == 40   # BR = child3

import os
from PIL import Image
ROOT = "apps/web-frontend/public/skydata/surveys/dss"

def _load(o, n):
    return np.asarray(Image.open(f"{ROOT}/Norder{o}/Dir0/Npix{n}.webp").convert("RGB"))

def test_rebuild_matches_real_parent():
    if not os.path.exists(f"{ROOT}/Norder4/Dir0/Npix644.webp"):
        import pytest; pytest.skip("survey tiles not present")
    kids = [_load(4, n) for n in child_ids(161)]
    rebuilt = rebuild_parent(kids).astype(np.float32)
    orig = _load(3, 161).astype(np.float32)
    mse = float(((rebuilt - orig) ** 2).mean())
    assert mse < 10.0            # design measured ~2.6; re-encode noise only
