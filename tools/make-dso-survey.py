#!/usr/bin/env python3
# Stellarium Web Engine
#
# Build the DSO "eph" HiPS survey (+ western-skyculture common names + the
# sky-i18n translation catalog) from the objects_catalogs engine export. This
# replaces the engine's ~9k 2020 base DSO survey with the App's ~20k catalog so
# the sky map is data-consistent with the external App.
#
# Input : objects-swe.json   (from: python -m catalog_builder build-swe)
# Output: apps/skydata/dso/{properties, Norder0/Dir0/Npix{0..11}.eph}
#         apps/skydata/skycultures/western/index.json  (+ "common_names")
#         apps/skydata/sky-i18n/{lang}.json             (App names overlaid)
#
# Name policy: proper names live in the skyculture
# common_names (english only, so translation flows via sys_translate); the eph
# id list holds catalog designations only, so the map shows the proper name when
# one exists (any length) else the catalog id. Named stars are excluded from the
# DSO markers (the star survey already shows them) but keep a HIP-keyed name.
#
# eph binary layout mirrors src/eph-file.c / src/modules/dso.c exactly; a
# round-trip self-check decodes every tile and verifies the fields before the
# survey is written into place.
#
# Requires numpy + astropy-healpix. Run with the tools venv, e.g.:
#   <ephvenv>/bin/python tools/make-dso-survey.py [objects-swe.json]

import json
import math
import os
import re
import subprocess
import struct
import sys
import zlib

import numpy as np
from astropy_healpix import HEALPix
import astropy.units as u

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKYDATA = os.path.join(ROOT, "apps", "skydata")
DSO_DIR = os.path.join(SKYDATA, "dso")
SKYCULTURE = os.path.join(SKYDATA, "skycultures", "western", "index.json")
I18N_DIR = os.path.join(SKYDATA, "sky-i18n")
DEFAULT_INPUT = os.environ.get("OBJECTS_SWE_JSON", os.path.join(ROOT, "..", "objects_catalogs", "docs", "objects-swe.json"))

ARCMIN2RAD = math.pi / (180.0 * 60.0)
DEG2RAD = math.pi / 180.0
DSO_DEFAULT_VMAG = 16.0            # src/modules/dso.c DSO_DEFAULT_VMAG
ORDER, NSIDE = 0, 1               # Norder0 only: all 12 base tiles always loaded,
                                  # so every object is instantly locatable/selectable.

EPH_RAD = 1 << 16
EPH_VMAG = 3 << 16
# (name, typechar, unit, size) — MUST match dso.c on_file_tile_loaded columns[].
COLUMNS = [
    ("type", "s", 0,        4),
    ("vmag", "f", EPH_VMAG, 4),
    ("bmag", "f", EPH_VMAG, 4),
    ("dmag", "f", EPH_VMAG, 4),   # display magnitude: real vmag, else size/opacity-derived
    ("ra",   "f", EPH_RAD,  4),
    ("de",   "f", EPH_RAD,  4),
    ("smax", "f", EPH_RAD,  4),
    ("smin", "f", EPH_RAD,  4),
    ("angl", "f", EPH_RAD,  4),
    ("morp", "s", 0,        32),
    ("ids",  "s", 0,        256),
]
_STARTS, _off = [], 0
for _c in COLUMNS:
    _STARTS.append(_off)
    _off += _c[3]
ROW_SIZE = _off                   # 320


def _mag_or_nan(v):
    return float("nan") if not (-30.0 < v < 90.0) else float(v)


def _angle_or_nan(deg):
    # Position angle in degrees (0..360, N->E). Anything outside that range
    # (the 9999 unknown sentinel, or NaN) becomes NaN so the engine leaves the
    # marker unrotated. dso.c NaN-guards s->angle, so NaN renders as today's 0.
    return float("nan") if not (0.0 <= deg < 360.0) else float(deg)


def _pack_str(s, size):
    b = s.encode("utf-8")[: size - 1]      # data string: always leave room for NUL
    return b + b"\x00" * (size - len(b))


def _pack_fixed(s, size):
    b = s.encode("utf-8")[:size]           # fixed field (column name/type): no NUL reserved
    return b + b"\x00" * (size - len(b))


