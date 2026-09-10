"""SeamNet shared helpers v2 (post design-review).

Self-trained plate-artifact removal: we know the artifact generative model exactly
(GSSS winner tessellations for red/blue mosaics + measured step statistics), so we
inject synthetic artifacts into crops of our OWN sky and train a U-Net to regress
the injected field. Review-driven v2 changes:
  - crops are generated ON THE FLY (random center+rotation) — no fixed pool to memorize
  - random low-order base perturbation (not in target) kills absolute-sky recall
  - injection amplitude driven by local background level (not |b| shortcut); no b input
  - per-region curvature term (vignetting bowls the classical solvers can't express)
  - G mix coefficient randomized u~U(0.35,0.65) + independent per-region G epsilon
  - blue winner label -1 (real DSS2-blue coverage gaps, the "dead blue channel" orange
    zones) falls back to the red tessellation (+20000 ids), matching the real mosaic
  - corrupted input clipped at 0 (uint8 domain)
"""
import os
import numpy as np
import healpy as hp

SC = os.path.dirname(os.path.abspath(__file__))
NS = 512
NPIX = hp.nside2npix(NS)
SZ = 160            # crop size, px
SCALE = 0.115       # deg/px (~nside-512 pixel; 160 px = 18.4 deg field)
HALF = SZ * SCALE / 2
AX_DEG = (np.arange(SZ) - (SZ - 1) / 2) * SCALE
XG, YG = np.meshgrid(AX_DEG, AX_DEG)
BLUE_OFF = 20000    # id offset for blue -1 zones remapped onto the red tessellation


def load_state():
    """Current INTENDED tile state at nside-512 (full float chain incl. dDarkDC2; not v3)."""
    z = np.load(SC + "/mapbase.npz")
    d = np.load(SC + "/delta512.npz")
    dL0 = np.load(SC + "/dLum512.npy")
    dreg = np.load(SC + "/delta_regions_final.npz")
    dm = np.load(SC + "/delta_membrane.npz")
    base = np.load(SC + "/dDarkDC.npy") + np.load(SC + "/dDarkDC2.npy")
    R = (z['mapR'].astype(np.float64) + d['dR'] + dL0 + dreg['dR'] + dm['dR'] + base).astype(np.float32)
    G = (z['mapG'].astype(np.float64) + d['dG'] + dL0 + dreg['dG'] + dm['dG'] + base).astype(np.float32)
    B = (z['mapB'].astype(np.float64) + d['dB'] + dL0 + dreg['dB'] + dm['dB'] + base).astype(np.float32)
    gb = z['gb'].astype(np.float32)
    return R, G, B, gb


def load_labels():
    """Red winner labels + effective blue labels (-1 gaps -> red tessellation + BLUE_OFF)."""
    wr = np.load(SC + "/winner_red.npz", allow_pickle=True)
    wb = np.load(SC + "/winner_blue.npz", allow_pickle=True)
    labr = wr['winner'].astype(np.int32)
    labb = wb['winner'].astype(np.int32)
    labr[labr < 0] = 19000 + 0 * labr[labr < 0]      # tiny red gap: single pseudo-region
    labb_eff = np.where(labb < 0, labr + BLUE_OFF, labb).astype(np.int32)
    return labr, labb_eff


def tangent_frame(c, psi):
    zax = np.array([0., 0., 1.])
    e1 = np.cross(zax, c)
    n = np.linalg.norm(e1)
    if n < 1e-8:
        e1 = np.array([1., 0., 0.])
    else:
        e1 = e1 / n
    e2 = np.cross(c, e1)
    ce, se = np.cos(psi), np.sin(psi)
    return ce * e1 + se * e2, -se * e1 + ce * e2


def crop_dirs(c, psi):
    e1, e2 = tangent_frame(c, psi)
    V = (c[None, None, :]
         + np.tan(np.radians(XG))[..., None] * e1
         + np.tan(np.radians(YG))[..., None] * e2)
    V /= np.linalg.norm(V, axis=-1, keepdims=True)
    return V.reshape(-1, 3)


def sample_crop(V, maps_lin, maps_near):
    th, ph = hp.vec2ang(V)
    out_lin = [hp.get_interp_val(m, th, ph, nest=True).astype(np.float32).reshape(SZ, SZ)
               for m in maps_lin]
    pix = hp.ang2pix(NS, th, ph, nest=True)
    out_near = [m[pix].reshape(SZ, SZ) for m in maps_near]
    return out_lin, out_near


def draw_crop(rng, R, G, B, gb, labr, labb):
    """Random Milky-Way-weighted crop: img(3,SZ,SZ) [R,G,B], labr, labb, gb crop."""
    while True:
        p = int(rng.integers(0, NPIX))
        if rng.random() < 0.3 + 0.7 * np.exp(-(gb[p] / 22.0) ** 2):
            break
    c = np.array(hp.pix2vec(NS, p, nest=True))
    V = crop_dirs(c, rng.random() * 2 * np.pi)
    (r, g, b, gc), (a, bb) = sample_crop(V, [R, G, B, gb], [labr, labb])
    return np.stack([r, g, b]), a, bb, gc


# ---------------- synthetic artifact model (measured statistics) ----------------

