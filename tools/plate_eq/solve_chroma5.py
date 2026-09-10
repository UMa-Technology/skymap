"""v5: per-CHANNEL sharp region leveling (the residual colour blocks).

R-channel offsets live on the RED plate tessellation, B on the BLUE one (dead-blue
GAP zones follow the red tessellation), G = synthesized 0.5(R+B). Per channel:
robust star-masked background - 2.5deg local trend -> per-region dark-pixel median
deviation -> minus 4deg neighbourhood reference of eligible regions -> capped
constant, rendered SHARP on that channel's own tessellation at tile resolution.
Saves dc5_chroma.npz.
"""
import os, sys, numpy as np, healpy as hp
SC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SC)
NS = 512; NPIX = hp.nside2npix(NS); ar = np.arange(NPIX)
from seamnet_common import load_state, load_labels

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
cshr = np.zeros(NPIX, np.float32)
ii = np.searchsorted(U0, comb)
ok = (ii < len(U0)) & (U0[np.clip(ii, 0, len(U0) - 1)] == comb)
cshr[ok] = CREG[ii[ok]]
lumadd = drest['dR'] + resid4 + cshr
CUR = {'R': (R + lumadd).astype(np.float64), 'G': (G + lumadd).astype(np.float64),
       'B': (B + lumadd).astype(np.float64)}
L = 0.299 * CUR['R'] + 0.587 * CUR['G'] + 0.114 * CUR['B']
labr, labb_eff = load_labels()      # red winner idx; blue idx or red+20000 in gaps

def smooth(m, fwhm):
    return hp.reorder(hp.smoothing(hp.reorder(m, n2r=True), fwhm=np.radians(fwhm)), r2n=True)

def solve_channel(vals, lab, capin=4.0, capout=2.5):
    bg = vals.copy()
    for it in range(3):
        s = smooth(bg, 1.5)
        resid = bg - s
        sig = 1.4826 * np.median(np.abs(resid - np.median(resid)))
        bg = np.where(resid > 2.0 * sig, s, bg)
    dev = bg - smooth(bg, 2.5)
    u, inv = np.unique(lab, return_inverse=True)
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
    ns = smooth(fld, 4.0); ds = smooth(wf, 4.0)
    refp = np.where(ds > 0.05, ns / np.maximum(ds, 0.05), 0.0)
    ref = np.zeros(NL)
    rpo = refp[order]
    for k, segr in zip(range(NL), np.split(rpo, starts[1:])):
        ref[k] = np.mean(segr)
    cap = np.where(babs < 20, capin, capout)
    c = np.where(eligible, -np.clip(darkdev - ref, -cap, cap), 0.0)
    act = np.abs(c) > 0.2
    print("  regions %d eligible %d active %d |c| p95 %.2f max %.2f" %
          (NL, int(eligible.sum()), int(act.sum()),
           np.percentile(np.abs(c[act]), 95) if act.any() else 0, np.abs(c).max()), flush=True)
    return u, c.astype(np.float32)

print("R channel (red tessellation):", flush=True)
uR, cR = solve_channel(CUR['R'], labr)
print("B channel (blue tessellation incl. GAP fallback):", flush=True)
uB, cB = solve_channel(CUR['B'], labb_eff)
np.savez(SC + "/dc5_chroma.npz", uR=uR, cR=cR, uB=uB, cB=cB)

# zone safety stats on the resulting per-pixel chroma correction
pR = cR[np.searchsorted(uR, labr)]
pB = cB[np.searchsorted(uB, labb_eff)]
pG = 0.5 * (pR + pB)
for nmz, (raz, dez) in (("musca", (188, -62)), ("crux", (187, -60)), ("galcenter", (266, -29)),
                        ("pipe", (262, -25)), ("cygnus", (305, 38)), ("lmc", (80, -69)),
                        ("orionbelt", (84.5, -1.5))):
    pixz = hp.query_disc(NS, hp.ang2vec(raz, dez, lonlat=True), np.radians(5), nest=True)
    ca = np.abs(np.stack([pR[pixz], pG[pixz], pB[pixz]]))
    cc = np.abs(pR[pixz] - pB[pixz])
    print("zone %-9s |c| mean %.2f p99 %.2f | |R-B shift| p99 %.2f" %
          (nmz, ca.mean(), np.percentile(ca, 99), np.percentile(cc, 99)), flush=True)
print("DONE")