def _pack_row(rec):
    """rec = [ids, otype, ra, de, size_x_arcmin, size_y_arcmin, vmag, bmag, dmag,
    angl_deg]. dmag (display magnitude, field 9) and angl_deg (major-axis position
    angle in degrees N->E, field 10) are precomputed by build-swe; older 8/9-field
    inputs fall back gracefully so the tool stays backward-compatible."""
    ids, otype, ra, de, sx, sy, vmag, bmag = rec[:8]
    dmag = rec[8] if len(rec) > 8 else _display_vmag(vmag)
    angle_deg = rec[9] if len(rec) > 9 else float("nan")
    buf = bytearray(ROW_SIZE)
    vals = {
        "type": _pack_str(otype, 4),
        "vmag": struct.pack("<f", _mag_or_nan(vmag)),
        "bmag": struct.pack("<f", _mag_or_nan(bmag)),
        "dmag": struct.pack("<f", float(dmag)),
        "ra":   struct.pack("<f", float(ra)),
        "de":   struct.pack("<f", float(de)),
        "smax": struct.pack("<f", float(sx) * ARCMIN2RAD),
        "smin": struct.pack("<f", float(sy) * ARCMIN2RAD),
        # Major-axis position angle. NI2026 "PA" is deg N->E of the major axis,
        # which matches the engine's painter_project_ellipse angle convention, so
        # it feeds straight through (deg -> rad). NaN when unknown -> unrotated.
        "angl": struct.pack("<f", _angle_or_nan(angle_deg) * DEG2RAD),
        "morp": _pack_str("", 32),
        "ids":  _pack_str(ids, 256),
    }
    for (name, _t, _u, size), start in zip(COLUMNS, _STARTS):
        buf[start:start + size] = vals[name]
    return bytes(buf)


def _chunk(typ, data):
    return (typ + struct.pack("<i", len(data)) + data
            + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF))


def _encode_tile(pix, recs):
    nuniq = pix + 4 * (4 ** ORDER)
    raw = b"".join(_pack_row(r) for r in recs)          # flags=0: plain row-major
    comp = zlib.compress(raw, 9)
    tile_header = struct.pack("<iQ", 3, nuniq)           # version=3, nuniq
    table_header = struct.pack("<iiii", 0, ROW_SIZE, len(COLUMNS), len(recs))
    for (name, tchar, unit, size), start in zip(COLUMNS, _STARTS):
        table_header += (_pack_fixed(name, 4) + _pack_fixed(tchar, 4)
                         + struct.pack("<iii", unit, start, size))
    block = struct.pack("<ii", len(raw), len(comp)) + comp
    dso = tile_header + table_header + block
    js = json.dumps({"children_mask": 0}).encode("utf-8")   # Norder0 is the leaf
    return b"EPHE" + struct.pack("<i", 2) + _chunk(b"JSON", js) + _chunk(b"DSO ", dso)


# ---- round-trip decoder (mirror of src/eph-file.c reader) --------------------

def _decode_tile(data):
    assert data[:4] == b"EPHE"
    off = 8
    out = []
    while off < len(data):
        typ = data[off:off + 4]
        clen = struct.unpack("<i", data[off + 4:off + 8])[0]
        body = data[off + 8:off + 8 + clen]
        if typ == b"DSO ":
            p = 12                                     # skip version + nuniq
            flags, row_size, n_col, n_row = struct.unpack("<iiii", body[p:p + 16])
            p += 16
            cols = []
            for _ in range(n_col):
                nm = body[p:p + 4].rstrip(b"\x00").decode()
                tc = chr(body[p + 4])
                _u, st, sz = struct.unpack("<iii", body[p + 8:p + 20])
                cols.append((nm, tc, st, sz))
                p += 20
            usize, csize = struct.unpack("<ii", body[p:p + 8])
            p += 8
            raw = zlib.decompress(body[p:p + csize])
            assert len(raw) == usize == row_size * n_row
            assert flags == 0
            for i in range(n_row):
                ro = i * row_size
                rec = {}
                for nm, tc, st, sz in cols:
                    seg = raw[ro + st:ro + st + sz]
                    rec[nm] = (struct.unpack("<f", seg[:4])[0] if tc == "f"
                               else seg.split(b"\x00")[0].decode("utf-8"))
                out.append(rec)
        off += 12 + clen
    return out


# ---- build ------------------------------------------------------------------

def _display_vmag(vmag):
    v = _mag_or_nan(vmag)
    return DSO_DEFAULT_VMAG if math.isnan(v) else v


