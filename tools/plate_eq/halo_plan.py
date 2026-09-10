"""Halo v3 planner: PERFECT-CIRCLE symmetric reference per star (user directive).

P_ref(r) per channel = azimuthal upper envelope across regions (top-2 mean per bin,
isotonic non-increasing, tapered at Rh). Every region is filled UP TO the round
reference: D_k = clip(P_ref - H_k, 0, 25). Result is continuous across every plate
boundary AND round by construction (no azimuthal weights -> no wedge edges).
Pixel-level texture rides on top untouched (adds are radial functions per region).
Saves halo_plan.npy (pickled dict).
"""
import os, sys, numpy as np, healpy as hp
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from seamnet_common import load_state
NS = 512

STARS = [
 ("Sirius",101.2875,-16.7161),("Canopus",95.9880,-52.6957),("RigilKent",219.9021,-60.8340),
 ("Arcturus",213.9153,19.1824),("Vega",279.2347,38.7837),("Capella",79.1723,45.9980),
 ("Rigel",78.6345,-8.2016),("Procyon",114.8255,5.2250),("Achernar",24.4285,-57.2368),
 ("Betelgeuse",88.7929,7.4071),("Hadar",210.9559,-60.3730),("Altair",297.6958,8.8683),
 ("Acrux",186.6496,-63.0991),("Aldebaran",68.9802,16.5093),("Antares",247.3519,-26.4320),
 ("Spica",201.2983,-11.1613),("Pollux",116.3289,28.0262),("Fomalhaut",344.4127,-29.6222),
 ("Deneb",310.3580,45.2803),("Mimosa",191.9303,-59.6888),("Regulus",152.0929,11.9672),
 ("Adhara",104.6564,-28.9721),("Shaula",263.4022,-37.1038),("Castor",113.6494,31.8883),
 ("Gacrux",187.7915,-57.1133),("Bellatrix",81.2828,6.3497),("Elnath",81.5730,28.6075),
 ("Miaplacidus",138.3000,-69.7172),("Alnilam",84.0534,-1.2019),("Alnair",332.0582,-46.9610),
 ("Alnitak",85.1897,-1.9426),("Mirfak",51.0807,49.8612),("Wezen",107.0979,-26.3932),
 ("Sargas",264.3297,-42.9978),("KausAustralis",276.0430,-34.3846),("Avior",125.6285,-59.5095),
 ("Menkalinan",89.8822,44.9474),("Atria",252.1662,-69.0277),("Alhena",99.4276,16.3993),
 ("Peacock",306.4119,-56.7351),("DeltaVel",131.1760,-54.7088),("Mirzam",95.6749,-17.9559),
 ("Alphard",141.8968,-8.6586),("Polaris",37.9546,89.2641),("Diphda",10.8974,-17.9866),
 ("Regor",122.3832,-47.3366)]

RBINS = np.geomspace(0.03, 2.2, 36)
RMID = np.sqrt(RBINS[:-1] * RBINS[1:])
NB = len(RMID)
DCAP = 25.0

R, G, B, gb = load_state()
drest = np.load(SC + "/delta_restore.npz")
resid4 = np.load(SC + "/dDark4_resid.npy")
sh = np.load(SC + "/dc4_sharp.npz")
U0 = sh['region_ids']; CREG = sh['c_reg']; BMAX = int(sh['bmax'])
wrz = np.load(SC + "/winner_red.npz", allow_pickle=True)
wbz = np.load(SC + "/winner_blue.npz", allow_pickle=True)
comb_coarse = wrz['winner'].astype(np.int64) * BMAX + (wbz['winner'].astype(np.int64) + 1)
cshr = np.zeros(len(comb_coarse), np.float32)
ii = np.searchsorted(U0, comb_coarse)
ok = (ii < len(U0)) & (U0[np.clip(ii, 0, len(U0) - 1)] == comb_coarse)
cshr[ok] = CREG[ii[ok]]
# include the v5/v6/v7 chroma+level terms so halo profiles see the final base state
def lut(u, c, keys):
    j = np.searchsorted(u, keys)
    v = np.zeros(len(keys), np.float32)
    okj = (j < len(u)) & (u[np.clip(j, 0, len(u) - 1)] == keys)
    v[okj] = c[j[okj]]
    return v

c5 = np.load(SC + "/dc5_chroma.npz")
c6 = np.load(SC + "/dc6_chroma.npz")
c7 = np.load(SC + "/dc7_chroma.npz")
sh6 = np.load(SC + "/dc6_sharp.npz")
sh7 = np.load(SC + "/dc7_sharp.npz")
resid6 = np.load(SC + "/dDark6_resid.npy")
labr_ = wrz['winner'].astype(np.int64); labr_[labr_ < 0] = 19000
labbe_ = np.where(wbz['winner'] < 0, labr_ + 20000, wbz['winner'].astype(np.int64))
pR5 = (lut(c5['uR'], c5['cR'], labr_) + lut(c6['uR'], c6['cR'], labr_)
       + lut(c7['uR'], c7['cR'], labr_))
