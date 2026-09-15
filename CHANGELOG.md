# Changelog

## 2026-09-15 — v1.1.1

1. **Framing rectangles drawn 2px instead of 1px.** The off-centre (orange) and centred (blue) field-of-view frames in `framing-overlay.vue` now match the border width the mosaic outline already used, so the frame stays legible against a bright sky. The dashed mosaic tile grid is unchanged.

## 2026-09-14 — v1.1.0

1. **Deep-sky annotation shapes dimmed to 50%.** The unselected hint alpha in `dso_hint_color` went from 0.7 to 0.5, so circles, ellipses and boxes recede into the sky. Names are unaffected: `dso_render_label` overrides the alpha to 0.95 for unselected labels, and a selected object keeps a fully opaque marker.
2. **New bridge action `toggleStarLabels(visible)`.** Hides the star name labels (Bayer / Flamsteed / proper names) without hiding the stars themselves, for a clean naked-sky view; constellation and deep-sky names are unaffected. The selected star keeps its label so the selection stays identifiable. The engine property it drives (`stars.hints_visible`) already existed; `getState` now reports it under the same key.
3. **New bridge action `setSkyCulture(key)`** switches the sky culture at runtime (constellation lines, artwork and cultural names) without reloading the page, alongside the existing `?sc=` URL seed. `getState` reports the active key as `skyCulture`. Keys are restricted to `[A-Za-z0-9_-]` because they are interpolated into a URL.
4. **New sky culture `western-new`**: the same constellation lines and common names as `western`, with a new set of 85 illustrations. Its `index.json` carries `"id": "western-new"` to match the data-source key, as the engine requires; the constellation ids stay `CON western …`, which is safe because switching cultures clears every constellation object before rebuilding.
5. Corrected the `western` sky culture credit: its illustrations are by 氕氘氚Star, not the upstream author named in the inherited description.

## 2026-09-11 — v1.0.1

1. **Restored the offline cross-language object search** lost in the repository split. The index is built from the eleven shipped `sky-i18n` catalogs plus the English source keys and the western `common_names`, so a name typed in any language resolves regardless of the display language, and catalog designations (`M31`, `NGC 224`, `HIP 91262`) resolve through a normalizing lookup. The pure index and ranking logic lives in `apps/skymap-web/src/assets/sky-search.js` with unit tests; `skysource-search.vue` and the dead `querySkySources` stub were removed.

## 2026-09-11 — Repository split

1. This repository was created fresh (no history) from the team's internal fork tree. Upstream merge base: `be43d6436` (2026-05-09); upstream is not merged after that point.
2. Retired the standard-GUI tree `apps/web-frontend`; the web layer is now `apps/skymap-web` and the tooling targets only that tree.
3. Protocol handshake: `window.SkymapBase`, the `base` field on `initProgress` messages, `skymap-base.json` inside `dist.zip`, and `version` in `dist.zip.json`.
4. Releases: `tools/release.sh vX.Y.Z` tags the commit and publishes the three `dist.zip` files on the orphan `dist` branch (git-lfs); on the GitHub mirror a `v*` tag also produces a GitHub Release via Actions. `tools/sync-github.sh` mirrors `main` to GitHub on demand.

## 2026-07-08 – 2026-07-15 — Optimization sprint

### Offline operation and build
1. **Fully offline app**: disabled the NoctuaSky online API, removed the satellites module, refreshed comet data to the latest MPC orbital elements, fixed the offline geolocation crash; the console is now error-free.
2. **Modernized build chain**: the C engine moved to emscripten 6.0.2 (native arm64, no Docker); the frontend moved from vue-cli/webpack 4 to Vite 7 + Node 24 (`./build-engine.sh` rebuilds the WASM in one step).