def build_eph(dsos):
    ra = np.array([d[2] for d in dsos], dtype=float)
    de = np.array([d[3] for d in dsos], dtype=float)
    hp = HEALPix(nside=NSIDE, order="nested")
    pix = np.asarray(hp.lonlat_to_healpix(ra * u.rad, de * u.rad))

    tiles = {}
    for d, p in zip(dsos, pix):
        tiles.setdefault(int(p), []).append(d)

    dirp = os.path.join(DSO_DIR, "Norder0", "Dir0")
    # wipe any previous survey tiles/orders
    for sub in ("Norder0", "Norder1", "Norder2", "Norder3"):
        s = os.path.join(DSO_DIR, sub)
        if os.path.isdir(s):
            for root, _dirs, files in os.walk(s, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
                os.rmdir(root)
    os.makedirs(dirp, exist_ok=True)

    total = 0
    for p in range(12):
        recs = sorted(tiles.get(p, []),
                      key=lambda d: d[8] if len(d) > 8 else _display_vmag(d[6]))
        blob = _encode_tile(p, recs)
        # round-trip self-check
        dec = _decode_tile(blob)
        assert len(dec) == len(recs), (p, len(dec), len(recs))
        with open(os.path.join(dirp, f"Npix{p}.eph"), "wb") as f:
            f.write(blob)
        total += len(recs)

    with open(os.path.join(DSO_DIR, "properties"), "w") as f:
        f.write("obs_description   = DSO survey from objects_catalogs "
                "(App-consistent) for stellarium-web\n"
                "hips_order_min    = 0\n"
                "type              = dso\n"
                "hips_tile_format  = eph\n")
    return total, {p: len(tiles.get(p, [])) for p in range(12)}


def selfcheck_roundtrip(dsos):
    """Verify a known object survives encode->decode with correct fields."""
    hp = HEALPix(nside=NSIDE, order="nested")
    m31 = next(d for d in dsos if d[0].split("|")[0] == "M 31")
    p = int(hp.lonlat_to_healpix(m31[2] * u.rad, m31[3] * u.rad))
    dec = _decode_tile(_encode_tile(p, [m31]))[0]
    assert dec["type"] == m31[1], (dec["type"], m31[1])
    assert abs(dec["ra"] - m31[2]) < 1e-6 and abs(dec["de"] - m31[3]) < 1e-6
    assert abs(dec["smax"] - m31[4] * ARCMIN2RAD) < 1e-6   # float32 precision
    assert dec["ids"].split("|")[0] == "M 31"
    assert abs(dec["vmag"] - m31[6]) < 1e-4
    if len(m31) > 9:                                       # position angle round-trips
        want = _angle_or_nan(m31[9]) * DEG2RAD
        got = dec["angl"]
        assert (math.isnan(want) and math.isnan(got)) or abs(got - want) < 1e-6, \
            (got, want)


def write_skyculture_names(sky_names):
    common = {key: [{"english": en}] for key, en, _tr in sky_names}
    block = "  \"common_names\": " + json.dumps(
        common, ensure_ascii=False, separators=(",", ":")) + ",\n"
    text = open(SKYCULTURE, encoding="utf-8").read()
    text = re.sub(r'  "common_names":[^\n]*\n', "", text, count=1)   # idempotent
    assert text.startswith("{\n"), "unexpected skyculture index.json format"
    text = "{\n" + block + text[2:]
    with open(SKYCULTURE, "w", encoding="utf-8") as f:
        f.write(text)
    return len(common)


def write_i18n(sky_names):
    per_lang = {}
    for _key, en, tr in sky_names:
        for lang, translated in tr.items():
            per_lang.setdefault(lang, {})[en] = translated
    os.makedirs(I18N_DIR, exist_ok=True)
    written = {}
    for lang, add in per_lang.items():
        path = os.path.join(I18N_DIR, f"{lang}.json")
        base = {}
        if os.path.isfile(path):
            base = json.load(open(path, encoding="utf-8"))
        base.update(add)                       # App names win over #5 po names
        with open(path, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, separators=(",", ":"))
        written[lang] = len(add)
    return written


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    data = json.load(open(src, encoding="utf-8"))
    dsos, sky_names = data["dsos"], data["sky_names"]

    selfcheck_roundtrip(dsos)
    total, per_tile = build_eph(dsos)
    n_cn = write_skyculture_names(sky_names)
    per_lang = write_i18n(sky_names)

    print(f"eph: {total} DSOs across 12 Norder0 tiles -> {DSO_DIR}")
    print("     per-tile:", per_tile)
    print(f"skyculture common_names: {n_cn} entries -> {SKYCULTURE}")
    print("sky-i18n overlaid:", per_lang)

    # The App catalog has no LMC (no NGC number), so the survey rebuild just
    # dropped it; re-inject it now rather than trusting anyone to remember.
    # (This once silently lost the Large Magellanic Cloud, see the internal
    # design notes.)
    tools = os.path.dirname(__file__)
    subprocess.check_call([sys.executable,
                           os.path.join(tools, "add-lmc-dso.py"), "--apply"])
    # Then the full post-build patch/cleanup chain (zh name patches, the
    # cleaners, app-font refresh). Rebuilds once silently resurrected dirty
    # zh names because these passes were memory-driven; the chain is
    # idempotent, so always run all of it here.
    subprocess.check_call([sys.executable,
                           os.path.join(tools, "finish-sky-i18n.py")])


if __name__ == "__main__":
    main()
