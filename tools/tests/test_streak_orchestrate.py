import importlib.util
import cv2
import numpy as np
import pytest
from PIL import Image
from tools.clean_dss.io import save_webp_q90, file_sha, load_rgb
from tools.clean_dss.fixtures import make_streak_tile, make_clean_tile
from tools.clean_dss import streaks, streaks_hp as HP
from tools.clean_dss.destreak import streak_support_mask

CLI = "tools/clean-dss-survey.py"


def _cli():
    spec = importlib.util.spec_from_file_location("cds", CLI)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _stitch_region_with_streak(root, parent, seed):
    """Write 4 order-4 children whose 1024 stitch (TL,TR,BL,BR)=(c0,c2,c1,c3) carries
    one long red trail across it, plus the rebuilt order-3 parent."""
    d4 = root / "Norder4" / "Dir0"; d3 = root / "Norder3" / "Dir0"
    d4.mkdir(parents=True, exist_ok=True); d3.mkdir(parents=True, exist_ok=True)
    small, _gt = make_streak_tile(angle_deg=20, amp_dn=55.0, fwhm=2.0, mix=(1.0, 0.6, 0.2), seed=seed)
    big = np.asarray(Image.fromarray(small).resize((1024, 1024), Image.BICUBIC))
    kids = [4 * parent + k for k in range(4)]
    # inverse of _stitch_children: c0=TL, c1=BL, c2=TR, c3=BR
    quads = {kids[0]: big[:512, :512], kids[1]: big[512:, :512],
             kids[2]: big[:512, 512:], kids[3]: big[512:, 512:]}
    for c, q in quads.items():
        save_webp_q90(np.ascontiguousarray(q), str(d4 / f"Npix{c}.webp"))
    save_webp_q90(cv2.resize(big, (512, 512), interpolation=cv2.INTER_AREA), str(d3 / f"Npix{parent}.webp"))


def _corridor_response_ratio(before_img, after_img):
    """Median high-pass response inside the trail's support corridor: after/before.
    Measured on the corridor (not whole-image) because profile subtraction leaves
    bright stars untouched, so a whole-image percentile would be star-dominated."""
    fit = max(streaks.scan_image(before_img)["groups"], key=lambda g: g["score"])["fit"]
    mask = streak_support_mask(HP.highpass(before_img), fit, before_img.shape[0])
    rb = HP.response(before_img)[mask]; ra = HP.response(after_img)[mask]
    return float(np.median(ra) / max(np.median(rb), 1e-6))


def test_parse_typed_tiles_groups_by_class_and_maps_to_order3():
    m = _cli()
    got = m.parse_typed_tiles(["3/7:streak", "4/28:streak", "3/161:seam", "3/137:defect"])
    assert got["streak"] == {7}                 # 28 // 4 == 7
    assert got["seam"] == {161}
    assert got["defect"] == {137}


def test_parse_typed_tiles_defaults_untagged_to_seam():
    m = _cli()
    got = m.parse_typed_tiles(["3/161", "4/646"])   # back-compat: no :class -> seam
    assert got["seam"] == {161}                     # 646 // 4 == 161
    assert got["streak"] == set() and got["defect"] == set()


def test_parse_typed_tiles_rejects_bad_class_and_order():
    m = _cli()
    with pytest.raises(SystemExit):
        m.parse_typed_tiles(["3/5:bogus"])
    with pytest.raises(SystemExit):
        m.parse_typed_tiles(["2/5:streak"])


def test_clean_streak_region_reduces_the_trail_and_writes_only_its_region(tmp_path):
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    _stitch_region_with_streak(src, parent=0, seed=1)
    save_webp_q90(make_clean_tile(seed=7)[0], str(src / "Norder4/Dir0/Npix40.webp"))   # control (region 10)

    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(str(src), str(out), 0, changed4, changed3, warnings)
    assert changed4 == {0, 1, 2, 3} and changed3 == {0}
    assert warnings == []                                     # guardrails clean on a lone trail over sky
    # the trail dropped hard on its own corridor on the rebuilt order-3 parent
    before = load_rgb(str(src / "Norder3/Dir0/Npix0.webp"))
    after = load_rgb(str(out / "Norder3/Dir0/Npix0.webp"))
    assert _corridor_response_ratio(before, after) < 0.5
    # clean_streak_region only writes its own region — a control tile elsewhere is not copied here
    assert not (out / "Norder4/Dir0/Npix40.webp").exists()


