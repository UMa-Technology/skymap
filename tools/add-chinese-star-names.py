#!/usr/bin/env python3
# Stellarium Web Engine
#
# Add Chinese asterism (三垣二十八宿 / 星官) star names to the WESTERN skyculture.
#
# The app ships the western skyculture; its HIP-keyed common_names only carry the
# stars that also have a Western proper name (Aldebaran -> 毕宿五, ...), so the
# many Chinese-only stars (毕宿二 = HIP 20648, ...) show no Chinese name. The full
# Chinese naming lives in the *unloaded* chinese skyculture
# (skycultures/chinese/index.json, HIP -> native). This tool ports that set into
# the western skyculture:
#   - western/index.json  common_names["HIP n"] = [{"english": <designation>}]
#       where <designation> is the star's Bayer/Flamsteed designation (e.g.
#       "γ² Vel", "27 Cas") derived from the star survey, so NON-Chinese languages
#       fall back to the designation.
#   - sky-i18n/zh_cn.json  <designation> -> Chinese name (from chinese skyculture)
#   - sky-i18n/zh_tw.json  <designation> -> Traditional (opencc s2t)
# So Chinese shows 毕宿二/畢宿二, every other language shows the designation.
#
# Only stars that are (a) in the star survey (renderable) and (b) not already
# named in the western skyculture are added. PURELY ADDITIVE / IDEMPOTENT: it
# never overwrites an existing common_name or a real translation.
#
# Runs AFTER make-dso-survey.py (which rewrites the western common_names block).
#
# Usage:  tools/add-chinese-star-names.py [--apply]   (default: dry-run report)

import glob, json, os, re, struct, sys, zlib

# Trailing Chinese-skyculture markers that are metadata, not part of the name:
# '*' (annotation), '?' (uncertain id), '[宿名]' (mansion/enclosure). Stripped so
# labels stay clean. See tools/clean-sky-i18n-markers.py (the catch-all pass).
_MARKERS = re.compile(r"\s*(?:\[[^\]]*\]|[*?？﹖])+\s*$")

def strip_markers(name):
    stripped = _MARKERS.sub("", name)
    return stripped or name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAR_DIR = os.path.join(ROOT, "apps", "skydata", "stars")
CHINESE = os.path.join(ROOT, "apps", "skydata", "skycultures", "chinese", "index.json")
WESTERN = os.path.join(ROOT, "apps", "skydata", "skycultures", "western", "index.json")
I18N = os.path.join(ROOT, "apps", "skydata", "sky-i18n")

# ---- star survey decode (eph, byte-shuffled) --------------------------------

def _unshuffle(buf, row_size, n_row):
    out = bytearray(len(buf))
    for b in range(row_size):
        base = b * n_row
        for r in range(n_row):
            out[r * row_size + b] = buf[base + r]
    return bytes(out)

def _decode_star_tile(data):
    off, rows = 8, []
    while off < len(data) - 8:
        typ = data[off:off+4]; clen = struct.unpack('<i', data[off+4:off+8])[0]
        body = data[off+8:off+8+clen]
        if typ == b'STAR':
            p = 12
            flags, row_size, n_col, n_row = struct.unpack('<iiii', body[p:p+16]); p += 16
            cols = []
            for _ in range(n_col):
                nm = body[p:p+4].rstrip(b'\x00').decode(); tc = chr(body[p+4])
                _u, st, sz = struct.unpack('<iii', body[p+8:p+20]); cols.append((nm, tc, st, sz)); p += 20
            usize, csize = struct.unpack('<ii', body[p:p+8]); p += 8
            raw = zlib.decompress(body[p:p+csize])
            if flags & 1:
                raw = _unshuffle(raw, row_size, n_row)
            for i in range(n_row):
                ro = i * row_size; rec = {}
                for nm, tc, st, sz in cols:
                    seg = raw[ro+st:ro+st+sz]
                    if tc == 'i': rec[nm] = struct.unpack('<i', seg[:4])[0]
                    elif tc == 'f': rec[nm] = struct.unpack('<f', seg[:4])[0]
                    else: rec[nm] = seg.split(b'\x00')[0].decode('utf-8', 'replace')
                rows.append(rec)
        off += 8 + clen + 4
    return rows

def load_star_ids():
    hip2ids = {}
    for f in glob.glob(os.path.join(STAR_DIR, "Norder*/Dir*/*.eph")):
        for r in _decode_star_tile(open(f, 'rb').read()):
            if r.get('hip') and r['hip'] not in hip2ids:
                hip2ids[r['hip']] = r['ids']
    return hip2ids

# ---- Bayer / Flamsteed designation -> display form (mirror designation.c) ----

GREEK = {"alf":"α","bet":"β","gam":"γ","del":"δ","eps":"ε","zet":"ζ","eta":"η",
         "tet":"θ","iot":"ι","kap":"κ","lam":"λ","mu":"μ","nu":"ν","xi":"ξ",
         "ksi":"ξ","omi":"ο","pi":"π","rho":"ρ","sig":"σ","tau":"τ","ups":"υ",
         "phi":"φ","chi":"χ","psi":"ψ","ome":"ω"}
SUP = {c: s for c, s in zip("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")}

