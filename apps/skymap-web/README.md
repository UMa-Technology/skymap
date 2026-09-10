# Stellarium Web frontend

This directory contains the Graphical User Interface for using
Stellarium Web Engine in a web page.

This is a Vue 3 + Vuetify 3 project, bundled with Vite.

Official page: [stellarium-web.org](https://stellarium-web.org)

## Build and run

Prerequisites: Node >= 20.19 (Node 24 recommended), plus the emscripten SDK
and scons for building the engine. See
[../../dev_docs/local-build-and-run.md](../../dev_docs/local-build-and-run.md)
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
