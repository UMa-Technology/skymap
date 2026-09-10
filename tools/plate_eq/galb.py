import numpy as np, healpy as hp
# hips_frame=equatorial (J2000/ICRS). Convert tile-center to galactic latitude b.
_ROT_C2G = hp.Rotator(coord=['C','G'])   # celestial(equatorial) -> galactic

def tile_center_vec(order, npix):
    nside = 1<<order
    return np.array(hp.pix2vec(nside, npix, nest=True))

def tile_center_galactic_b(order, npix):
    """Galactic latitude b (deg) of the tile center. hips_frame=equatorial (ICRS)."""
    v = tile_center_vec(order, npix)               # equatorial unit vector
    vg = _ROT_C2G(v)                               # rotate to galactic
    b = np.degrees(np.arcsin(np.clip(vg[2], -1, 1)))
    return float(b)

# ---- validation against known anchors ----
def eq_vec_from_radec(ra,dec):
    ra,dec=np.radians(ra),np.radians(dec)
    return np.array([np.cos(dec)*np.cos(ra),np.cos(dec)*np.sin(ra),np.sin(dec)])
def gal_b_of_radec(ra,dec):
    return np.degrees(np.arcsin(np.clip(_ROT_C2G(eq_vec_from_radec(ra,dec))[2],-1,1)))
print("VALIDATION (expected b):")
print(f"  Galactic center RA266.405 Dec-28.936 -> b={gal_b_of_radec(266.405,-28.936):+.3f} (exp ~0)")
print(f"  NGP RA192.859 Dec+27.128 -> b={gal_b_of_radec(192.859,27.128):+.3f} (exp +90)")
print(f"  SGP RA12.859 Dec-27.128 -> b={gal_b_of_radec(12.859,-27.128):+.3f} (exp -90)")
print(f"  Anticenter RA86.4 Dec+28.9 -> b={gal_b_of_radec(86.405,28.936):+.3f} (exp ~0)")

# distribution: how many order-3 tiles are |b|<20 (MW band) vs >=20
for order in (3,4):
    nside=1<<order; npix=12*nside*nside
    b=np.array([tile_center_galactic_b(order,p) for p in range(npix)])
    print(f"order{order}: |b|<10:{np.sum(np.abs(b)<10)}  10-20:{np.sum((np.abs(b)>=10)&(np.abs(b)<20))}  "
          f">=20:{np.sum(np.abs(b)>=20)}  (total {npix})")
    if order==3:
        # tile radius ~ half diagonal; a tile spans ~7.3deg, so classify with a margin
        band=np.where(np.abs(b)<25)[0]
        print(f"  order3 |b|<25 (MW-risk band incl. margin): {len(band)} tiles")
