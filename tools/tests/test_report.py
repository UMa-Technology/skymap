import os
from tools.clean_dss.io import save_webp_q90
from tools.clean_dss.fixtures import make_color_seam_tile
from tools.clean_dss.report import write_contact_sheet


def test_contact_sheet_written(tmp_path):
    src = tmp_path / "src"; out = tmp_path / "out"
    for tree in (src, out):
        (tree / "Norder4" / "Dir0").mkdir(parents=True)
    img, _ = make_color_seam_tile(0, (12, 0, -10), seed=1)
    save_webp_q90(img, str(src / "Norder4/Dir0/Npix0.webp"))
    save_webp_q90(img, str(out / "Norder4/Dir0/Npix0.webp"))
    rep = tmp_path / "rep"
    write_contact_sheet(str(src), str(out), {0}, str(rep))
    assert os.path.exists(str(rep / "Npix0.png"))
