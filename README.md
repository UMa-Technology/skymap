# SkyMap

SkyMap is an offline, embeddable star-map web layer built on a fork of
[Stellarium Web Engine](https://github.com/Stellarium/stellarium-web-engine):
a C planetarium engine compiled to WebAssembly, driven by a Vue 3 page that
talks to its host through a small JavaScript bridge. It ships with its own
sky data (stars, deep-sky objects, DSS survey, landscapes, translations).

This repository is the **base**: engine, web layer, data and build tools.
Host applications (Flutter apps, native WebViews) consume the single build
artifact `dist.zip` published on the orphan `dist` branch; they are not part
of this repository.

## Repository layout

| Path | What |
|---|---|
| `src/`, `data/`, `ext_src/`, `SConstruct` | C engine and its build |
| `build-engine.sh` | Builds the engine to WASM/JS and installs it into the web layer |
| `apps/skymap-web/` | The web layer (Vite + Vue 3). `USAGE.md` documents the JS bridge |
| `apps/skydata/` | Sky data served by the web layer (`apps/skymap-web/public/skydata` is a symlink to it) |
| `tools/` | Data pipelines (catalogs, translations, fonts, survey cleaning) and `make-dist-zip.sh` |
| `tools/release.sh` | Tags a release and publishes `dist.zip` on the orphan `dist` branch (git-lfs) |
| `tools/sync-github.sh` | Fast-forwards the `github` branch and pushes it to the GitHub mirror |
| `.github/workflows/` | CI build gate; tag-triggered release of `dist.zip` |

`dev_docs/` and `docs/` are ignored: internal notes live in a private
repository and are symlinked in on developer machines.

Branches: `develop` (daily work) → `main` (stable) → `github` (the snapshot mirrored to
GitHub `main` by `tools/sync-github.sh`). The orphan `dist` branch holds only release
artifacts.

## Build the engine

Prerequisites: the [emscripten SDK](https://emscripten.org) **6.0.2** activated
in your shell (`source ~/emsdk/emsdk_env.sh`) and `scons` (`pip install scons`).

```bash
./build-engine.sh          # release build; extra args go to scons (e.g. mode=debug)
```

This writes `apps/skymap-web/src/assets/js/stellarium-web-engine.{js,wasm}`
(git-ignored). Rerun after changing anything under `src/`.

## Build the web layer

Prerequisites: Node 24 (`apps/skymap-web/.nvmrc`), Python 3 with
`fonttools` and `brotli` (`pip install fonttools brotli`, used by the icon
subsetter).

```bash
cd apps/skymap-web
npm ci
npm run dev        # http://localhost:8080 with hot reload
npm run build      # dist/ → dist.zip + dist.zip.sha256 + dist.zip.json
npx vitest run     # unit tests
npm run lint
```

`npm run build` runs `tools/make-dist-zip.sh` afterwards, producing a
byte-reproducible `dist.zip` (normalized mtimes and permissions) next to two
sidecars: the SHA-256 and a JSON record of the commit, dirtiness, staleness,
engine WASM hash and version.

Python tests for the packaging scripts:

```bash
python3 -m pytest tools/tests/test_make_dist_zip.py tools/tests/test_install_dist.py
```

The DSS survey-cleaning suite under `tools/tests/` needs the scientific stack
in `tools/requirements-clean-dss.txt` (Python 3.11) and is not run in CI.

## Releases and the handshake

`tools/release.sh vX.Y.Z` (run on a clean `main`) builds the web layer with the version
baked in, tags the commit `vX.Y.Z`, and commits `dist.zip`, `dist.zip.sha256` and
`dist.zip.json` to the orphan `dist` branch (git-lfs) tagged `dist/vX.Y.Z`. Host
applications fetch a release with `git clone --depth 1 --branch dist/vX.Y.Z` (their
`bin/skymap_dist.py` does this and verifies the SHA-256); they never build the web layer
themselves. On the GitHub mirror, pushing a `v*` tag additionally attaches the same three
files to a GitHub Release (`.github/workflows/release.yml`).

Every build embeds its identity:

- `window.SkymapBase = { version, protocol }` on the page, and the same object
  as `base` on every `initProgress` message sent to the host;
- `skymap-base.json` inside `dist.zip` (same content);
- `"version"` in `dist.zip.json`.

`version` is the git tag (or `git describe` output for local builds).
`protocol` (`apps/skymap-web/src/protocol.js`) is bumped only when an existing
bridge action, `getState` key or inbound message changes meaning or is
removed; adding actions does not bump it. Hosts should require an exact
protocol match plus a minimum version.

## License

SkyMap is licensed under the **GNU Affero General Public License v3.0** (see
`LICENSE`). It derives from Stellarium Web Engine, Copyright (c) Stellarium
Labs SRL, forked at upstream merge base `be43d6436` (2026-05-09); upstream
changes are not merged after that point. Changes made in this fork are
Copyright (C) 2026 Suzhou UMa Technology Co., Ltd and summarized in
`CHANGELOG.md`.

Data attribution:

- DSS colored survey: Digitized Sky Survey, STScI/NASA; colored and
  HEALPix-tiled by CDS (`apps/skydata/surveys/dss/properties`).
- Moon texture by Oleg Pluton (CC BY 4.0); Sun texture from Stellarium.
- Fonts: see `tools/.fontcache/LICENSES.md`.
