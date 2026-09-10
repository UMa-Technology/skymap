#!/usr/bin/env python3

# Stellarium Web Engine - Copyright (c) 2026 - Stellarium Labs SRL
#
# This program is licensed under the terms of the GNU AGPL v3, or
# alternatively under a commercial licence.
#
# The terms of the AGPL v3 license can be found in the main directory of this
# repository.

"""Turn a Stellarium `type = spherical` landscape panorama into the HiPS
pyramid the engine's landscape module renders (the same layout upstream's
`ocean` landscape uses, but with the deeper orders ocean lacks).

Input  : <dir>/landscape.ini + its `maptex` (equirectangular 2:1 RGBA image,
         top row = zenith, bottom row = nadir, left edge = azimuth 0 = North).
Output : <dir>/Norder{0..N}/Dir0/Npix*.webp, <dir>/Norder0/Allsky.webp,
         <dir>/Norder0/Allsky_preview.png, <dir>/properties, and the
         description.*.utf8 the module reads (only if missing).

WHY MORE THAN ONE ORDER -- this is the load-bearing part of the tool. All three
defects a Norder0-only landscape shows (soft image, a hard X radiating from each
intercardinal horizon point, a faint diamond lattice over smooth ground) are the
same thing: the survey is being magnified far past its own texel size.
hips_get_render_order() (hips.c:643) asks for order 4 at an 8-degree FOV and
order 5 at 3 degrees, and hips_get_render_order_clamped() (hips.c:662) clamps
that to `hips_order`. At hips_order=0 the survey is magnified 16-32x. Measured
consequences at order 0 (0.1145 deg/texel vs a 8000px panorama's 0.045 deg/px):
  * blur -- 65-73% of the squared error is the 2.5x resolution shortfall; webp
    q90 is 27-35% and destroys no detail (it slightly RAISES the measured local
    gradient: it adds a little ringing). Lossless costs +405% bytes for +2 dB.
  * the X -- each intercardinal horizon point is a corner shared by 4 tiles.
    GL_CLAMP_TO_EDGE (texture.c:74) freezes the outer half texel of every tile,
    because the neighbour's texel simply is not in the texture, so a ~1 texel
    plateau with a step in it runs along every tile edge. This is a border
    VISIBILITY problem, not a misalignment: laid on a common axis two adjacent
    tiles' texel centres form a perfectly uniform lattice (gap 1.0000 across the
    seam). Re-aligning the content to the tile edge was tried and measured --
    it duplicates the boundary sample, widens the plateau, makes registration
    worse, and still leaves ~76% of the line, so do NOT do it.
  * the lattice -- per-cell affine texture interpolation over the
    `1 << (split_order - render_order)` grid (the landscape passes
    split_order=3, so an order-0 tile is an 8x8 grid of ~11 degree cells),
    displacing content by up to ~0.9 texel, plus plain bilinear magnification
    of the texel grid itself.
Every extra order halves the texel size, the frozen band AND the split cell, so
depth is the only fix that touches all three. Default depth therefore goes ONE
order past the source resolution: the deepest order is pure upsampling, which
buys nothing in detail but is what shrinks the frozen band and the lattice below
a screen pixel. Use --max-order to trade disk for that last bit of polish.

Geometry (derived from the engine, not guessed -- get it wrong and the horizon
tilts or the panorama mirrors; verified by reconstructing upstream's own ocean
tiles back into a clean equirectangular panorama):

  * The landscape hips is declared FRAME_OBSERVED (landscape.c:add_from_uri),
    i.e. x=North, y=East, z=Zenith (see the cardinal.c POINTS table), but
    hips_render() is handed the `rg2h` "hack matrix" diag(1,-1,1,1). So the
    frame the TILES live in is (North, West, Zenith) -- a right-handed frame
    where healpix's phi grows westward. Hence azimuth = -phi.
  * A tile pixel maps to (a, b) = (row/N, col/N) -- note the order: the hips
    renderer multiplies the tile's uv by `uv_swap` (hips.c:render_visitor), so
    the texture's s axis takes the quad's second uv coordinate and t the first.
    healpix_get_mat3() then gives, for nside = 2^order and (ix, iy, face) =
    healpix_nest2xyf(nside, pix),
        x_hp = pi/4 * ((a - b) / nside + FACES[face][0] + (ix - iy) / nside)
        y_hp = pi/4 * ((a + b) / nside + FACES[face][1] + (ix + iy) / nside)
    which healpix_xy2_z_phi() turns into (z, phi).
  * Consequence worth remembering when eyeballing the output: at order 0 faces
    0-3 cover z>=0, so they only hold whatever rises ABOVE the true horizon
    (nothing at all for a flat sea like ocean, a sliver of dune crest for
    drakkar); faces 8-11 cover z<=0 and are the heavy, opaque ground tiles.

The Allsky mosaic layout is NOT the 4-per-line the HiPS spec suggests: the
engine computes `nbw = (int)sqrt(12) = 3` (hips.c:434), so it is 3 columns x 4
rows of (allsky_width / 3) px tiles -- 192x256 with 64px tiles, exactly what
upstream's ocean ships. A mismatch here makes tiles visibly jump as the real
ones load. Only the order-0 allsky is ever used (hips.c:432), so that is all we
write.

Usage:
  make-landscape-survey.py apps/skydata/landscapes/drakkar
  # force the depth, or shift which image column lands on North:
  make-landscape-survey.py --max-order 3 --rotate 90 <dir>
  # eyeball the geometry: re-project the written tiles back to equirectangular
  make-landscape-survey.py --check /tmp/roundtrip.jpg <dir>
"""

