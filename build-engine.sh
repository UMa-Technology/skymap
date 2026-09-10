#!/usr/bin/env bash
#
# build-engine.sh — rebuild the C engine to WASM/JS and install it into the
# web frontend, in one command.
#
# This is the modern-emscripten path (no Docker, native arm64). It replaces the
# stale Docker/emsdk-1.39.17 build that used to live in apps/web-frontend/Makefile
# (removed once this native path took over). See dev_docs/local-build-and-run.md
# for the full rationale and the SConstruct migration notes.
#
# Usage:
#   ./build-engine.sh                 # release build
#   ./build-engine.sh mode=debug      # any extra args are passed to scons
#
# Prereqs (see dev_docs/local-build-and-run.md):
#   - emscripten SDK activated (this script sources $EMSDK_ENV, default
#     ~/emsdk/emsdk_env.sh; override by exporting EMSDK_ENV).
#   - scons on PATH (brew install scons).
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

ENGINE_JS="build/stellarium-web-engine.js"
ENGINE_WASM="build/stellarium-web-engine.wasm"
# 两个前端目录都装：标准 GUI 版 + App 嵌入版（web-frontend-app）
FRONTEND_JS_DIRS="apps/web-frontend/src/assets/js apps/web-frontend-app/src/assets/js"

# 1. Make sure emcc is available; source the emsdk env if not.
if ! command -v emcc >/dev/null 2>&1; then
  EMSDK_ENV="${EMSDK_ENV:-$HOME/emsdk/emsdk_env.sh}"
  if [ -f "$EMSDK_ENV" ]; then
    echo "==> emcc not on PATH; sourcing $EMSDK_ENV"
    # shellcheck disable=SC1090
    source "$EMSDK_ENV"
  fi
fi
if ! command -v emcc >/dev/null 2>&1; then
  echo "ERROR: emcc not found. Activate the emscripten SDK first:" >&2
  echo "  source ~/emsdk/emsdk_env.sh   (or export EMSDK_ENV=/path/to/emsdk_env.sh)" >&2
  exit 1
fi

# 2. Build the ES6 module (release by default; extra CLI args go to scons).
#    werror=0: emscripten 6's clang is new enough that the 2019 C code trips
#    many new warnings; do not let -Werror abort the build.
echo "==> scons -j8 mode=release es6=1 werror=0 $*"
scons -j8 mode=release es6=1 werror=0 "$@"

# 3. Patch import.meta.url -> self.location.href.
#    EXPORT_ES6 output hardcodes import.meta.url to locate the wasm. The engine's
#    real wasm URL comes from Module.wasmFile (set in sw_helpers.js), so this
#    value is never actually used; self.location.href is a valid absolute URL in
#    both window and worker. (sed -i.bak form is portable across BSD/GNU sed.)
echo "==> patching import.meta.url in $ENGINE_JS"
sed -i.bak 's/import\.meta\.url/self.location.href/g' "$ENGINE_JS"
rm -f "$ENGINE_JS.bak"

# 4. Install into the frontends.（目录不存在则创建，强制覆盖拷贝）
for dir in $FRONTEND_JS_DIRS; do
  mkdir -p "$dir"
  echo "==> installing engine into $dir"
  cp -f "$ENGINE_JS" "$ENGINE_WASM" "$dir/"
done

echo "==> done. Engine rebuilt and installed. (Restart 'npm run dev' if it was running.)"
