import glob
import os
import sys

vars = Variables()
vars.AddVariables(
    EnumVariable('mode', 'Build mode', 'debug',
        allowed_values=('debug', 'release', 'profile')),
    BoolVariable('es6', 'Create ES6 js module', False),
    BoolVariable('werror', 'Warnings as error', True),
)

VariantDir('build/src', 'src', duplicate=0)
VariantDir('build/ext_src', 'ext_src', duplicate=0)
env = Environment(variables=vars)

env.Append(CFLAGS= '-Wall -std=gnu11 -Wno-unknown-pragmas -D_GNU_SOURCE '
                   '-Wno-missing-braces',
           CXXFLAGS='-Wall -std=gnu++11 -Wno-narrowing '
                    '-Wno-unknown-pragmas -Wno-unused-function')

if env['werror']:
    env.Append(CCFLAGS='-Werror')

if env['mode'] == 'debug':
    env.Append(CCFLAGS=['-O0', '-DCOMPILE_TESTS'])

if env['mode'] in ['profile', 'debug']:
    env.Append(CCFLAGS='-g', LINKFLAGS='-g')

if env['mode'] != 'debug':
    env.Append(CCFLAGS='-DNDEBUG')

sources = (glob.glob('src/*.c*') + glob.glob('src/algos/*.c') +
           glob.glob('src/projections/*.c') + glob.glob('src/modules/*.c') +
           glob.glob('src/utils/*.c') + glob.glob('src/private/*.c'))
env.Append(CPPPATH=['src'])

env.Append(CCFLAGS='-include config.h')

sources += glob.glob('ext_src/erfa/*.c')
env.Append(CPPPATH=['ext_src/erfa'])

sources += glob.glob('ext_src/json/*.c')
env.Append(CPPPATH=['ext_src/json'])

env.Append(CPPPATH=['ext_src/uthash'])
env.Append(CPPPATH=['ext_src/stb'])

sources += glob.glob('ext_src/zlib/*.c')
env.Append(CPPPATH=['ext_src/zlib'])
env.Append(CFLAGS=['-DHAVE_UNISTD_H'])

sources += glob.glob('ext_src/inih/*.c')
env.Append(CPPPATH=['ext_src/inih'])

sources += glob.glob('ext_src/nanovg/*.c')
env.Append(CPPPATH=['ext_src/nanovg'])

sources += glob.glob('ext_src/md4c/*.c')
env.Append(CPPPATH=['ext_src/md4c'])
env.Append(CFLAGS=['-DMD4C_USE_UTF8'])

# Add webp
sources += (
    'ext_src/webp/src/dec/alpha_dec.c',
    'ext_src/webp/src/dec/buffer_dec.c',
    'ext_src/webp/src/dec/frame_dec.c',
    'ext_src/webp/src/dec/idec_dec.c',
    'ext_src/webp/src/dec/io_dec.c',
    'ext_src/webp/src/dec/quant_dec.c',
    'ext_src/webp/src/dec/tree_dec.c',
    'ext_src/webp/src/dec/vp8_dec.c',
    'ext_src/webp/src/dec/vp8l_dec.c',
    'ext_src/webp/src/dec/webp_dec.c',
    'ext_src/webp/src/utils/bit_reader_utils.c',
    'ext_src/webp/src/utils/color_cache_utils.c',
    'ext_src/webp/src/utils/filters_utils.c',
    'ext_src/webp/src/utils/huffman_utils.c',
    'ext_src/webp/src/utils/quant_levels_dec_utils.c',
    'ext_src/webp/src/utils/random_utils.c',
    'ext_src/webp/src/utils/rescaler_utils.c',
    'ext_src/webp/src/utils/thread_utils.c',
    'ext_src/webp/src/utils/utils.c',
    'ext_src/webp/src/dsp/cpu.c',
    'ext_src/webp/src/dsp/dec_clip_tables.c')

for fname in ['alpha_processing', 'dec', 'filters', 'lossless', 'rescaler',
        'upsampling', 'yuv']:
    sources += ('ext_src/webp/src/dsp/' + fname + '.c', )

env.Append(CPPPATH=['ext_src/webp'])
env.Append(CPPPATH=['ext_src/webp/src'])

sources = ['build/%s' % x for x in sources]

if not env.GetOption('clean'):
    # Modern emscripten (>= 2.0) no longer ships the scons 'emscripten' tool or
    # the 'emscons' wrapper, so instead of env.Tool('emscripten') we drive the
    # emcc/em++ toolchain directly. `emcc`/`em++` must be on PATH (source
    # emsdk_env.sh first).
    env.Replace(CC='emcc', CXX='em++', LINK='em++', AR='emar', RANLIB='emranlib')
    # Drop macOS host-linker/compiler bits that emcc rejects.
    env.Replace(FRAMEWORKS=[], FRAMEWORKPATH=[])
    # scons sanitizes the subprocess environment by default; pass the caller's
    # environment through so the emsdk tools (emcc/em++) and their config
    # (PATH, EM_CONFIG, EMSDK, EM_CACHE, ...) set by emsdk_env.sh are visible.
    env['ENV'] = dict(os.environ)

