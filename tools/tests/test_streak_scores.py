import json
import importlib.util
import numpy as np
from tools.clean_dss.io import save_webp_q90
from tools.clean_dss.fixtures import make_streak_tile, make_clean_tile

SCRIPT = "tools/make-streak-scores.py"


def _mod():
    spec = importlib.util.spec_from_file_location("mss", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_scan_tree_writes_json_with_scores_and_geometry(tmp_path):
    d = tmp_path / "Norder3" / "Dir0"; d.mkdir(parents=True)
    save_webp_q90(make_streak_tile(20, 55.0, fwhm=2.0, mix=(1.0, 0.5, 0.1), seed=1)[0], str(d / "Npix5.webp"))
    save_webp_q90(make_clean_tile(seed=2)[0], str(d / "Npix6.webp"))
    out = tmp_path / "tile-streaks.json"
    m = _mod()
    m.scan_tree(str(tmp_path), str(out), npix_list=[5, 6])
    data = json.loads(out.read_text())
    assert data["5"]["score"] > 6.0                      # streak tile flagged
    assert data["5"]["groups"] and "p0" in data["5"]["groups"][0]
    assert data["6"]["score"] < 6.0                      # clean tile quiet
    json.dumps(data)                                     # JSON-safe: no numpy left