def _sup(digits):
    return "".join(SUP[c] for c in str(int(digits))) if digits else ""

def clean_designation(dsgn):
    """'* gam02 Vel' -> 'γ² Vel', '* 27 Cas' -> '27 Cas'. None if not Bayer/Flamsteed."""
    if dsgn.startswith("V* "): d = dsgn[3:]
    elif dsgn.startswith("* "): d = dsgn[2:]
    else: return None
    toks = d.split()
    if len(toks) < 2: return None
    head, const = toks[0], toks[1]
    if head.isdigit():                                   # Flamsteed
        return "%d %s" % (int(head), const)
    letter, rest = None, head
    for ln in (3, 2):                                    # Greek abbrev
        if head[:ln].lower() in GREEK:
            letter, rest = GREEK[head[:ln].lower()], head[ln:]; break
    if letter is None:                                   # single Latin letter
        if head[0].isalpha(): letter, rest = head[0], head[1:]
        else: return None
    return "%s%s %s" % (letter, _sup("".join(c for c in rest if c.isdigit())), const)

def pivot_candidates(hip, ids):
    """Ordered designation candidates (Bayer, then Flamsteed, then HIP) used as
    the translation key / non-Chinese label. Multiple candidates let the caller
    resolve the rare case where a Bayer letter is (erroneously) shared by two
    stars: the real one keeps the Bayer, the other falls back to its Flamsteed."""
    out = []
    for name in ids.split("|"):
        if name.startswith("* ") or name.startswith("V* "):
            got = clean_designation(name)
            if got and got not in out: out.append(got)
    out.append("HIP %d" % hip)
    return out

# ---- build additions ---------------------------------------------------------

def build():
    hip2ids = load_star_ids()
    ch = json.load(open(CHINESE, encoding="utf-8"))["common_names"]
    ch_names = {}                                        # hip -> primary native name
    for k, v in ch.items():
        if k.startswith("HIP "):
            names = [e.get("native") for e in v if e.get("native")]
            if names: ch_names[int(k[4:])] = strip_markers(names[0])
    west = json.load(open(WESTERN, encoding="utf-8"))["common_names"]
    west_hip = set(k for k in west if k.startswith("HIP "))

    from opencc import OpenCC
    s2t = OpenCC("s2t").convert

    west_add, zh_cn_add, zh_tw_add = {}, {}, {}
    used_pivot, skipped = {}, {"faint": 0, "named": 0, "collision": 0}
    for hip, native in sorted(ch_names.items()):
        key = "HIP %d" % hip
        if key in west_hip: skipped["named"] += 1; continue
        if hip not in hip2ids: skipped["faint"] += 1; continue
        piv = None
        for cand in pivot_candidates(hip, hip2ids[hip]):
            if cand not in used_pivot:                   # first free designation
                piv = cand; break
        if piv is None:                                  # all taken (never: HIP unique)
            skipped["collision"] += 1; continue
        used_pivot[piv] = native
        west_add[key] = [{"english": piv}]
        zh_cn_add[piv] = native
        zh_tw_add[piv] = s2t(native)
    return west_add, zh_cn_add, zh_tw_add, skipped

# ---- writers (idempotent, format-preserving) --------------------------------

def patch_western(west_add):
    text = open(WESTERN, encoding="utf-8").read()
    cn = json.load(open(WESTERN, encoding="utf-8"))["common_names"]
    added = 0
    for k, v in west_add.items():
        if k not in cn: cn[k] = v; added += 1
    block = '  "common_names":' + json.dumps(cn, ensure_ascii=False, separators=(",", ":")) + ",\n"
    text = re.sub(r'  "common_names":[^\n]*\n', "", text, count=1)
    text = "{\n" + block + text[2:]
    open(WESTERN, "w", encoding="utf-8").write(text)
    return added

def patch_i18n(lang, add):
    path = os.path.join(I18N, lang + ".json")
    cat = json.load(open(path, encoding="utf-8"))
    added = 0
    for k, v in add.items():
        if cat.get(k) in (None, k):                      # missing or identity
            cat[k] = v; added += 1
    json.dump(cat, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return added

def main():
    apply = "--apply" in sys.argv
    west_add, zh_cn_add, zh_tw_add, skipped = build()
    print("Chinese star names to add: %d" % len(west_add))
    print("  skipped: already-named=%d  too-faint=%d  designation-collision=%d"
          % (skipped["named"], skipped["faint"], skipped["collision"]))
    print("  samples:")
    for k in ["HIP 20648", "HIP 20885", "HIP 20713", "HIP 18724", "HIP 39953"]:
        if k in west_add:
            piv = west_add[k][0]["english"]
            print("    %-10s en=%-9s zh_cn=%s  zh_tw=%s" % (k, piv, zh_cn_add[piv], zh_tw_add[piv]))
    if not apply:
        print("\n(dry-run; pass --apply to write)"); return
    w = patch_western(west_add)
    c = patch_i18n("zh_cn", zh_cn_add)
    t = patch_i18n("zh_tw", zh_tw_add)
    print("\napplied: western +%d,  zh_cn +%d,  zh_tw +%d" % (w, c, t))

if __name__ == "__main__":
    main()
