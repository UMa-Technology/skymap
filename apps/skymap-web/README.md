# SkyMap web layer

This directory is the SkyMap embeddable web layer built on the Stellarium Web
Engine: a Vue 3 + Vuetify 3 project, bundled with Vite. It builds into
`dist.zip` for host apps to embed; see [USAGE.md](USAGE.md) for the bridge
contract.

## Build and run

Prerequisites: Node >= 20.19 (Node 24 recommended), plus the emscripten SDK
and scons for building the engine. See
the root [README](../../README.md)
for the full setup and rationale.

``` bash
# 1. Build the WASM/JS engine and install it into this frontend.
#    Run from the repository root. Only needed the first time, or after
#    changing the C engine (src/*.c).
./build-engine.sh

# 2. Install frontend dependencies and run the dev GUI
#    (http://localhost:8080, with hot-reload).
npm install
npm run dev

# 3. Compile a static production build into dist/.
npm run build

# 4. Preview the production build locally.
npm run preview
```
