"""v6: wide-window incremental leveling (user: "4 deg too small -> 10 deg to
include the deviant tile clusters").

Same estimator as v4/v5 but TREND fwhm 6 deg (was 2.5) and neighbourhood reference
10 deg (was 4), solved ON TOP of the current state (chain+dc4+dc5) as increments:
clusters of commonly-offset plates now deviate from a reference anchored by the
wider normal surroundings, so the whole cluster gets lifted, not just its outline.
Outputs dc6_sharp.npz (L constants on combined regions) + dDark6_resid.npy (smooth
subband residual) + dc6_chroma.npz (per-mosaic channel constants).
"""
import os, sys, numpy as np, healpy as hp
SC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SC)
NS = 512; NPIX = hp.nside2npix(NS); ar = np.arange(NPIX)
from seamnet_common import load_state, load_labels

TREND = 6.0
REF = 10.0

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
c5 = np.load(SC + "/dc5_chroma.npz")
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
labr, labb_eff = load_labels()

def lut(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

cl4 = lut(U0, CREG, comb)
pR5 = lut(c5['uR'], c5['cR'], labr)
pB5 = lut(c5['uB'], c5['cB'], labb_eff)
lum = drest['dR'] + resid4 + cl4
CUR = {'R': (R + lum + pR5).astype(np.float64),
       'G': (G + lum + 0.5 * (pR5 + pB5)).astype(np.float64),
       'B': (B + lum + pB5).astype(np.float64)}
L = 0.299 * CUR['R'] + 0.587 * CUR['G'] + 0.114 * CUR['B']

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

def dev_field(vals):
    bg = vals.copy()
    for it in range(3):
        s = smooth(bg, 1.5)
        resid = bg - s
        sig = 1.4826 * np.median(np.abs(resid - np.median(resid)))
        bg = np.where(resid > 2.0 * sig, s, bg)
    return bg - smooth(bg, TREND)

def subband_solve(dev, lab_ids, capin, capout, tag):
    """generic: per-label dark-median deviation minus 10-deg eligible reference."""
    u, inv = np.unique(lab_ids, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(inv, kind='stable')
    starts = np.unique(inv[order], return_index=True)[1]
    NL = len(u)
    darkdev = np.zeros(NL); darkmed = np.full(NL, 1e9)
    tex = np.zeros(NL); size = np.zeros(NL); babs = np.zeros(NL)
    Lo = L[order]; dvo = dev[order]; gbo = np.abs(gb)[order]
    for k, segL, segd, segb in zip(range(NL), np.split(Lo, starts[1:]),
                                   np.split(dvo, starts[1:]), np.split(gbo, starts[1:])):
        if len(segL) < 12: continue
        dk = segL <= np.percentile(segL, 40)
        darkdev[k] = np.median(segd[dk])
        darkmed[k] = np.median(segL[dk])
        tex[k] = np.percentile(segL, 75) - np.percentile(segL, 25)
        size[k] = len(segL); babs[k] = np.median(segb)
    eligible = (darkmed < 16.0) & (tex < 18.0) & (size >= 12)
    fld = np.zeros(NPIX); wf = np.zeros(NPIX)
    el_pix = eligible[inv]
    fld[el_pix] = darkdev[inv[el_pix]]; wf[el_pix] = 1.0
    ns = smooth(fld, REF); ds = smooth(wf, REF)
    refp = np.where(ds > 0.05, ns / np.maximum(ds, 0.05), 0.0)
    ref = np.zeros(NL)
    rpo = refp[order]
    for k, segr in zip(range(NL), np.split(rpo, starts[1:])):
        ref[k] = np.mean(segr)
    cap = np.where(babs < 20, capin, capout)
    c = np.where(eligible, -np.clip(darkdev - ref, -cap, cap), 0.0)
    act = np.abs(c) > 0.2
    print("%s: labels %d eligible %d active %d |c| p95 %.2f max %.2f" %
          (tag, NL, int(eligible.sum()), int(act.sum()),
           np.percentile(np.abs(c[act]), 95) if act.any() else 0, np.abs(c).max()), flush=True)
    return u, c.astype(np.float32), inv, eligible, size

# ---- luminance on combined tessellation, subbands like v4 ----
devL = dev_field(L)
u0c, lab0 = np.unique(comb, return_inverse=True)
order0 = np.argsort(lab0, kind='stable'); lo0 = lab0[order0]
gbo = gb[order0]; pix_o = ar[order0]
starts0 = np.unique(lo0, return_index=True)[1]
band = np.zeros(NPIX, np.int64)
for k, seg_pix, seg_gb in zip(np.unique(lo0), np.split(pix_o, starts0[1:]), np.split(gbo, starts0[1:])):
    if len(seg_pix) < 8: continue
    band[seg_pix] = np.digitize(seg_gb, np.percentile(seg_gb, [25, 50, 75]))
sb = lab0 * 4 + band
us, csb, inv_sb, elig_sb, size_sb = subband_solve(devL, sb, 6.0, 3.0, "L subbands")
# split region constant / smooth residual (same as v4)
NL0 = len(u0c)
c_reg = np.zeros(NL0); w_reg = np.zeros(NL0)
el_share = np.zeros(NL0); tot_share = np.zeros(NL0)
reg_idx = (us // 4).astype(np.int64)
for k in range(len(us)):
    tot_share[reg_idx[k]] += size_sb[k]
    if elig_sb[k]:
        el_share[reg_idx[k]] += size_sb[k]
        c_reg[reg_idx[k]] += csb[k] * size_sb[k]
        w_reg[reg_idx[k]] += size_sb[k]
c_reg = np.where(w_reg > 0, c_reg / np.maximum(w_reg, 1), 0.0)
okreg = (tot_share > 0) & (el_share / np.maximum(tot_share, 1) >= 0.6)
c_reg = np.where(okreg, c_reg, 0.0)
resid_sb = csb - c_reg[reg_idx]
resid_sb[~elig_sb] = 0.0
c_resid = smooth(resid_sb[inv_sb], 0.3)
np.savez(SC + "/dc6_sharp.npz", region_ids=u0c, c_reg=c_reg.astype(np.float32), bmax=BMAX)
np.save(SC + "/dDark6_resid.npy", c_resid.astype(np.float32))
act = np.abs(c_reg) > 0.2
print("L region constants: %d active | p95 %.2f max %.2f | resid |p95| %.2f" %
      (int(act.sum()), np.percentile(np.abs(c_reg[act]), 95) if act.any() else 0,
       np.abs(c_reg).max(), np.percentile(np.abs(c_resid), 95)), flush=True)

# ---- chroma per mosaic ----
devR = dev_field(CUR['R'])
uR6, cR6, _, _, _ = subband_solve(devR, labr, 4.0, 2.5, "R regions")
devB = dev_field(CUR['B'])
uB6, cB6, _, _, _ = subband_solve(devB, labb_eff, 4.0, 2.5, "B regions")
np.savez(SC + "/dc6_chroma.npz", uR=uR6, cR=cR6, uB=uB6, cB=cB6)

# zone stats incl. the user's Ara screenshot area
pL6 = c_reg[np.searchsorted(u0c, comb)] + c_resid
pR6 = lut(uR6, cR6, labr); pB6 = lut(uB6, cB6, labb_eff)
for nmz, (raz, dez) in (("araNGC6193", (250.3, -48.8)), ("musca", (188, -62)),
                        ("crux", (187, -60)), ("galcenter", (266, -29)), ("pipe", (262, -25)),
                        ("cygnus", (305, 38)), ("lmc", (80, -69))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(5), nest=True)
    cz = np.abs(pL6[pixz])
    print("zone %-11s |L6| mean %.2f p99 %.2f | |R6-B6| p99 %.2f" %
          (nmz, cz.mean(), np.percentile(cz, 99),
           np.percentile(np.abs(pR6[pixz] - pB6[pixz]), 99)), flush=True)
print("DONE")