def test_clean_streak_region_skips_when_no_trail(tmp_path):
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    d4 = src / "Norder4" / "Dir0"; d4.mkdir(parents=True)
    for c in (0, 1, 2, 3):                                    # clean region, no trail
        save_webp_q90(make_clean_tile(seed=c)[0], str(d4 / f"Npix{c}.webp"))
    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(str(src), str(out), 0, changed4, changed3, warnings)
    assert changed4 == set() and changed3 == set()           # nothing detected -> nothing written
    assert not (out / "Norder3/Dir0/Npix0.webp").exists()


def test_clean_streak_region_cleans_when_top_fit_is_not_a_trail_but_a_lower_fit_is(tmp_path):
    """PER-FIT gating (regression vs the old TOP-fit gate): a region whose TOP-scoring
    scanner fit is a non-trail (a wide/curved DSO false positive) but which ALSO contains
    a thin straight real trail as a lower-scoring fit must still be cleaned. The old code
    gated the whole region on the top fit's is_trail and would have SKIPPED this region;
    per-fit gating keeps the lower is_trail fits and cleans them."""
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    _stitch_region_with_streak(src, parent=0, seed=1)
    big = m._stitch_children([str(src / f"Norder4/Dir0/Npix{c}.webp") for c in (0, 1, 2, 3)])
    # recover the real trail fit from the honest scan, then craft a groups list whose TOP
    # (highest score) fit is a non-trail and the real trail sits below it as is_trail=True.
    real = max(streaks.scan_image(big)["groups"], key=lambda g: g["score"])
    trail_group = dict(real); trail_group["is_trail"] = True; trail_group["score"] = 5.0
    trail_group["features"] = {"prom": 99.0}            # not faint -> default grow path
    top_non_trail = dict(real); top_non_trail["is_trail"] = False; top_non_trail["score"] = 999.0
    top_non_trail["features"] = {"thinscore": 1.2, "prom": 99.0}
    crafted = {"binfrac": 0.0, "ngroups": 2, "dense": False,
               "groups": [top_non_trail, trail_group]}
    orig = streaks.scan_image
    try:
        streaks.scan_image = lambda img, **kw: crafted
        changed4, changed3, warnings = set(), set(), []
        m.clean_streak_region(str(src), str(out), 0, changed4, changed3, warnings)
    finally:
        streaks.scan_image = orig
    assert changed4 == {0, 1, 2, 3} and changed3 == {0}     # cleaned despite top fit not a trail
    before = load_rgb(str(src / "Norder3/Dir0/Npix0.webp"))
    after = load_rgb(str(out / "Norder3/Dir0/Npix0.webp"))
    assert _corridor_response_ratio(before, after) < 0.6    # the lower is_trail fit was taken down


def test_clean_streak_region_skips_when_no_fit_is_a_trail(tmp_path):
    """PER-FIT gating: a region where EVERY fit is a DSO/false-positive (none is_trail)
    must be skipped and write nothing, even though the scanner found candidate lines."""
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    _stitch_region_with_streak(src, parent=0, seed=1)      # real image; verdicts overridden below
    big = m._stitch_children([str(src / f"Norder4/Dir0/Npix{c}.webp") for c in (0, 1, 2, 3)])
    real = max(streaks.scan_image(big)["groups"], key=lambda g: g["score"])
    g0 = dict(real); g0["is_trail"] = False; g0["score"] = 30.0; g0["features"] = {"thinscore": 1.1}
    g1 = dict(real); g1["is_trail"] = False; g1["score"] = 12.0; g1["features"] = {"thinscore": 0.7}
    crafted = {"binfrac": 0.0, "ngroups": 2, "dense": False, "groups": [g0, g1]}
    orig = streaks.scan_image
    try:
        streaks.scan_image = lambda img, **kw: crafted
        changed4, changed3, warnings = set(), set(), []
        m.clean_streak_region(str(src), str(out), 0, changed4, changed3, warnings)
    finally:
        streaks.scan_image = orig
    assert changed4 == set() and changed3 == set()          # no fit is_trail -> nothing written
    assert not (out / "Norder3/Dir0/Npix0.webp").exists()