import argparse
import configparser
import datetime
import math
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# Position of the healpix faces (mirrors FACES in src/algos/healpix.c).
FACES = [(1, 0), (3, 0), (5, 0), (7, 0),
         (0, -1), (2, -1), (4, -1), (6, -1),
         (1, -2), (3, -2), (5, -2), (7, -2)]

ALLSKY_TILE = 64    # px per tile in the Allsky mosaic (=> 192x256 mosaic)


# --- healpix ---------------------------------------------------------------

def nest2xyf(nside, pix):
    """Port of healpix_nest2xyf(): nested pixel -> (ix, iy, face).

    ix is the even bit-plane of the in-face index, iy the odd one.
    """
    npface = nside * nside
    face, p = divmod(pix, npface)
    ix = iy = bit = 0
    while p:
        ix |= (p & 1) << bit
        iy |= ((p >> 1) & 1) << bit
        p >>= 2
        bit += 1
    return ix, iy, face


def xyf2nest(nside, ix, iy, face):
    """Inverse of nest2xyf(). Works on scalars or numpy arrays."""
    p = ix * 0
    for bit in range(16):
        p |= ((ix >> bit) & 1) << (2 * bit)
        p |= ((iy >> bit) & 1) << (2 * bit + 1)
    return face * nside * nside + p


def healpix_xy2_z_phi(x, y):
    """Vectorised port of healpix_xy2_z_phi() from src/algos/healpix.c."""
    polar = np.abs(y) > math.pi / 4
    z = np.where(polar, 0.0, y * 8 / (math.pi * 3))
    phi = np.array(x, dtype=np.float64, copy=True)

    if polar.any():
        yp, xp = y[polar], x[polar]
        sigma = 2 - np.abs(yp * 4) / math.pi
        z[polar] = np.sign(yp) * (1 - sigma * sigma / 3)
        xc = -math.pi + (2 * np.floor((xp + math.pi) * 4 / (2 * math.pi)) + 1) \
            * math.pi / 4
        phi[polar] = np.where(sigma != 0, xc + (xp - xc) / np.where(
            sigma != 0, sigma, 1), xp)
    return z, phi


def order_resolution(order, tile_width):
    """Mean pixel size of the survey at `order`, in degrees."""
    npix = 12 * (4 ** order) * tile_width * tile_width
    return math.degrees(math.sqrt(4 * math.pi / npix))


def tile_altaz(order, pix, size, supersample):
    """(alt, az) in radians for every (super)sample of one tile.

    Returned arrays are (size*ss, size*ss); the first axis is the tile's image
    rows, the second its columns.

    Texel (i, j) is filled from a=(i+0.5)/size, b=(j+0.5)/size -- texel CENTRES.
    That is what GL does: render_gl.c maps quad coordinate a straight to texture
    coordinate t (and b to s), tex->w == tex->tex_w == 512 so the scale factor
    is exactly 1, and GL_LINEAR samples texel i at (i+0.5)/size. Do not be
    tempted to "edge align" this to i/(size-1) to make neighbouring tiles meet:
    see the module docstring -- the tiles already meet, and it measurably makes
    things worse.
    """
    nside = 1 << order
    ix, iy, face = nest2xyf(nside, pix)
    f0, f1 = FACES[face]
    n = size * supersample
    t = (np.arange(n) + 0.5) / n
    a, b = t[:, None], t[None, :]
    x_hp = math.pi / 4 * ((a - b) / nside + f0 + (ix - iy) / nside)
    y_hp = math.pi / 4 * ((a + b) / nside + f1 + (ix + iy) / nside)
    x_hp, y_hp = np.broadcast_arrays(x_hp, y_hp)
    z, phi = healpix_xy2_z_phi(np.ascontiguousarray(x_hp),
                               np.ascontiguousarray(y_hp))
    alt = np.arcsin(np.clip(z, -1, 1))
    az = -phi   # the tile frame is (North, West, Up): phi grows westward.
    return alt, az


