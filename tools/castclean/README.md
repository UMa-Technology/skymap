# castclean — plate colour-cast removal for sky-survey RGB imagery

Removes plate-level colour casts from scanned photographic sky surveys
(built for the DSS2-colour HiPS tiles, reusable in any project):

- **orange casts (R high)** — the blue plate is missing: the B channel
  background is literally black while R/G show a star field (G is synthetic
  `(R+B)/2` in the CDS composite);
- **blue casts (B high)** — plate footprints (straight edges / diamonds)
  whose channel balance is shifted.

Genuine colour — warm Milky-Way star clouds, blue reflection nebulae,
galaxies — is preserved by construction: corrections only happen where
plate evidence exists (dead-channel levels/texture, or chroma steps with no
matching luminance step). Luminance structure is never repainted.

Algorithm derivation, tuning history and validation are documented in the
internal design notes. Distilled from studying GraXpert's and Siril's background-extraction /
colour-calibration code, extended with piecewise plate handling
(chroma-Poisson seam cutting, membrane inpainting, dead-plate resynthesis)
that neither tool has.

## Files

- `castclean.h` / `castclean.c` — the module. Dependency-free C99
  (only libc + libm), compiles as C or C++. Operates in place on 8-bit
  interleaved RGB.
- `castclean_cli.c` — tiny test harness (binary PPM in / PPM out).
- `Makefile` — builds the CLI (`make`).

## Usage

```c
#include "castclean.h"

castclean_params p;
castclean_params_init(&p);          /* tuned defaults */
p.confirmed = 1;                    /* a human vouched this image is defective */

castclean_report rep;
castclean_rgb8(pixels, width, height, stride, &p, &rep);
/* rep.changed, rep.dead_frac, rep.mask_frac, rep.mean_abs_delta ... */
```

Two modes:

- **scan mode** (`confirmed = 0`, default) — conservative, safe to run
  blindly over a whole survey. Only regions with physics-certain
  dead-channel evidence are corrected (local harmonic inpainting of the
  chroma fields); everything else is bit-untouched, images without evidence
  come back unchanged. Use `report` to rank candidates for human review.
- **confirmed mode** (`confirmed = 1`) — full correction for images a human
  confirmed defective: global chroma levelling across detected plate seams
  (DCT Poisson), direction-aware defect growth, dead-region chroma
  resynthesis, optional seam-luminance levelling.

CLI:

```sh
make
./castclean_cli -confirmed in.ppm out.ppm
./castclean_cli in.ppm out.ppm            # scan mode
```

## Validation (2026-07)

- The four user-confirmed DSS tiles (Norder4 1888/1823/1816 orange,
  Norder3 448 blue+orange blocks): casts removed, seams invisible,
  output matches the tuned Python prototype within mean |diff| ≤ 1.4
  (p99 ≤ 4) — differences come from approximated blur kernels.
- Full Norder3 sweep (768 tiles, scan mode): strong defects flagged
  identically to the prototype; M31, the Pleiades reflection glow and
  genuine dark nebulae untouched. The C port's tail is slightly more
  conservative (26 vs 57 flags at the 0.15 mean-delta threshold; the extra
  Python flags are all marginal 0.15–0.36 cases).

## Limits

- 8-bit interleaved RGB only; width/height must be ≥ 4 analysis cells
  (default cell = 16 px).
- Working memory ≈ 80 bytes/pixel (float field buffers); tile or crop very
  large images.
- Dead-R auto-detection is off by default: a strict-zero R test
  false-positives on bright blue reflection nebulae, and no real missing-R
  plates were found in DSS2. Blue casts are handled in confirmed mode via
  the seam path.
- The optional `castclean_prior` (survey-wide luminance-conditioned chroma
  statistics) sharpens DC anchoring in confirmed mode; without it,
  per-image robust statistics are used.