def test_main_streak_tiles_end_to_end_and_controls_byte_identical(tmp_path):
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    _stitch_region_with_streak(src, parent=0, seed=1)
    # control tiles in another region (region 10) + its order-3 parent
    save_webp_q90(make_clean_tile(seed=7)[0], str(src / "Norder4/Dir0/Npix40.webp"))
    save_webp_q90(make_clean_tile(seed=8)[0], str(src / "Norder3/Dir0/Npix10.webp"))

    m.main(["--src", str(src), "--out", str(out), "--streak-tiles", "3/0"])
    assert (out / "Norder3/Dir0/Npix0.webp").exists()
    for c in (0, 1, 2, 3):
        assert (out / f"Norder4/Dir0/Npix{c}.webp").exists()
    # untouched controls are byte-identical copies
    assert file_sha(str(out / "Norder4/Dir0/Npix40.webp")) == file_sha(str(src / "Norder4/Dir0/Npix40.webp"))
    assert file_sha(str(out / "Norder3/Dir0/Npix10.webp")) == file_sha(str(src / "Norder3/Dir0/Npix10.webp"))


def test_main_typed_tiles_token_routes_to_streak(tmp_path):
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    _stitch_region_with_streak(src, parent=0, seed=1)
    changed = m.main(["--src", str(src), "--out", str(out), "--tiles", "3/0:streak"])
    assert changed == {0, 1, 2, 3}                            # the streak region's 4 children


def test_main_still_accepts_seam_tiles_only(tmp_path):
    # back-compat: the phase-1 invocation path must keep working
    from tools.clean_dss.fixtures import make_color_seam_tile
    m = _cli()
    src = tmp_path / "src"; out = tmp_path / "out"
    (src / "Norder4/Dir0").mkdir(parents=True); (src / "Norder3/Dir0").mkdir(parents=True)
    for c in (0, 1, 2, 3):
        save_webp_q90(make_color_seam_tile(0, (14, 0, -12), seed=c)[0], str(src / f"Norder4/Dir0/Npix{c}.webp"))
    save_webp_q90(make_color_seam_tile(0, (14, 0, -12), seed=9)[0], str(src / "Norder3/Dir0/Npix0.webp"))
    m.main(["--src", str(src), "--out", str(out), "--seam-tiles", "3/0"])
    assert (out / "Norder3/Dir0/Npix0.webp").exists()


def test_main_nothing_to_do_errors(tmp_path):
    m = _cli()
    with pytest.raises(SystemExit):
        m.main(["--src", str(tmp_path / "src"), "--out", str(tmp_path / "out")])


import os
from tools.clean_dss.validate import stars_preserved

# Pinned dirty-tile fixtures (see tools/tests/fixtures/dss_dirty), decoupled from the live
# survey tree: real-trail asserts need a tile that still has its trail, but the shipped tree
# gets those trails cleaned out. DSO tiles (338/594/23) are kept dirty here too for stability.
DSS = os.path.join(os.path.dirname(__file__), "fixtures", "dss_dirty")


@pytest.mark.parametrize("parent", [178, 283])
def test_real_tile_trail_is_reduced_and_saturated_stars_kept(tmp_path, parent):
    """Integration on the real survey tree (skips if not checked out): a real trail's
    corridor response collapses, and the SATURATED bright stars survive. NOTE: the
    confirmed policy is aggressive — non-saturated beads/mid-stars on the trail line are
    removed by design — so we do NOT use stars_preserved here (it conflates removed beads
    with damaged stars); we assert the genuine bright (>=235) stars are kept instead."""
    import numpy as np
    from tools.clean_dss import streaks
    from tools.clean_dss.destreak import destreak_image
    kids = [4 * parent + k for k in range(4)]
    if not all(os.path.exists(f"{DSS}/Norder4/Dir0/Npix{c}.webp") for c in kids):
        pytest.skip(f"real DSS children for region {parent} not present")
    m = _cli()
    before = m._stitch_children([f"{DSS}/Norder4/Dir0/Npix{c}.webp" for c in kids])
    fits = [g["fit"] for g in streaks.scan_image(before)["groups"] if g["score"] >= m.STREAK_SCORE_MIN]
    assert fits                                               # the known trail is detected
    cleaned, union, info = destreak_image(before, fits)
    assert _corridor_response_ratio(before, cleaned) < 0.25   # brightest trail's corridor collapsed >75%
    sat = before.astype(np.float32).mean(2) >= 235            # genuine saturated stars
    assert sat.sum() > 20 and (cleaned.astype(np.float32).mean(2)[sat] >= 200).mean() > 0.9
    # and clean_streak_region wires it to the right tiles + rebuild
    out = tmp_path / "out"
    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(DSS, str(out), parent, changed4, changed3, warnings)
    assert changed3 == {parent} and changed4 == set(kids)