# --- sampling --------------------------------------------------------------

def dilate_colours(pano):
    """Bleed the nearest opaque RGB into the fully transparent region.

    The engine composites with straight, non-premultiplied alpha (webp decodes
    to straight RGBA in swe_utils.c, blit.glsl does no un-premultiply, and
    render_gl.c:1595 sets glBlendFuncSeparate(GL_SRC_ALPHA,
    GL_ONE_MINUS_SRC_ALPHA, ...)), so bilinear filtering blends the transparent
    texels' RGB in too, and drakkar.png stores pure black under its alpha=0 sky.

    Measured, this is worth ~nothing on the RENDER side: the supersampled tiles
    contain no hard 255<->0 alpha step at all, so the wrong colour is always
    co-located with near-zero alpha and cancels (worst case ~5/255, a handful of
    pixels out of 60M). It is kept on by default because the deep orders sample
    the panorama with plain bilinear and no supersampling, where the same
    cancellation is not guaranteed. Only RGB changes; alpha is untouched.
    """
    from scipy.ndimage import distance_transform_edt
    opaque = pano[..., 3] > 0
    if opaque.all() or not opaque.any():
        return pano
    # distance_transform_edt on the *transparent* mask gives, for each
    # transparent pixel, the index of the nearest opaque one.
    _, (ri, ci) = distance_transform_edt(~opaque, return_indices=True)
    out = pano.copy()
    out[..., :3] = pano[ri, ci, :3]
    out[..., 3] = pano[..., 3]
    return out


def sample_nearest(pano, alt, az, rotate_deg):
    h, w = pano.shape[:2]
    col = np.floor((np.degrees(az) + rotate_deg) % 360.0 / 360.0 * w)
    col = col.astype(np.int32) % w
    row = np.floor((90.0 - np.degrees(alt)) / 180.0 * h).astype(np.int32)
    np.clip(row, 0, h - 1, out=row)
    return pano[row, col]


def sample_bilinear(pano, alt, az, rotate_deg):
    """Used when the target tile is FINER than the source, where nearest just
    replicates source pixels into visible blocks."""
    h, w = pano.shape[:2]
    x = (np.degrees(az) + rotate_deg) % 360.0 / 360.0 * w - 0.5
    y = (90.0 - np.degrees(alt)) / 180.0 * h - 0.5
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    fx = (x - x0).astype(np.float32)[..., None]
    fy = (y - y0).astype(np.float32)[..., None]
    x1, y1 = (x0 + 1) % w, np.clip(y0 + 1, 0, h - 1)
    x0, y0 = x0 % w, np.clip(y0, 0, h - 1)
    p00 = pano[y0, x0].astype(np.float32)
    p01 = pano[y0, x1].astype(np.float32)
    p10 = pano[y1, x0].astype(np.float32)
    p11 = pano[y1, x1].astype(np.float32)
    top = p00 + (p01 - p00) * fx
    bot = p10 + (p11 - p10) * fx
    return np.clip(top + (bot - top) * fy + 0.5, 0, 255).astype(np.uint8)


