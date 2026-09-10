import importlib.util
import pytest
from tools.clean_dss.io import save_webp_q90, file_sha
from tools.clean_dss.fixtures import make_color_seam_tile, make_clean_tile

CLI = "tools/clean-dss-survey.py"


def _cli():
    spec = importlib.util.spec_from_file_location("cds", CLI)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(argv):
    return _cli().main(argv)


def _seam(path, seed):
    img, _ = make_color_seam_tile(0, (14, 0, -12), seed=seed)
    save_webp_q90(img, str(path))


def test_parse_seam_regions_maps_to_order3_parent():
    m = _cli()
    assert m.parse_seam_regions(["3/161"]) == {161}
    assert m.parse_seam_regions(["4/700"]) == {175}          # 700 // 4
    assert m.parse_seam_regions(["3/161", "4/646"]) == {161}  # 646 // 4 == 161
    assert m.parse_seam_regions(["3/5", "4/40"]) == {5, 10}


def _build_tree(root):
    (root / "Norder4" / "Dir0").mkdir(parents=True)
    (root / "Norder3" / "Dir0").mkdir(parents=True)
    for c in (0, 1, 2, 3):                       # region 0 children
        _seam(root / f"Norder4/Dir0/Npix{c}.webp", seed=c)
    _seam(root / "Norder3/Dir0/Npix0.webp", seed=99)         # region 0 parent
    save_webp_q90(make_clean_tile(seed=7)[0], str(root / "Norder4/Dir0/Npix40.webp"))  # control (region 10)
    save_webp_q90(make_clean_tile(seed=8)[0], str(root / "Norder3/Dir0/Npix10.webp"))  # control parent


def test_region_cleaned_and_others_untouched(tmp_path):
    src = tmp_path / "src"; out = tmp_path / "out"
    _build_tree(src)
    changed = _run(["--src", str(src), "--out", str(out), "--seam-tiles", "3/0"])
    assert changed == {0, 1, 2, 3}
    for c in (0, 1, 2, 3):                       # all four children cleaned
        assert file_sha(str(out / f"Norder4/Dir0/Npix{c}.webp")) != file_sha(str(src / f"Norder4/Dir0/Npix{c}.webp"))
    assert (out / "Norder3/Dir0/Npix0.webp").exists()        # parent rebuilt
    # controls in another region are byte-identical (copied)
    assert file_sha(str(out / "Norder4/Dir0/Npix40.webp")) == file_sha(str(src / "Norder4/Dir0/Npix40.webp"))
    assert file_sha(str(out / "Norder3/Dir0/Npix10.webp")) == file_sha(str(src / "Norder3/Dir0/Npix10.webp"))


def test_order4_entry_maps_to_its_region(tmp_path):
    src = tmp_path / "src"; out = tmp_path / "out"
    _build_tree(src)
    changed = _run(["--src", str(src), "--out", str(out), "--seam-tiles", "4/2"])
    assert changed == {0, 1, 2, 3}              # 4/2 -> region 0 -> all children


def test_parse_rejects_bad_entries():
    m = _cli()
    with pytest.raises(SystemExit):
        m.parse_seam_regions(["2/5"])           # order 2 not shipped
    with pytest.raises(SystemExit):
        m.parse_seam_regions(["nonsense"])      # not order/npix


def test_missing_children_aborts(tmp_path):
    src = tmp_path / "src"; out = tmp_path / "out"
    (src / "Norder4" / "Dir0").mkdir(parents=True)
    (src / "Norder3" / "Dir0").mkdir(parents=True)
    _seam(src / "Norder4/Dir0/Npix0.webp", seed=0)   # only 1 of region 0's 4 children
    with pytest.raises(SystemExit):
        _run(["--src", str(src), "--out", str(out), "--seam-tiles", "3/0"])