@pytest.mark.parametrize("parent", [338, 594, 23])
def test_clean_streak_region_rejects_dso_region(tmp_path, parent):
    """The trail-vs-DSO gate must SKIP a DSO region (galaxy edge / nebula filament) even
    when a human accidentally flags it: cleaning would erase real astronomy. Nothing is
    written. 594 is the hard nebula whose top fit is the worst DSO (sharpness ~1.27)."""
    m = _cli()
    kids = [4 * parent + k for k in range(4)]
    if not all(os.path.exists(f"{DSS}/Norder4/Dir0/Npix{c}.webp") for c in kids):
        pytest.skip(f"real DSS children for region {parent} not present")
    out = tmp_path / "out"
    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(DSS, str(out), parent, changed4, changed3, warnings)
    assert changed4 == set() and changed3 == set()            # rejected -> nothing written
    assert not (out / f"Norder3/Dir0/Npix{parent}.webp").exists()


def test_clean_streak_region_cleans_faint_real_below_old_score_floor(tmp_path):
    """Region 227 is a faint-but-real trail (scanner score ~5.5, below the legacy 6.0
    floor) that the discriminator admits (sharpness 6.08). The is_trail gate must clean
    it (the old score gate would have silently skipped it), reducing its corridor."""
    import numpy as np
    parent = 227
    kids = [4 * parent + k for k in range(4)]
    if not all(os.path.exists(f"{DSS}/Norder4/Dir0/Npix{c}.webp") for c in kids):
        pytest.skip(f"real DSS children for region {parent} not present")
    m = _cli()
    before = m._stitch_children([f"{DSS}/Norder4/Dir0/Npix{c}.webp" for c in kids])
    top = max(streaks.scan_image(before)["groups"], key=lambda g: g["score"])
    assert top["score"] < m.STREAK_SCORE_MIN and top["is_trail"]   # faint yet a real trail
    out = tmp_path / "out"
    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(DSS, str(out), parent, changed4, changed3, warnings)
    assert changed3 == {parent} and changed4 == set(kids)          # actually cleaned + rebuilt
    after = load_rgb(str(out / f"Norder3/Dir0/Npix{parent}.webp"))
    before3 = cv2.resize(before, (512, 512), interpolation=cv2.INTER_AREA)
    assert _corridor_response_ratio(before3, after) < 0.85         # faint trail reduced


def test_clean_streak_region_cleans_fragmented_real_trail_via_per_fit_gating(tmp_path):
    """Region 40 is a faint FRAGMENTED real trail: 3 collinear fits at thinscore
    ~3.14/3.82/2.69 whose TOP scanner fit is a vertical plate seam (thinscore 0.39,
    is_trail=False). The old TOP-fit gate skipped the whole region; per-fit gating with
    THINSCORE_MIN=3.0 keeps the >3.0 segments and cleans them. Confirms a fit exists that
    is is_trail while the top fit is not."""
    import numpy as np
    parent = 40
    kids = [4 * parent + k for k in range(4)]
    if not all(os.path.exists(f"{DSS}/Norder4/Dir0/Npix{c}.webp") for c in kids):
        pytest.skip(f"real DSS children for region {parent} not present")
    m = _cli()
    before = m._stitch_children([f"{DSS}/Norder4/Dir0/Npix{c}.webp" for c in kids])
    groups = streaks.scan_image(before)["groups"]
    top = max(groups, key=lambda g: g["score"])
    assert not top["is_trail"]                                     # top fit is the seam, not a trail
    assert any(g["is_trail"] for g in groups)                      # but a fragmented real trail is
    out = tmp_path / "out"
    changed4, changed3, warnings = set(), set(), []
    m.clean_streak_region(DSS, str(out), parent, changed4, changed3, warnings)
    assert changed3 == {parent} and changed4 == set(kids)          # cleaned despite non-trail top fit
