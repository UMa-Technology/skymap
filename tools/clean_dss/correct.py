"""Remove a seam step from the low-frequency field via gradient-domain (Poisson)
reconstruction: take the coarse-bg gradients, zero the gradients that cross the
detected region boundary, reintegrate. Real structure (all other gradients) is
preserved; per-tile DC is re-anchored so neighbouring tiles stay continuous."""
import numpy as np
from scipy.fft import dctn, idctn

def poisson_reconstruct(gx, gy):
    """Solve grad(u) ~= (gx,gy) with homogeneous Neumann BC via DCT. gx,gy are
    forward differences (gx[:, :-1] valid). Returns u with mean 0."""
    h, w = gx.shape
    fx = np.zeros((h, w), np.float64); fy = np.zeros((h, w), np.float64)
    fx[:, 1:] = np.diff(gx, axis=1)         # d/dx of gx
    fx[:, 0] = gx[:, 0]                     # left Neumann boundary flux (incoming flux = 0)
    fy[1:, :] = np.diff(gy, axis=0)         # d/dy of gy
    fy[0, :] = gy[0, :]                     # top Neumann boundary flux
    f = fx + fy                             # divergence
    fhat = dctn(f, type=2, norm='ortho')
    i = np.arange(h)[:, None]; j = np.arange(w)[None, :]
    denom = (2*np.cos(np.pi*i/h) - 2) + (2*np.cos(np.pi*j/w) - 2)
    denom[0, 0] = 1.0
    uhat = fhat / denom
    uhat[0, 0] = 0.0
    u = idctn(uhat, type=2, norm='ortho')
    return u.astype(np.float32)

def _seam_corrected_channel(bgc, labels):
    gx = np.zeros_like(bgc); gy = np.zeros_like(bgc)
    gx[:, :-1] = np.diff(bgc, axis=1)
    gy[:-1, :] = np.diff(bgc, axis=0)
    # zero gradients that step across a region boundary (the seam)
    lab = labels
    cross_x = lab[:, :-1] != lab[:, 1:]
    cross_y = lab[:-1, :] != lab[1:, :]
    gx[:, :-1][cross_x] = 0.0
    gy[:-1, :][cross_y] = 0.0
    u = poisson_reconstruct(gx, gy)
    u += bgc.mean() - u.mean()              # re-anchor DC to the original tile mean
    return u

def correct_seam(bg, labels):
    """bg: (GRID,GRID,3) coarse background; labels: (GRID,GRID) region ids.
    Returns corrected coarse background (same shape)."""
    out = np.empty_like(bg)
    for c in range(bg.shape[2]):
        out[..., c] = _seam_corrected_channel(bg[..., c].astype(np.float32), labels)
    return out

from .background import upsample_smooth

def apply_correction(img_uint8, bg, bg_corr):
    """Add the low-frequency correction (bg_corr - bg), smoothly upsampled, to the
    full-res image per channel. Stars/structure ride along unchanged (correction is
    smooth & small); only the seam's DC step is removed."""
    img = img_uint8.astype(np.float32)
    size = img.shape[0]
    for c in range(3):
        delta = upsample_smooth(bg_corr[..., c] - bg[..., c], size)
        img[..., c] += delta
    return np.clip(img, 0, 255).astype(np.uint8)
