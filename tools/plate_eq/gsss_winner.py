"""Port of STScI GetImage plate selection (FURTHEST_FROM_EDGE) using GSSS .dsh headers.
Builds all-sky nside-512 winner-region label maps per channel."""
import os, re, glob, json
import numpy as np
import healpy as hp

ARCSEC = 206264.80624709636

def parse_dsh(path):
    txt = open(path, 'rb').read().decode('latin1')
    cards = {}
    for i in range(0, len(txt) - 79, 80):
        card = txt[i:i+80]
        if card.startswith('END'): break
        m = re.match(r'([A-Z0-9_\-]+)\s*=\s*([^/]+)', card)
        if not m: continue
        k = m.group(1); v = m.group(2).strip()
        if v.startswith("'"):
            cards[k] = v.strip("' ").strip()
        else:
            try: cards[k] = float(v)
            except ValueError: pass
    need = ['PLATERA','PLATEDEC','PLTSCALE','XPIXELSZ','YPIXELSZ','PPO3','PPO6','XPIXELS','YPIXELS']
    if any(k not in cards for k in need): return None
    amdx = np.array([cards.get('AMDX%d'%i, 0.0) for i in range(1, 14)])
    amdy = np.array([cards.get('AMDY%d'%i, 0.0) for i in range(1, 14)])
    if abs(amdx[0]) < 1e-12: return None
    return dict(region=cards.get('REGION', os.path.basename(path)[:-4]),
                ra=cards['PLATERA'], dec=cards['PLATEDEC'], scale=cards['PLTSCALE'],
                xsz=cards['XPIXELSZ'], ysz=cards['YPIXELSZ'],
                ppo3=cards['PPO3'], ppo6=cards['PPO6'],
                nx=cards['XPIXELS'], ny=cards['YPIXELS'], amdx=amdx, amdy=amdy)

def poly13(cf, x, y):
    x2 = x*x; y2 = y*y; r2 = x2 + y2
    v = (cf[0]*x + cf[1]*y + cf[2] + cf[3]*x2 + cf[4]*x*y + cf[5]*y2 + cf[6]*r2 +
         cf[7]*x2*x + cf[8]*x2*y + cf[9]*x*y2 + cf[10]*y2*y +
         cf[11]*x*r2 + cf[12]*x*r2*(x2*y2))   # term 12 exactly as GetImage astrmcal.c
    return v

def poly13_grad(cf, x, y):
    x2=x*x; y2=y*y; r2=x2+y2
    dvx = (cf[0] + 2*cf[3]*x + cf[4]*y + 2*cf[6]*x + 3*cf[7]*x2 + 2*cf[8]*x*y + cf[9]*y2 +
           cf[11]*(r2 + 2*x2) + cf[12]*((r2 + 2*x2)*(x2*y2) + x*r2*(2*x*y2)))
    dvy = (cf[1] + cf[4]*x + 2*cf[5]*y + 2*cf[6]*y + cf[8]*x2 + 2*cf[9]*x*y + 3*cf[10]*y2 +
           cf[11]*(2*x*y) + cf[12]*(2*y*x*r2*x2 + x*(2*y)*x2*y2*0 + x*(2*y)*(x2*y2)*0 + x*(r2*2*y*x2 if False else 0)))
    # exact dvy for term12: d/dy [x*r2*x2*y2] = x*x2*(dr2/dy*y2 + r2*2y) = x*x2*(2y*y2 + 2y*r2)
    dvy = (cf[1] + cf[4]*x + 2*cf[5]*y + 2*cf[6]*y + cf[8]*x2 + 2*cf[9]*x*y + 3*cf[10]*y2 +
           cf[11]*(2*x*y) + cf[12]*(x*x2*(2*y*y2 + 2*y*r2)))
    return dvx, dvy

def sky_to_pixel(pl, ra, dec):
    """Vectorized amdinv: RA/Dec deg -> plate pixel x,y. Returns x,y (pixels)."""
    ra0 = np.radians(pl['ra']); de0 = np.radians(pl['dec'])
    a = np.radians(ra); d = np.radians(dec)
    div = np.sin(d)*np.sin(de0) + np.cos(d)*np.cos(de0)*np.cos(a - ra0)
    xi  = np.cos(d)*np.sin(a - ra0)/div*ARCSEC
    eta = (np.sin(d)*np.cos(de0) - np.cos(d)*np.sin(de0)*np.cos(a - ra0))/div*ARCSEC
    ox = xi/pl['scale']; oy = eta/pl['scale']
    for _ in range(6):
        f = poly13(pl['amdx'], ox, oy) - xi
        g = poly13(pl['amdy'], oy, ox) - eta          # NOTE: y-poly takes (oy,ox)
        fx, fy = poly13_grad(pl['amdx'], ox, oy)
        gy, gx = poly13_grad(pl['amdy'], oy, ox)
        det = fx*gy - fy*gx
        dx = (-f*gy + g*fy)/det; dy = (-g*fx + f*gx)/det
        ox = ox + dx; oy = oy + dy
        if np.max(np.abs(dx)) < 1e-5 and np.max(np.abs(dy)) < 1e-5: break
    x = (pl['ppo3'] - ox*1000.0)/pl['xsz']
    y = (pl['ppo6'] + oy*1000.0)/pl['ysz']
    return x, y

def build_winner_map(plates, nside=512, radius_deg=5.0):
    npix = hp.nside2npix(nside)
    best_margin = np.full(npix, -1e9, np.float32)
    winner = np.full(npix, -1, np.int32)
    for idx, pl in enumerate(plates):
        vec = hp.ang2vec(pl['ra'], pl['dec'], lonlat=True)
        pix = hp.query_disc(nside, vec, np.radians(radius_deg), nest=True)
        if len(pix) == 0: continue
        ra, dec = hp.pix2ang(nside, pix, nest=True, lonlat=True)
        x, y = sky_to_pixel(pl, ra, dec)
        margin = np.minimum.reduce([x, y, pl['nx'] - x, pl['ny'] - y]).astype(np.float32)
        upd = (margin > 0) & (margin > best_margin[pix])
        bp = pix[upd]
        best_margin[bp] = margin[upd]
        winner[bp] = idx
    return winner, best_margin

def load_channel(hdr_dir, prefixes):
    plates = []
    for f in sorted(glob.glob(os.path.join(hdr_dir, '*.dsh'))):
        base = os.path.basename(f)
        if not any(re.match(p + r'\d', base) for p in prefixes): continue
        pl = parse_dsh(f)
        if pl: plates.append(pl)
    return plates

if __name__ == '__main__':
    import sys, time
    SC = os.path.dirname(os.path.abspath(__file__))
    hdr = os.path.join(SC, 'getimage/hdrs/DSSHeaders')
    t0 = time.time()
    for chan, prefixes in [('red', ['XP','XS','ER','GR']), ('blue', ['XJ','S'])]:
        plates = load_channel(hdr, prefixes)
        print(chan, 'plates:', len(plates), {p: sum(1 for x in plates if x['region'].startswith(p)) for p in prefixes}, flush=True)
        winner, margin = build_winner_map(plates)
        regions = np.array([p['region'] for p in plates])
        cov = float(np.mean(winner >= 0))
        np.savez(os.path.join(SC, f'winner_{chan}.npz'), winner=winner, margin=margin, regions=regions)
        print(chan, 'coverage %.4f  time %.0fs' % (cov, time.time() - t0), flush=True)