def _region_field(lab, gbc, Lc, rng, dc_only=False, scale_mult=1.0):
    """Piecewise field over one tessellation: per-region DC (Laplace, background-level
    scaled) + b-gradient residual (skyVal mechanism) + planar + curvature terms."""
    ids, inv = np.unique(lab, return_inverse=True)
    inv = inv.reshape(-1)
    n = len(ids)
    cnt = np.bincount(inv).astype(np.float64)
    bg = np.bincount(inv, weights=Lc.ravel().astype(np.float64)) / cnt
    scale0 = np.clip(0.35 + 0.045 * (bg - 6.0), 0.35, 2.0)
    scale = scale0 * scale_mult
    dc = rng.laplace(0.0, scale)
    dc = dc * (rng.random(n) > 0.07)          # small clean-plate spike only: a large
    # spike teaches the L1 net to soft-threshold small steps to zero — exactly the
    # amplitude range of the real residuals we need it to remove
    if dc_only:
        return dc[inv].reshape(SZ, SZ).astype(np.float32)
    gbr = gbc.ravel().astype(np.float64)
    gmean = np.bincount(inv, weights=gbr) / cnt
    kk = rng.normal(0.0, 0.06 + 0.08 * (scale0 - 0.35), n)     # DN/deg along b
    xm = np.bincount(inv, weights=XG.ravel()) / cnt
    ym = np.bincount(inv, weights=YG.ravel()) / cnt
    dx = XG.ravel() - xm[inv]
    dy = YG.ravel() - ym[inv]
    gx = rng.normal(0.0, 0.05, n)
    gy = rng.normal(0.0, 0.05, n)
    q2x = rng.normal(0.0, 0.02, n)
    q2y = rng.normal(0.0, 0.02, n)
    qxy = rng.normal(0.0, 0.02, n)
    m2x = np.bincount(inv, weights=dx * dx) / cnt
    m2y = np.bincount(inv, weights=dy * dy) / cnt
    mxy = np.bincount(inv, weights=dx * dy) / cnt
    f = (dc[inv] + kk[inv] * (gbr - gmean[inv]) + gx[inv] * dx + gy[inv] * dy
         + q2x[inv] * (dx * dx - m2x[inv]) + q2y[inv] * (dy * dy - m2y[inv])
         + qxy[inv] * (dx * dy - mxy[inv]))
    return f.reshape(SZ, SZ).astype(np.float32)


def _blur(a, sigma):
    import cv2
    return cv2.GaussianBlur(a, (0, 0), sigma)


def inject(img_rgb, labr, labb, gbc, rng):
    """Returns corrupted x (3,SZ,SZ) and target artifact A (3,SZ,SZ), both float32."""
    L = 0.299 * img_rgb[0] + 0.587 * img_rgb[1] + 0.114 * img_rgb[2]
    aR = _region_field(labr, gbc, L, rng)
    aB = _region_field(labb, gbc, L, rng)
    if rng.random() < 0.5:                     # correlated pure-luminance component
        alum = _region_field(labr, gbc, L, rng, scale_mult=0.5)
        aR = aR + alum
        aB = aB + alum
    u = rng.uniform(0.35, 0.65)
    aG = u * aR + (1 - u) * aB + _region_field(labr, gbc, L, rng, dc_only=True, scale_mult=0.2)
    A = np.clip(np.stack([aR, aG, aB]), -8, 8)
    sig = rng.uniform(0.5, 1.6)                # HiPS + bilinear sampling softness range
    A = np.stack([_blur(A[k], sig) for k in range(3)])
    if rng.random() < 0.55:
        # partial-correction residual: earlier classical passes subtracted SMOOTH
        # (0.3-0.8 deg feathered) versions of piecewise fields, so real leftovers are
        # "sharp step minus smooth ramp" dipoles + reduced steps. Train on exactly that.
        gam = rng.uniform(0.3, 1.0)
        ss = rng.uniform(2.5, 7.0)             # px (0.3-0.8 deg)
        A = A - gam * np.stack([_blur(A[k], ss) for k in range(3)])
    # low-order base perturbation, NOT in target: absolute sky level is not evidence
    Xn = XG / HALF
    Yn = YG / HALF
    a = rng.normal(0.0, 1.0, 6) * np.array([0.8, 0.6, 0.6, 0.3, 0.3, 0.3])
    P = (a[0] + a[1] * Xn + a[2] * Yn + a[3] * Xn * Xn + a[4] * Yn * Yn + a[5] * Xn * Yn)
    Pc = P[None] + rng.normal(0.0, 0.4, (3, 1, 1))
    x = np.maximum(img_rgb + Pc.astype(np.float32) + A, 0.0)
    return x.astype(np.float32), A


def edge_maps(labr, labb):
    er = np.zeros((SZ, SZ), np.float32)
    eb = np.zeros((SZ, SZ), np.float32)
    for lab, e in ((labr, er), (labb, eb)):
        e[:, 1:] = np.maximum(e[:, 1:], (lab[:, 1:] != lab[:, :-1]).astype(np.float32))
        e[1:, :] = np.maximum(e[1:, :], (lab[1:, :] != lab[:-1, :]).astype(np.float32))
    return _blur(er, 1.0), _blur(eb, 1.0)


def net_input(x_rgb, er, eb):
    """8 channels: asinh-stretched RGB + linear RGB + red/blue seam-edge maps."""
    a = np.arcsinh(x_rgb / 12.0)
    l = np.clip(x_rgb, 0, 240) / 40.0
    return np.concatenate([a, l, er[None], eb[None]], 0).astype(np.float32)
