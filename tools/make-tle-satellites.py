#!/usr/bin/python3

# Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
#
# This program is licensed under the terms of the GNU AGPL v3, or
# alternatively under a commercial licence.
#
# The terms of the AGPL v3 license can be found in the main directory of this
# repository.

# Bake a build-day TLE snapshot for the space stations (ISS + the Chinese
# Space Station / Tiangong modules) into a small plain-JSON baseline that ships
# with the offline app. The frontend glue (apps/*/src/assets/satellites.js)
# loads it at startup via createObj so the stations render immediately with no
# network, and later overwrites the positions in place from fresh TLE pushed by
# the host (Flutter fetches CelesTrak) via the satellites_set_tle C function.
#
# TLE goes stale (LEO position drifts ~1-5 km/day, degrees within a week), so
# this snapshot is only the offline fallback; the live refresh is what keeps it
# accurate. Re-run this at release time to keep the fallback reasonably current.
#
# Output: apps/skydata/tle_satellite_baseline.json  (committed; served to both
# frontends through the public/skydata -> ../../skydata symlinks).

import json
import os

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'apps', 'skydata', 'tle_satellite_baseline.json')

# CelesTrak GROUP=stations bundles the ISS + CSS modules + docked craft. FORMAT
# MUST be explicit: CelesTrak's gp.php default is CSV, not TLE.
GROUP_URL = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle'
CATNR_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=%d&FORMAT=tle'

# The objects we ship, with their display name and standard magnitude.
# `name` is the ENGLISH msgid used as the on-sky label; the engine translates it
# per the sky-language setting through the sky-i18n catalog (the label render
# path runs designation_cleanup(..., DSGN_TRANSLATE) -> sys_translate("sky",...)).
# The localized strings live in tools/add-sky-i18n-satellites.py — keep the two
# in sync. `mag` is the engine's standard magnitude (satellites.c stdmag
# convention: intrinsic brightness; the engine derives apparent vmag from
# range/phase). We ship only the two stations users care about: ISS and the
# Chinese Space Station. NORAD 48274 (Tianhe core) stands for the whole station
# (labeled Tiangong / 天宫) — the docked Wentian/Mengtian modules fly at the same
# on-sky position and can't be individually picked, so they are intentionally
# not shipped (the C-side persistent list and the frontend whitelist match this).
TARGETS = {
    25544: {'name': 'ISS',      'mag': -1.8},  # International Space Station
    48274: {'name': 'Tiangong', 'mag': 0.0},   # CSS Tianhe core = the station
}


def parse_tle(text):
    """Yield (line1, line2, norad) from CelesTrak 3-line-per-object TLE text."""
    lines = [l.rstrip('\r\n') for l in text.splitlines() if l.strip()]
    # Blocks are [name, line1, line2]; be lenient about a missing name line.
    i = 0
    while i + 1 < len(lines):
        if lines[i].startswith('1 ') and lines[i + 1].startswith('2 '):
            l1, l2 = lines[i], lines[i + 1]
            i += 2
        elif (i + 2 < len(lines) and lines[i + 1].startswith('1 ')
              and lines[i + 2].startswith('2 ')):
            l1, l2 = lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue
        if len(l1) >= 69 and len(l2) >= 69:
            yield l1, l2, int(l1[2:7])  # NORAD id = columns 3-7 of line 1


def record(norad, l1, l2):
    t = TARGETS[norad]
    return {
        'model': 'tle_satellite',
        'types': ['Asa'],
        'model_data': {
            'norad_number': norad,
            'tle': [l1, l2],
            'mag': t['mag'],
        },
        'names': ['NAME %s' % t['name'], 'NORAD %d' % norad],
    }


def run():
    recs = {}
    text = requests.get(GROUP_URL, timeout=60).text
    for l1, l2, norad in parse_tle(text):
        if norad in TARGETS:
            recs[norad] = record(norad, l1, l2)

    # A CSS module occasionally drops out of GROUP=stations; fetch it directly.
    for norad in set(TARGETS) - set(recs):
        print('fallback per-CATNR fetch for %d' % norad)
        text = requests.get(CATNR_URL % norad, timeout=60).text
        for l1, l2, n in parse_tle(text):
            if n == norad:
                recs[norad] = record(norad, l1, l2)

    missing = set(TARGETS) - set(recs)
    if missing:
        raise SystemExit('could not fetch TLE for NORAD ids: %s' % sorted(missing))

    # Stable order (bright ISS first, then the CSS assembly) for a clean diff.
    ordered = [recs[n] for n in sorted(TARGETS, key=lambda n: TARGETS[n]['mag'])]
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(ordered, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('wrote %d satellites -> %s' % (len(ordered), OUT))


if __name__ == '__main__':
    run()
