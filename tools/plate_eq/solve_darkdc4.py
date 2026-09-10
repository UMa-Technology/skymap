"""Dark leveling v4: trend-referenced, locally-anchored, rendered SHARP.

Estimation: robust star-masked background bg; local trend = smooth(bg, 2.5deg);
per (combined-region x b-quartile-band) subband: dark-pixel median of dev=bg-trend.
Correction = -(darkdev - local reference), reference = neighbourhood median of the
darkdev field (the user's 3x3-neighbourhood idea, in region space via 4deg smoothing).
Eligibility gates (dark + low texture) protect galcenter/bright nebulae; |b|-banded caps.

Output split for application:
  dc4_region.json-ish npz: per combined-region SHARP constant (size-weighted mean of
    its band corrections) -> rendered at tile resolution on exact plate boundaries.
  dDark4_resid.npy: per-subband residual minus the region constant, smoothed 0.3deg
    -> goes through the normal nside-512 upsample path (no sharp internal band edges).
"""
import os, numpy as np, healpy as hp
SC = os.path.dirname(os.path.abspath(__file__))
NS = 512; NPIX = hp.nside2npix(NS); ar = np.arange(NPIX)

import sys
sys.path.insert(0, SC)
from seamnet_common import load_state
R, G, B, gb = load_state()
dr = np.load(SC + "/delta_restore.npz")
L = (0.299 * R + 0.587 * G + 0.114 * B + dr['dR']).astype(np.float64)

def smooth(m, fwhm_deg):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm_deg)), r2n=True)

# robust star/structure-masked background (3 iterations)
bg = L.copy()
for it in range(3):
    s = smooth(bg, 1.5)
    resid = bg - s
    sig = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    bg = np.where(resid > 2.0 * sig, s, bg)
trend = smooth(bg, 2.5)
dev = bg - trend

wr = np.load(SC + "/winner_red.npz", allow_pickle=True)
wb = np.load(SC + "/winner_blue.npz", allow_pickle=True)
BMAX = int(wb['winner'].max() + 2)
comb = wr['winner'].astype(np.int64) * BMAX + (wb['winner'].astype(np.int64) + 1)
u0, lab0 = np.unique(comb, return_inverse=True); NL0 = len(u0)

# per-region b-quartile bands (as v3)
order0 = np.argsort(lab0, kind='stable'); lo0 = lab0[order0]; gbo = gb[order0]; pix_o = ar[order0]
starts0 = np.unique(lo0, return_index=True)[1]
band = np.zeros(NPIX, np.int64)
qcuts = {}
for k, seg_pix, seg_gb in zip(np.unique(lo0), np.split(pix_o, starts0[1:]), np.split(gbo, starts0[1:])):
    if len(seg_pix) < 8: continue
    qs = np.percentile(seg_gb, [25, 50, 75])
    band[seg_pix] = np.digitize(seg_gb, qs)
    qcuts[int(k)] = qs
lab = lab0 * 4 + band
us, lab = np.unique(lab, return_inverse=True); NL = len(us)

order = np.argsort(lab, kind='stable'); lo = lab[order]
Lo = L[order]; devo = dev[order]; gbo2 = np.abs(gb[order])
starts = np.unique(lo, return_index=True)[1]
darkdev = np.zeros(NL); darkmed = np.full(NL, 1e9); tex = np.zeros(NL)
size = np.zeros(NL); babs = np.zeros(NL)
for k, segL, segd, segb in zip(np.unique(lo), np.split(Lo, starts[1:]),
                               np.split(devo, starts[1:]), np.split(gbo2, starts[1:])):
    if len(segL) < 12: continue
    dk = segL <= np.percentile(segL, 40)
    darkdev[k] = np.median(segd[dk])
    darkmed[k] = np.median(segL[dk])
    tex[k] = np.percentile(segL, 75) - np.percentile(segL, 25)
    size[k] = len(segL); babs[k] = np.median(segb)
eligible = (darkmed < 16.0) & (tex < 18.0) & (size >= 12)
print("subbands:", NL, "eligible:", int(eligible.sum()), flush=True)

