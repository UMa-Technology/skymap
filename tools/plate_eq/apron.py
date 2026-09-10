"""Tile + real-neighbor apron assembly (the tiling-consistency foundation).

assemble_apron(order, pix, apron=64) -> (512+2a)^2 image whose margins are REAL
pixels from the 4 edge-neighbor tiles (dihedral-corrected, incl. polar caps).
The 4 corner a*a squares have no corner-tile data (assemble_neighbourhood fills
edge blocks only) -> filled with the mean of the two adjacent strips' mirrors,
good enough to support background-mesh interpolation at the corners.

To read from another survey dir (e.g. dss-starless), set assemble.RAW first.
"""
import numpy as np
import assemble


def assemble_apron(order, pix, apron=64, gray=False):
    canvas, _, placed = assemble.assemble_neighbourhood(order, pix, gray)
    a = int(apron)
    TW = assemble.TW
    sub = canvas[TW - a:2 * TW + a, TW - a:2 * TW + a].copy()
    n = sub.shape[0]
    # mirror-fill the four corner squares from the adjacent filled strips
    for (rs, cs) in ((slice(0, a), slice(0, a)), (slice(0, a), slice(n - a, n)),
                     (slice(n - a, n), slice(0, a)), (slice(n - a, n), slice(n - a, n))):
        r0, c0 = rs.start, cs.start
        vsrc = slice(2 * a - 1, a - 1, -1) if r0 == 0 else slice(n - a - 1, n - 2 * a - 1, -1)
        hsrc = slice(2 * a - 1, a - 1, -1) if c0 == 0 else slice(n - a - 1, n - 2 * a - 1, -1)
        sub[rs, cs] = 0.5 * (sub[vsrc, cs] + sub[rs, hsrc])
    return sub, placed


def apron_seams(order, pix, apron=64):
    """mean |step| across the tile/apron boundary (should be webp-noise level)."""
    a = apron
    sub, placed = assemble_apron(order, pix, apron, gray=True)
    n = sub.shape[0]
    t = np.mean(np.abs(sub[a - 1, a:n - a] - sub[a, a:n - a]))
    b = np.mean(np.abs(sub[n - a - 1, a:n - a] - sub[n - a, a:n - a]))
    l = np.mean(np.abs(sub[a:n - a, a - 1] - sub[a:n - a, a]))
    r = np.mean(np.abs(sub[a:n - a, n - a - 1] - sub[a:n - a, n - a]))
    return t, b, l, r, placed


if __name__ == "__main__":
    for label, pix4 in (("equatorial", 1252), ("dense-crux", 2688),
                        ("north-polar-corner(face0)", 0), ("south-polar", 3071)):
        t, b, l, r, placed = apron_seams(4, pix4)
        ks = [f"{d}:k{v[1]}/{v[2]}" for d, v in placed.items()]
        print(f"{label:28s} pix{pix4}: apron seams T{t:.2f} B{b:.2f} L{l:.2f} R{r:.2f} | {ks}")