### Offline DSS deep-sky survey
3. **Built-in offline DSS color survey** (HiPS orders 2–4, re-encoded at Q90, about 68 MB): gated by FOV and blended smoothly with the Milky Way layer; prefetching removes the black flash on level switches; an order-2 fallback layer eliminates black tiles while loading.
4. **Multi-pass cleanup of plate defects**: satellite/aircraft streaks (about 140 tiles, profile subtraction plus a streak-vs-object discriminator), bright-star diffraction spikes and ring halos, watermarks, and pupil ghosts fixed tile by tile.
5. **All-sky blue-cast cleanup** (`castclean` C module): unified detection and re-synthesis of orange (missing-blue-plate dead channel) and blue (channel imbalance) casts across 377 regions.
6. **Generic "manual annotation + strip-ramp fill" repair pipeline**: scan-and-rank → web annotation → batch fix → pyramid rebuild, all tooling in `tools/`; used to clear 46 tiles with staircase plate seams and 51 tiles with orange plate patches (real texture grain transplanted, background ramped per position on both sides).
7. **"Starless + seam-cleaned" survey enabled by default**: stars are redrawn live by the engine from the catalog, so image quality and labels no longer interfere.

### Performance and phone heat
8. **Thermal optimization, round one**: rendering pauses when the page is hidden; adaptive 60/10 fps; MSAA off on high-DPR screens; internal render resolution capped at 2×DPR (2.25× fewer shaded pixels on DPR-3 phones).
9. **Thermal optimization, round two**: fixed the throttling defect where selecting an object pinned 60 fps forever (locked tracking jittered every frame and fooled the motion check); replaced with an accumulated-pixel-motion model and three tiers — 60 fps for interaction/visible motion, 10 fps for engine animations, and one frame per 3 s minimum for a static sky; host-app API calls wake the render loop immediately; deselecting also releases the tracking lock.
10. **Atmosphere model cache and night-time skip**: the Preetham/sky-brightness model is cached by Sun and Moon position (recomputed only every few tens of seconds at real-time speed); at night, when the whole full-screen atmosphere pass stays under half a color step, it is skipped entirely, with exposure-adaptation bookkeeping unaffected.

### Rendering and engine
11. **Independent star-field exposure** (`star_exposure_scale`) and star-size contrast compression: bright stars no longer glare on high-brightness screens, and the magnitude hierarchy looks more natural.
12. **Sun rendered as a camera-facing billboard**: keeps prominence detail and looks the same on any date.
13. **New custom-horizon module** (`custom_horizon`): renders an occlusion profile supplied by the host app (translucent fill plus a ridge line) without projection artifacts at any FOV.
14. **Smoother horizon fog band**: attenuation is now computed per pixel with dithering, removing the gradient banding visible when zoomed in.

### Deep-sky objects and catalogs
15. **DSO data source replaced wholesale** by the app's real catalog (objects_catalogs): dark nebulae (LDN/Barnard) rendered with a size-plus-opacity scheme (previously invisible), label ellipses regained their position angle and orientation, duplicate proper-name labels de-duplicated.
16. **Single-select professional catalog overlays** (LDN/LBN/SH2/PK/ACO/B): all off by default, one shown when selected; per-catalog brightness compensation, dark nebulae fade in by angular size, reusing the regular DSO FOV fade rules.

### Languages and sky cultures
17. **Constellation names actually translate**: the engine gained a `sys_set_lang` hook (the frontend had never passed the language to the engine, so constellation names were always Latin) plus the missing skycultures translation domain; switchable at runtime.
18. **Chinese star names completed for all 2,658 stars** (following the Chinese asterism system, with Bayer/Flamsteed designations as the fallback for other languages, in Simplified and Traditional) plus a rebuilt CJK subset font and cleanup of trailing markers and Latin contamination in names.
19. **Constellation selection focus**: on selection the lines, name and mythological artwork fade in while everything else fades out; constellations sharing artwork (Vela/Puppis/Serpens) no longer disappear when selected; five artworks fixed for a gray glowing background.

### User interface
20. **Settings and toolbar polish**: star visibility toggle, equator line and J2000 equatorial grid added to settings; reference lines recolored (meridian blue / ecliptic green / equator orange), 1.5× thicker and opaque; catalog dropdown given an opaque background; the language picker trimmed to native names and right-aligned.