def downsample(samples, size, supersample):
    """(size*ss, size*ss, 4) uint8 -> (size, size, 4) uint8, alpha-weighted."""
    if supersample == 1:
        return samples
    s = samples.reshape(size, supersample, size, supersample, 4)
    a = s[..., 3].astype(np.float32) / 255.0
    rgb = s[..., :3].astype(np.float32) * a[..., None]   # premultiply
    a_sum = a.mean(axis=(1, 3))[..., None]
    rgb_sum = rgb.mean(axis=(1, 3))
    with np.errstate(divide='ignore', invalid='ignore'):
        rgb_out = np.where(a_sum > 0, rgb_sum / np.where(a_sum > 0, a_sum, 1),
                           0.0)
    out = np.empty((size, size, 4), dtype=np.uint8)
    out[..., :3] = np.clip(rgb_out + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(a_sum[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


# --- output ----------------------------------------------------------------

def save_tile(img, path, quality):
    """Lossy webp, except for the fully transparent tiles (most of the upper
    hemisphere once the pyramid gets deep), where lossless is exact and
    smaller."""
    im = Image.fromarray(img)
    if img[..., 3].max() == 0:
        im.save(path, 'WEBP', lossless=True, method=6)
    else:
        im.save(path, 'WEBP', quality=quality, method=6, alpha_quality=100)


def shrink_premultiplied(img, size):
    """Resize an RGBA array in premultiplied space (PIL resizes the raw RGB,
    which drags the sky's undefined colour into the horizon band)."""
    a = img[..., 3:4].astype(np.float32) / 255.0
    pre = np.concatenate([img[..., :3].astype(np.float32) * a,
                          img[..., 3:4].astype(np.float32)], axis=2)
    small = np.asarray(Image.fromarray(
        np.clip(pre + 0.5, 0, 255).astype(np.uint8)).resize(
            (size, size), Image.LANCZOS)).astype(np.float32)
    sa = small[..., 3:4] / 255.0
    out = np.empty((size, size, 4), dtype=np.uint8)
    with np.errstate(divide='ignore', invalid='ignore'):
        rgb = np.where(sa > 0, small[..., :3] / np.where(sa > 0, sa, 1), 0.0)
    out[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(small[..., 3] + 0.5, 0, 255).astype(np.uint8)
    return out


def write_allsky(tiles, out_dir, quality):
    """3 columns x 4 rows mosaic -- see the docstring on the engine's nbw."""
    nbw = int(math.sqrt(12))    # == 3, matching hips.c
    nbh = (12 + nbw - 1) // nbw
    mosaic = np.zeros((nbh * ALLSKY_TILE, nbw * ALLSKY_TILE, 4), np.uint8)
    for pix, tile in enumerate(tiles):
        x, y = (pix % nbw) * ALLSKY_TILE, (pix // nbw) * ALLSKY_TILE
        mosaic[y:y + ALLSKY_TILE, x:x + ALLSKY_TILE] = shrink_premultiplied(
            tile, ALLSKY_TILE)
    im = Image.fromarray(mosaic)
    im.save(os.path.join(out_dir, 'Allsky.webp'), 'WEBP', quality=quality,
            method=6, alpha_quality=100)
    im.save(os.path.join(out_dir, 'Allsky_preview.png'), 'PNG')


def write_properties(path, title, max_order, tile_width, date):
    with open(path, 'w') as f:
        for k, v in [('hips_order', max_order), ('hips_order_min', 0),
                     ('hips_tile_width', tile_width),
                     ('hips_tile_format', 'webp'),
                     ('dataproduct_type', 'image'), ('obs_title', title),
                     ('hips_release_date', date), ('type', 'landscape')]:
            f.write('%-21s = %s\n' % (k, v))


def write_descriptions(dirname, title, ini):
    """The module fetches description.en.utf8 (landscape.c:landscape_update);
    the other locales follow upstream ocean's naming. Never overwrite a hand-written
    one."""
    author = ini.get('author', '')
    made = ini.get('description', '')
    texts = {
        'en': '<h2>%s</h2>\n<p>%s%s\n' % (
            title, made, ' by %s.' % author if author else ''),
        'zh_CN': '<h2>%s</h2>\n<p>%s%s\n' % (
            title, made, '，作者 %s。' % author if author else ''),
    }
    for lang, text in texts.items():
        path = os.path.join(dirname, 'description.%s.utf8' % lang)
        if os.path.exists(path):
            continue
        with open(path, 'w') as f:
            f.write(text)
        print('  wrote %s' % os.path.basename(path))


# --- verification ----------------------------------------------------------

def check_roundtrip(order, tiles, out_path, rotate_deg, width=1600):
    """Re-project a whole order back to an equirectangular image.

    A correct build gives back the source panorama: dead level horizon, no
    mirroring, no missing tile. Cheap way to catch a geometry mistake without
    loading the app. `tiles` is a dict {pix: array}.
    """
    nside = 1 << order
    height = width // 2
    size = next(iter(tiles.values())).shape[0]
    alt, az = np.meshgrid(
        np.radians(90.0 - (np.arange(height) + 0.5) / height * 180.0),
        np.radians((np.arange(width) + 0.5) / width * 360.0 - rotate_deg),
        indexing='ij')

    # (alt, az) -> healpix (x, y): the inverse of healpix_xy2_z_phi(). phi is
    # kept in [0, 2pi) because that is the range the polar faces' x lives in
    # (FACES x offsets run 1..7), and there |phi - xc| <= pi/4 always holds, so
    # the quadrant of phi does identify the face.
    z = np.sin(alt)
    phi = np.mod(-az, 2 * math.pi)
    za = np.abs(z)
    x, y = phi.copy(), z * math.pi * 3 / 8
    polar = za > 2 / 3
    if polar.any():
        sigma = np.sqrt(3 * (1 - za[polar]))
        y[polar] = np.sign(z[polar]) * (2 - sigma) * math.pi / 4
        xc = (2 * np.floor(phi[polar] * 2 / math.pi) + 1) * math.pi / 4
        x[polar] = xc + (phi[polar] - xc) * sigma

    out = np.zeros((height, width, 4), np.uint8)
    done = np.zeros((height, width), bool)
    for face, (f0, f1) in enumerate(FACES):
        # invert the forward map: with P = (X-f0)*nside, Q = (Y-f1)*nside,
        # a + ix = (P+Q)/2 and b + iy = (Q-P)/2. The +-2pi shifts cover the
        # faces whose x range straddles the phi wrap.
        for shift in (0.0, -2 * math.pi, 2 * math.pi):
            p = ((x + shift) * 4 / math.pi - f0) * nside
            q = (y * 4 / math.pi - f1) * nside
            ai, bi = (p + q) / 2, (q - p) / 2
            ix, iy = np.floor(ai).astype(np.int64), np.floor(bi).astype(np.int64)
            m = ((ix >= 0) & (ix < nside) & (iy >= 0) & (iy < nside) & ~done)
            if not m.any():
                continue
            a, b = ai[m] - ix[m], bi[m] - iy[m]
            rows = np.clip((a * size).astype(np.int32), 0, size - 1)
            cols = np.clip((b * size).astype(np.int32), 0, size - 1)
            pixels = xyf2nest(nside, ix[m], iy[m], face)
            vals = np.zeros((pixels.size, 4), np.uint8)
            for pv in np.unique(pixels):
                sel = pixels == pv
                if pv in tiles:
                    vals[sel] = tiles[pv][rows[sel], cols[sel]]
            out[m] = vals
            done |= m
    if not done.all():
        print('  WARNING: %d/%d output pixels hit no tile'
              % ((~done).sum(), done.size), file=sys.stderr)

    rgba = Image.fromarray(out)
    bg = Image.new('RGB', (width, height), (20, 20, 60))
    bg.paste(rgba, (0, 0), rgba)
    bg.save(out_path, quality=92)
    print('  wrote %s' % out_path)


# --- driver ----------------------------------------------------------------

def build_order(pano, order, size, quality, rotate, out_root,
                src_res, verbose):
    """Render and write every tile of one order. Returns {pix: array}."""
    res = order_resolution(order, size)
    ratio = res / src_res
    if ratio >= 1.0:
        # tile coarser than the source: average the source down.
        ss = min(4, 1 << max(1, math.ceil(math.log2(ratio))))
        sampler = sample_nearest
        how = 'nearest x%d' % ss
    else:
        # tile finer than the source: nothing to average, interpolate instead.
        ss = 1
        sampler = sample_bilinear
        how = 'bilinear'

    out_dir = os.path.join(out_root, 'Norder%d' % order, 'Dir0')
    os.makedirs(out_dir, exist_ok=True)
    npix = 12 * (4 ** order)
    print('  Norder%d: %3d tiles, %.4f deg/px (%s)' % (order, npix, res, how))

    tiles, total, empty = {}, 0, 0
    for pix in range(npix):
        alt, az = tile_altaz(order, pix, size, ss)
        tile = downsample(sampler(pano, alt, az, rotate), size, ss)
        path = os.path.join(out_dir, 'Npix%d.webp' % pix)
        save_tile(tile, path, quality)
        tiles[pix] = tile
        total += os.path.getsize(path)
        if tile[..., 3].max() == 0:
            empty += 1
        if verbose:
            print('    Npix%-4d alpha %3d..%3d  %8d bytes' % (
                pix, tile[..., 3].min(), tile[..., 3].max(),
                os.path.getsize(path)))
    print('    %d fully transparent, %.1f MB total'
          % (empty, total / 1024 / 1024))
    return tiles


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('dir', help='landscape dir holding landscape.ini')
    parser.add_argument('--maptex', default=None,
                        help='path to the source panorama, overriding '
                             'landscape.ini\'s `maptex`. Use this when the '
                             'panorama is kept outside apps/skydata so the app '
                             'bundle does not ship it (the app never fetches '
                             'it -- only these tiles are served)')
    parser.add_argument('--tile-width', type=int, default=512,
                        help='tile size in px (upstream ocean uses 512)')
    parser.add_argument('--max-order', type=int, default=None,
                        help='deepest order to build (default: one order past '
                             'the source resolution -- see the module '
                             'docstring on why that last order is worth it)')
    parser.add_argument('--quality', type=int, default=92,
                        help='webp quality for the non-empty tiles')
    parser.add_argument('--rotate', type=float, default=0.0,
                        help='degrees to add to the panorama azimuth, i.e. '
                             'move the image column that lands on North')
    parser.add_argument('--title', default=None,
                        help='obs_title (default: landscape.ini name)')
    parser.add_argument('--no-dilate', action='store_true',
                        help='keep the source RGB under alpha=0 as-is instead '
                             'of bleeding the ground colour into it')
    parser.add_argument('--check', metavar='JPG', default=None,
                        help='also re-project the deepest order back to an '
                             'equirectangular image for inspection')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='print every tile')
    args = parser.parse_args()

    ini_path = os.path.join(args.dir, 'landscape.ini')
    cfg = configparser.ConfigParser()
    cfg.read(ini_path)
    if not cfg.has_section('landscape'):
        sys.exit('%s: no [landscape] section' % ini_path)
    ini = cfg['landscape']
    if ini.get('type') != 'spherical':
        sys.exit('%s: only type = spherical is supported (got %r)'
                 % (ini_path, ini.get('type')))
    title = args.title or ini.get('name') or os.path.basename(
        args.dir.rstrip('/'))

    src = args.maptex or os.path.join(args.dir, ini['maptex'])
    if not os.path.exists(src):
        sys.exit('%s: not found. The source panorama is deliberately kept out '
                 'of apps/skydata (the app never fetches it, but Vite would '
                 'copy it into dist) -- pass --maptex <path> to point at it.'
                 % src)
    print('reading %s' % src)
    pano = np.asarray(Image.open(src).convert('RGBA'))
    h, w = pano.shape[:2]
    src_res = 360.0 / w
    print('  %dx%d panorama, %.4f deg/px' % (w, h, src_res))
    if abs(w - 2 * h) > 1:
        print('  WARNING: not 2:1, a spherical maptex must span 360x180 deg',
              file=sys.stderr)

    if not args.no_dilate:
        pano = dilate_colours(pano)
        print('  dilated the ground colour into the transparent sky')

    size = args.tile_width
    max_order = args.max_order
    if max_order is None:
        # first order that resolves the source, then ONE more: that last order
        # adds no detail but is what pushes the CLAMP_TO_EDGE band and the
        # split-cell lattice under a screen pixel.
        max_order = 0
        while order_resolution(max_order, size) > src_res:
            max_order += 1
        max_order += 1
    print('building orders 0..%d (deepest %.4f deg/px vs source %.4f)'
          % (max_order, order_resolution(max_order, size), src_res))

    tiles = None
    for order in range(max_order + 1):
        tiles = build_order(pano, order, size, args.quality, args.rotate,
                            args.dir, src_res, args.verbose)
        if order == 0:
            write_allsky([tiles[i] for i in range(12)],
                         os.path.join(args.dir, 'Norder0'), args.quality)
            print('    wrote Allsky.webp + Allsky_preview.png')

    now = datetime.datetime.now(datetime.timezone.utc)
    write_properties(os.path.join(args.dir, 'properties'), title, max_order,
                     size, now.strftime('%Y-%m-%dT%H:%MZ'))
    print('  wrote properties (obs_title = %s, hips_order = %d)'
          % (title, max_order))
    write_descriptions(args.dir, title, ini)
    if args.check:
        check_roundtrip(max_order, tiles, args.check, args.rotate)


if __name__ == '__main__':
    main()