pB5 = (lut(c5['uB'], c5['cB'], labbe_) + lut(c6['uB'], c6['cB'], labbe_)
       + lut(c7['uB'], c7['cB'], labbe_))
cshr = cshr + lut(sh6['region_ids'], sh6['c_reg'], comb_coarse) \
            + lut(sh7['region_ids'], sh7['c_reg'], comb_coarse)
dbR = np.load(SC + "/dband7_R.npy"); dbG = np.load(SC + "/dband7_G.npy")
dbB = np.load(SC + "/dband7_B.npy")
lum = drest['dR'] + resid4 + cshr + resid6
CUR = {'R': R + lum + pR5 + dbR, 'G': G + lum + 0.5 * (pR5 + pB5) + dbG,
       'B': B + lum + pB5 + dbB}

def pava_dec(y):
    """isotonic non-increasing fit"""
    y = y[::-1].astype(np.float64)          # -> non-decreasing problem
    n = len(y)
    lvl = y.copy(); wt = np.ones(n)
    i = 0
    vals = []; ws = []
    for k in range(n):
        vals.append(y[k]); ws.append(1.0)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * ws[-2] + vals[-1] * ws[-1]) / (ws[-2] + ws[-1])
            w = ws[-2] + ws[-1]
            vals = vals[:-2] + [v]; ws = ws[:-2] + [w]
    out = np.concatenate([np.full(int(w), v) for v, w in zip(vals, ws)])
    return out[::-1]

# nebular-field stars: round fills would overwrite real nebulosity (verified bad)
EXCLUDE = {"Alnilam", "Alnitak"}

plans = {}
for name, ra0, dec0 in STARS:
    if name in EXCLUDE: continue
    v0 = np.array(hp.ang2vec(ra0, dec0, lonlat=True))
    pix = hp.query_disc(NS, v0, np.radians(2.2), nest=True)
    vv = np.array(hp.pix2vec(NS, pix, nest=True)).T
    r = np.degrees(np.arccos(np.clip(vv @ v0, -1, 1)))
    reg = comb_coarse[pix]
    binid = np.digitize(r, RBINS) - 1
    inb = (binid >= 0) & (binid < NB)
    prof = {}
    for rg in np.unique(reg):
        m = (reg == rg) & inb
        if m.sum() < 20: continue
        P = np.full((3, NB), np.nan)
        for kb in np.unique(binid[m]):
            mb = m & (binid == kb)
            if mb.sum() < 6: continue
            for ci, ch in enumerate('RGB'):
                P[ci, kb] = np.median(CUR[ch][pix[mb]])
        Bo = np.nanmedian(P[:, RMID > 1.6], axis=1)
        if np.any(np.isnan(Bo)):
            Bo = np.nanmedian(P[:, RMID > 1.2], axis=1)
        if np.any(np.isnan(Bo)): continue
        prof[int(rg)] = P - Bo[:, None]
    if len(prof) < 2: continue
    allH = np.stack([H for H in prof.values()])          # (nreg,3,NB) with nans
    # round reference: per bin top-2 mean across regions (robust vs single-region bumps)
    Pref = np.zeros((3, NB))
    for ci in range(3):
        for kb in range(NB):
            v = allH[:, ci, kb]
            v = v[~np.isnan(v)]
            if len(v) == 0: continue
            v = np.sort(v)[::-1]
            Pref[ci, kb] = v[:2].mean() if len(v) >= 3 else v[0]
    PrefL = 0.299 * Pref[0] + 0.587 * Pref[1] + 0.114 * Pref[2]
    sig = np.where(PrefL > 0.75)[0]
    if len(sig) < 3: continue
    Rh = min(float(RBINS[min(sig.max() + 2, NB)]), 2.0)
    taper = np.clip((Rh - RMID) / 0.15, 0, 1)
    for ci in range(3):
        Pref[ci] = pava_dec(np.nan_to_num(Pref[ci], nan=0.0))
        Pref[ci] = np.convolve(Pref[ci], np.ones(3) / 3, mode='same') * taper
        Pref[ci] = np.clip(Pref[ci], 0, None)
    ids = []; Ds = []
    for rg, H in prof.items():
        Hf = np.where(np.isnan(H), Pref, H)
        D = np.clip(Pref - Hf, 0, DCAP) * taper[None, :]
        for ci in range(3):
            D[ci] = np.convolve(D[ci], np.ones(3) / 3, mode='same')
        if (0.299 * D[0] + 0.587 * D[1] + 0.114 * D[2] > 0.8).sum() >= 2:
            ids.append(rg); Ds.append(D.astype(np.float32))
    if not ids: continue
    mx = max(float((0.299*D[0]+0.587*D[1]+0.114*D[2]).max()) for D in Ds)
    print("  %-14s Rh %.2f regions-to-fill %d max-add %.1f DN" % (name, Rh, len(ids), mx), flush=True)
    plans[name] = dict(ra=ra0, dec=dec0, Rh=Rh, ids=np.array(ids, np.int64),
                       D=np.stack(Ds), rmid=RMID.astype(np.float32))
np.save(SC + "/halo_plan.npy", plans, allow_pickle=True)
print("planned stars:", len(plans))