# local reference: neighbourhood median of eligible darkdev (4deg smoothing of the field)
fld = np.zeros(NPIX); wfld = np.zeros(NPIX)
el_pix = eligible[lab]
fld[el_pix] = darkdev[lab[el_pix]]; wfld[el_pix] = 1.0
num_s = smooth(fld, 4.0); den_s = smooth(wfld, 4.0)
ref_pix = np.where(den_s > 0.05, num_s / np.maximum(den_s, 0.05), 0.0)
# per-subband reference = mean of ref over its pixels
o2 = np.argsort(lab, kind='stable')
refo = ref_pix[o2]
ref_sb = np.zeros(NL)
for k, segr in zip(np.unique(lab[o2]), np.split(refo, np.unique(lab[o2], return_index=True)[1][1:])):
    ref_sb[k] = np.mean(segr)

cap = np.where(babs < 20, 6.0, 3.0)
c_sb = np.where(eligible, -np.clip(darkdev - ref_sb, -cap, cap), 0.0)

# split: sharp per-REGION constant + smooth per-subband residual
c_reg = np.zeros(NL0)
w_reg = np.zeros(NL0)
# us = lab0_index*4 + band, so us//4 IS the region index (0..NL0-1)
reg_idx_of_sb = (us // 4).astype(np.int64)
for k in range(NL):
    if eligible[k]:
        c_reg[reg_idx_of_sb[k]] += c_sb[k] * size[k]
        w_reg[reg_idx_of_sb[k]] += size[k]
c_reg = np.where(w_reg > 0, c_reg / np.maximum(w_reg, 1), 0.0)
# region constant only where the whole region is predominantly eligible (>=60% px)
el_share = np.zeros(NL0)
tot_share = np.zeros(NL0)
for k in range(NL):
    tot_share[reg_idx_of_sb[k]] += size[k]
    if eligible[k]: el_share[reg_idx_of_sb[k]] += size[k]
okreg = (tot_share > 0) & (el_share / np.maximum(tot_share, 1) >= 0.6)
c_reg = np.where(okreg, c_reg, 0.0)

resid_sb = c_sb - c_reg[reg_idx_of_sb]
resid_sb[~eligible] = 0.0
c_resid = resid_sb[lab]
c_resid_s = smooth(c_resid, 0.3)

np.savez(SC + "/dc4_sharp.npz", region_ids=u0, c_reg=c_reg.astype(np.float32), bmax=BMAX)
np.save(SC + "/dDark4_resid.npy", c_resid_s.astype(np.float32))

act = np.abs(c_reg) > 0.2
print("regions with sharp constant: %d/%d | |c_reg| p95 %.2f max %.2f" %
      (int(act.sum()), NL0, np.percentile(np.abs(c_reg[act]), 95) if act.any() else 0, np.abs(c_reg).max()), flush=True)
print("resid field |p95| %.2f" % np.percentile(np.abs(c_resid_s), 95), flush=True)
full = c_reg[np.searchsorted(u0, comb)] + c_resid_s
for nmz, (raz, dez) in (("musca", (188, -62)), ("crux", (187, -60)), ("galcenter", (266, -29)),
                        ("pipe", (262, -25)), ("cygnus", (305, 38)), ("lmc", (80, -69))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(5), nest=True)
    cz = np.abs(full[pixz])
    print("zone %-9s meanabs %.2f p99 %.2f" % (nmz, cz.mean(), np.percentile(cz, 99)), flush=True)
# check the Crux offenders got leveled
dev_after = dev + full
disc = hp.query_disc(NS, hp.ang2vec(187.0, -62.0, lonlat=True), np.radians(6), nest=True)
sub = comb[disc]
sp = []
for uu in np.unique(sub):
    m = sub == uu
    if m.sum() < 60: continue
    segL = L[disc[m]]
    dk = segL <= np.percentile(segL, 40)
    sp.append((np.median(dev[disc[m]][dk]), np.median(dev_after[disc[m]][dk])))
sp = np.array(sp)
print("crux/musca region darkdev spread: before std %.2f p2p %.2f -> after std %.2f p2p %.2f" %
      (sp[:, 0].std(), sp[:, 0].max() - sp[:, 0].min(), sp[:, 1].std(), sp[:, 1].max() - sp[:, 1].min()), flush=True)
print("DONE")