# Clang does not like overrided initializers.
env.Append(CCFLAGS=['-Wno-initializer-overrides'])
env.Append(CCFLAGS='-DNO_LIBCURL')

# All the emscripten runtime methods the JS glue (src/js/*.js) uses.
# ALLOC_NORMAL / allocate / writeAsciiToMemory were removed in modern
# emscripten (the glue no longer uses them, see src/js/obj.js).
runtime_methods = ','.join([
    'GL',
    # HEAPU8 is exported so the app / dev console can watch the live wasm
    # heap size ($stel.HEAPU8.buffer.byteLength) now that memory can grow.
    'HEAPU8',
    'UTF8ToString',
    'addFunction',
    'ccall',
    'cwrap',
    'getValue',
    'intArrayFromString',
    'lengthBytesUTF8',
    'removeFunction',
    'setValue',
    'stringToUTF8',
    'writeArrayToMemory',
])
# _malloc / _free are wasm exports, so they belong in EXPORTED_FUNCTIONS.
exported_functions = '_malloc,_free'

flags = [
         '-s', 'MODULARIZE=1', '-s', 'EXPORT_NAME=StelWebEngine',
         # Memory growth is required for low-end phones: a fixed 512 MiB
         # INITIAL_MEMORY makes WebAssembly.instantiate() fail with
         # "RangeError: Out of memory: wasm memory" on devices that cannot
         # hand out that much contiguous memory up front.
         # GROWABLE_ARRAYBUFFERS=0 is what makes growth safe here: it forces
         # the classic detach-and-copy growth path (plain non-resizable
         # ArrayBuffer + updateMemoryViews()) instead of the resizable
         # ArrayBuffer backing (default since emscripten 6.x), which Chrome
         # rejects in texImage2D / TextDecoder.decode ("must not be
         # resizable"), breaking every render frame.
         '-s', 'ALLOW_MEMORY_GROWTH=1',
         '-s', 'GROWABLE_ARRAYBUFFERS=0',
         '-s', 'INITIAL_MEMORY=67108864',
         '-s', 'MAXIMUM_MEMORY=536870912',
         '-s', 'ALLOW_TABLE_GROWTH=1',
         '--pre-js', 'src/js/pre.js',
         '--pre-js', 'src/js/obj.js',
         '--pre-js', 'src/js/geojson.js',
         '--pre-js', 'src/js/canvas.js',
         # '-s', 'STRICT=1', # Note: to put back once we switch to emsdk 2
         '-s', 'RESERVED_FUNCTION_POINTERS=10',
         '-O3',
         '-s', 'USE_WEBGL2=1',
         # Only emit browser/worker code paths. Without this, modern emscripten
         # emits a Node.js branch using `import.meta.url` and `import("node:*")`,
         # which webpack 4 (the frontend bundler) cannot parse.
         '-s', 'ENVIRONMENT=web,worker',
         '-s', 'NO_EXIT_RUNTIME=1',
         '-s', 'EXPORTED_FUNCTIONS=%s' % exported_functions,
         '-s', 'EXPORTED_RUNTIME_METHODS=%s' % runtime_methods,
         '-s', 'FILESYSTEM=0'
        ]

#if env['mode'] not in ['profile', 'debug']:
#    flags += ['--closure', '1']

if env['mode'] in ['profile', 'debug']:
    flags += [
        '--profiling',
        '-s', 'ASM_JS=2', # Removes 'use asm'.
    ]

if env['mode'] == 'debug':
    flags += ['-s', 'SAFE_HEAP=1', '-s', 'ASSERTIONS=1',
              '-s', 'WARN_UNALIGNED=1']

if env['es6']:
    # USE_ES6_IMPORT_META=0 is no longer supported by modern emscripten
    # (import.meta.url is always used to locate the .wasm).
    flags += ['-s', 'EXPORT_ES6=1']

env.Append(CCFLAGS=['-DNO_ARGP', '-DGLES2 1'] + flags)
env.Append(LINKFLAGS=flags)
env.Append(LIBS=['GL'])

prog = env.Program(target='build/stellarium-web-engine.js', source=sources)
env.Depends(prog, glob.glob('src/*.js'))
env.Depends(prog, glob.glob('src/js/*.js'))

# Copy js files in the html example after build.
env.Depends('build/stellarium-web-engine.wasm', prog)

# Native CLI binary (only used for --gen-doc / tests). emcc cannot build a
# host executable and its output would collide with the wasm target above, so
# skip it in the emscripten build.
if env.get('native_build'):
    env.Program(target='build/stellarium-web-engine', source=sources)

# Ugly hack to run makeasset before each compilation
from subprocess import call
call('./tools/make-assets.py')
