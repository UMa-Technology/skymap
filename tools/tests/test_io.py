import numpy as np
from tools.clean_dss.io import load_rgb, save_webp_q90, file_sha


def test_roundtrip_and_hash(tmp_path):
    img = (np.random.default_rng(0).random((512, 512, 3)) * 255).astype(np.uint8)
    p = tmp_path / "t.webp"
    save_webp_q90(img, str(p))
    assert p.exists()
    back = load_rgb(str(p))
    assert back.shape == (512, 512, 3)
    assert file_sha(str(p)) == file_sha(str(p))     # stable


def test_save_is_deterministic(tmp_path):
    img = (np.random.default_rng(1).random((64, 64, 3)) * 255).astype(np.uint8)
    a, b = tmp_path / "a.webp", tmp_path / "b.webp"
    save_webp_q90(img, str(a)); save_webp_q90(img, str(b))
    assert file_sha(str(a)) == file_sha(str(b))     # same input -> same bytes
