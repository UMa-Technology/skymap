# plate_eq — DSS2-color HiPS plate-equalization / cleaning pipeline

Offline processing that turns the raw CDS `P/DSS2/color` HiPS survey (3072 order-4
tiles + 768 order-3, 512px webp) into the cleaned layers served by the web
frontend. Root cause of the artifacts: `P/DSS2/color` is two independent HiPS
mosaics (DSS2-red + DSS2-blue) whose per-plate sky subtraction leaves brightness
steps and colour casts at the plate boundaries.

Run everything from the **repo root** with the `.venv-clean-dss` interpreter and
this dir on `PYTHONPATH`, e.g.:

```
PYTHONPATH=tools/plate_eq .venv-clean-dss/bin/python tools/plate_eq/hybrid_apply.py 3072
```

## Layers produced (served via `?dss=` in the frontend)

```
dss (default, with stars, colour)         <- colour-cast + seam cleaning (v1-v9)
  └─ dss-starless   = dss with stars removed (starnet8, mask-and-composite)
       └─ dss-clean = starless + true-boundary seam leveling + fog flattening
            └─ dss-hybrid = clean + geometry-independent luminance-seam leveling
```

`dss` keeps the stars (full DSS look); `dss-hybrid` is star-removed (the engine
draws stars from its catalog). They are different products, not replacements.

## Production entry points (this session's final pipeline)

- **`hybrid_seam.py`** — geometry-independent seam corrector. Detects straight
  plate seams from the *data* (chroma-gradient Hough; the GSSS winner geometry is
  ~56px off the real CDS boundaries), classifies each edge by a step-vs-distance
  profile (flat DC step = artifact; ramps with distance = real structure), and
  levels only flat luminance steps with an equal-DN membrane (colour preserved).
  The luminance path is self-protecting (real structure ramps → skipped). An
  L-conserving R↔B colour-transfer path exists but is `COLOR_ENABLED=False` by
  default (it desaturates real blue fields). `correct_tile()` uses a real-neighbour
  apron for cross-tile consistency, falling back to the bare tile on the ~320
  face-boundary tiles where `assemble` corrupts the apron centre.
- **`hybrid_apply.py`** — full-survey batch: dss-clean → dss-hybrid (CoW-cloned),
  writes only changed tiles, rebuilds affected N3 parents.
- **`apron.py` / `assemble.py`** — tile + real-neighbour apron assembly (HEALPix
  neighbourhood, dihedral-corrected, polar caps).
- **`protect_mask.py`** — photutils-based bright/dark extended-structure mask
  (galaxies / nebulae / dark clouds kept bit-exact).
- **`chroma_seam.py`** — shared helpers (`_chroma`, `_merge_lines`, `stf`).
- Upstream chain: `starnet8.py` + `starless_tile.py` + `starless_apply.py`
  (star removal), `seam_fix.py` + `stage2_flatten.py` + `starless_stage2_apply.py`
  (dss-clean), `gsss_winner.py` (GSSS GetImage plate geometry),
  `repair_quantization.py` (single-rint rebuild-from-HEAD, the canonical writer).

## Everything else

The other scripts are earlier stages and abandoned experiments (per-region DC
solves, membrane solves, SeamNet, GraXpert trials, halo restamping, chroma-cast
cleaner). They are kept for provenance; the design decisions and dead-ends are
documented in the project memory (`project-dss-background-seam.md`). The heavy
data artifacts (model checkpoints, `.npz` fields, reference clones) were left in
the scratchpad and are not vendored here.

Environment: `.venv-clean-dss` (numpy2, scipy, opencv, healpy, astropy,
photutils 3.0, torch+MPS). No matplotlib.
