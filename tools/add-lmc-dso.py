#!/usr/bin/env python3
# Surgically add the Large Magellanic Cloud to the DSO survey.
#
# The App's objects_catalogs export has the Small Magellanic Cloud (NGC 292) but
# NOT the LMC (it has no NGC number), so the map labels the SMC but not the LMC.
# This injects one LMC row into its Norder0 HEALPix tile (nside=1 nested pixel 8,
# same base pixel as the SMC) and registers "LMC -> Large Magellanic Cloud" in
# the western skyculture common_names so it localizes via sky-i18n (which already
# has "Large Magellanic Cloud" -> 大麦哲伦云 / 大麥哲倫雲 / ...).
#
# Reuses make-dso-survey.py's own pack/encode/decode so the binary format is
# guaranteed correct; round-trips the tile and asserts every prior row survives.
#
# Usage: tools/add-lmc-dso.py [--apply]

import importlib.util
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILE = os.path.join(ROOT, "apps", "skydata", "dso", "Norder0", "Dir0", "Npix8.eph")
SKYCULTURE = os.path.join(ROOT, "apps", "skydata", "skycultures", "western",
                          "index.json")

# Load make-dso-survey.py for its pack/encode/decode + constants, but strip its
# top-level numpy / astropy-healpix imports (only build_eph, which we don't call,
# needs them; the HEALPix pixel for the LMC is computed by hand as 8).
_src = open(os.path.join(os.path.dirname(__file__), "make-dso-survey.py"),
            encoding="utf-8").read()
for _line in ("import numpy as np\n",
              "from astropy_healpix import HEALPix\n",
              "import astropy.units as u\n"):
    _src = _src.replace(_line, "")


class _M:
    pass


mk = _M()
mk.__dict__["__file__"] = os.path.join(os.path.dirname(__file__),
                                       "make-dso-survey.py")
exec(compile(_src, "make-dso-survey.py", "exec"), mk.__dict__)

# LMC in make-dso-survey row form: [ids, otype, ra_rad, de_rad, sx_arcmin,
# sy_arcmin, vmag, bmag, dmag, angle_deg]. Center 05h23m34.5s -69°45'22"
# (J2000), apparent size ~10.75deg x 9.17deg, V ~0.9. First id = the
# common_names key. angle NaN -> unrotated (its bar PA is not critical here).
LMC = ["LMC|ESO 56-115|PGC 17223|Nubecula Major", "G",
       math.radians(80.89417), math.radians(-69.75611),
       645.0, 550.0, 0.9, 0.9, 0.9, float("nan")]


def rec_to_row(r):
    """Decoded dict (stored units: rad) -> make-dso-survey row (arcmin/deg)."""
    def num(x):
        return x  # NaN passes through _pack_row's _*_or_nan helpers
    return [
        r["ids"], r["type"], r["ra"], r["de"],
        num(r["smax"]) / mk.ARCMIN2RAD, num(r["smin"]) / mk.ARCMIN2RAD,
        r["vmag"], r["bmag"], r["dmag"],
        num(r["angl"]) / mk.DEG2RAD,
    ]


def main():
    apply = "--apply" in sys.argv

    data = open(TILE, "rb").read()
    orig = mk._decode_tile(data)
    orig_ids = [d["ids"] for d in orig]
    print("Npix8 rows: %d" % len(orig))
    assert any(d["ids"].startswith("NGC 292") for d in orig), "SMC not in this tile!"
    # Sub-objects like "LMC N44" legitimately exist; only the LMC *galaxy* (whose
    # primary id would be exactly "LMC") must be absent.
    lmc_like = sorted({d["ids"].split("|")[0] for d in orig
                       if "LMC" in d["ids"]})[:8]
    print("existing ids containing 'LMC' (primary):", lmc_like)
    if any(d["ids"].split("|")[0] == "LMC" for d in orig):
        # Idempotent: make-dso-survey.py runs this after every rebuild.
        print("LMC galaxy already present, nothing to do")
        return

    rows = [rec_to_row(d) for d in orig] + [LMC]
    # Keep the tile sorted by display magnitude (brightest first), as the builder
    # does, so the engine's magnitude-ordered scan reaches the bright LMC.
    rows.sort(key=lambda d: d[8])
    blob = mk._encode_tile(8, rows)

    # Round-trip: every original row must survive byte-equivalently, plus LMC.
    dec = mk._decode_tile(blob)
    assert len(dec) == len(orig) + 1, (len(dec), len(orig))
    new_ids = {d["ids"] for d in dec}
    missing = [i for i in orig_ids if i not in new_ids]
    assert not missing, ("lost rows", missing[:5])
    lmc = next(d for d in dec if d["ids"].startswith("LMC"))
    print("LMC decoded back: ids=%r vmag=%.2f smax=%.4frad (%.0f')" % (
        lmc["ids"], lmc["vmag"], lmc["smax"], lmc["smax"] / mk.ARCMIN2RAD))

    # common_names entry (so the label localizes through sky-i18n). The file is
    # pretty-printed at top level but common_names is one compact line, so splice
    # the entry in as text to preserve the exact on-disk format.
    sc_text = open(SKYCULTURE, encoding="utf-8").read()
    already = '"LMC":' in sc_text
    print("common_names[LMC] present already: %s" % already)

    if not apply:
        print("\n(dry-run; --apply to write the tile + common_names)")
        return

    open(TILE, "wb").write(blob)
    if not already:
        marker = '"common_names": {'
        assert marker in sc_text, "common_names marker not found"
        entry = '"LMC":[{"english":"Large Magellanic Cloud"}],'
        sc_text = sc_text.replace(marker, marker + entry, 1)
        json.loads(sc_text)  # validate before writing
        open(SKYCULTURE, "w", encoding="utf-8").write(sc_text)
    print("written: Npix8.eph (+LMC), common_names[LMC]")


if __name__ == "__main__":
    main()
