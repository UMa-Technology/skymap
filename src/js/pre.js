/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

// Allow to set the memory file path in 'memFile' argument.
Module['locateFile'] = function(path) {
  if (path === "stellarium-web-engine.wasm") return Module.wasmFile;
  return path;
}

Module['onRuntimeInitialized'] = function() {
  // Init OpenGL context.
  if (Module.canvasElement) Module.canvas = Module.canvasElement;
  if (Module.canvas) {
    var contextAttributes = {};
    contextAttributes.alpha = false;
    contextAttributes.depth = true;
    contextAttributes.stencil = true;
    // MSAA 常开。此前按 "DPR>=1.5 关 MSAA" 优化（假设高 DPR 像素密度足以
    // 超采样多边形边缘），但 canvas.js 把渲染分辨率封顶在 MAX_DPR=2（DPR-3
    // 手机实际 2x 渲染再放大），且照片贴图（photos.c paint_quad）会在屏幕上
    // 产生大面积高对比斜边 —— 2x 分辨率下阶梯锯齿仍然明显（照片 fov 越小、
    // 屏幕占比越小时相对越粗）。纹理侧的 mipmap/三线性只影响内容采样，管不到
    // 几何边缘，必须靠 MSAA。移动端 GPU 全是 tile-based，4x MSAA 在片上
    // resolve，代价远低于桌面直觉。
    contextAttributes.antialias = true;
    contextAttributes.premultipliedAlpha = true;
    contextAttributes.preserveDrawingBuffer = false;
    contextAttributes.preferLowPowerToHighPerformance = false;
    contextAttributes.failIfMajorPerformanceCaveat = false;
    contextAttributes.majorVersion = 1;
    contextAttributes.minorVersion = 0;
    var ctx = Module.GL.createContext(Module.canvas, contextAttributes);
    Module.GL.makeContextCurrent(ctx);
  }

  // Since we are going to redefine the setValue and getValue methods,
  // I put the old one in new attributes so that we can still use them.
  Module['_setValue'] = Module['setValue'];
  Module['_getValue'] = Module['getValue'];

  // Call all the functions registered with Module.afterInit(f)
  for (var i in Module.extendFns) { Module.extendFns[i]() }

  Module._core_init(0, 0, 1);
  Module.core = Module.getModule('core');
  Module.observer = Module.core.observer;

  // Setup the translation function provided by the client if any.
  if (Module.translateFn) {
    Module.translationsCache = {};
    let callback = Module.addFunction(function(user, domain, str) {
      domain = Module.UTF8ToString(domain);
      str = Module.UTF8ToString(str);
      str = Module.translateFn(domain, str);
      let value = Module.translationsCache[str];
      if (value) return value;
      let size = Module.lengthBytesUTF8(str) + 1;
      value = Module._malloc(size);
      Module.stringToUTF8(str, value, size);
      Module.translationsCache[str] = value;
      return value;
    }, 'iiii');
    Module._sys_set_translate_function(callback);
  }

  if (Module.onReady) Module.onReady(Module);
}

// All to register functions that will be called only after the runtime
// is initialized.
Module['extendFns'] = [];
Module['afterInit'] = function(f) {
  Module.extendFns.push(f);
}

// Add some methods to the module

Module['D2R'] = Math.PI / 180;
Module['R2D'] = 180 / Math.PI;

// Expose the frame enum.
// Make sure that correspond to the values in frames.h!
Module['FRAME_ASTROM'] = 0;
Module['FRAME_ICRF'] = 1;
Module['FRAME_CIRS'] = 2;
Module['FRAME_JNOW'] = 3;
Module['FRAME_OBSERVED_GEOM'] = 4;
Module['FRAME_OBSERVED'] = 5;
Module['FRAME_MOUNT'] = 6;
Module['FRAME_VIEW'] = 7;
Module['FRAME_ECLIPTIC'] = 8;

Module['MJD2date'] = function(v) {
  return new Date(Math.round((v + 2400000.5 - 2440587.5) * 86400000));
}

Module['date2MJD'] = function(date) {
  return date / 86400000 - 2400000.5 + 2440587.5;
}

/*
 * Function: a2tf
 * Decompose radians into hours, minutes, seconds, fraction.
 *
 * This is a direct wrapping of erfaA2tf.
 *
 * Parameters:
 *   angle      - Angle in radians.
 *   resolution - Number of decimal (see erfa doc for full explanation).
 *                default to 0 (no decimals).
 *
 * Return:
 *   an object with the following attributes:
 *     sign ('+' or '-')
 *     hours
 *     minutes
 *     seconds
 *     fraction
 */
Module['a2tf'] = function(angle, resolution) {
  resolution = resolution || 0;
  var a2tf_json = Module.cwrap('a2tf_json', 'number', ['number', 'number']);
  var cret = a2tf_json(resolution, angle);
  var ret = Module.UTF8ToString(cret);
  Module._free(cret);
  ret = JSON.parse(ret);
  return ret;
}

/*
 * Function: a2af
 * Decompose radians into degrees, arcminutes, arcseconds, fraction.
 *
 * This is a direct wrapping of erfaA2af.
 *
 * Parameters:
 *   angle      - Angle in radians.
 *   resolution - Number of decimal (see erfa doc for full explanation).
 *                default to 0 (no decimals).
 *
 * Return:
 *   an object with the following attributes:
 *     sign ('+' or '-')
 *     degrees
 *     arcminutes
 *     arcseconds
 *     fraction
 */
Module['a2af'] = function(angle, resolution) {
  resolution = resolution || 0;
  var a2af_json = Module.cwrap('a2af_json', 'number', ['number', 'number']);
  var cret = a2af_json(resolution, angle);
  var ret = Module.UTF8ToString(cret);
  Module._free(cret);
  ret = JSON.parse(ret);
  return ret;
}

/*
 * Function: designationCleanup
 * Create a printable version of a designation
 *
 * This can be used for example to compute the label to render for an object.
 *
 * Parameters:
 *   d     - the designation string.
 *   flags - formatting flags
 *
 * Return:
 *   A human-friendly designation.
 */
Module['designationCleanup'] = function(d, flags) {
  const designation_cleanup = Module.cwrap('designation_cleanup',
                                           null, ['string', 'number',
                                                  'number', 'number']);
  const cbuf = Module._malloc(256);
  designation_cleanup(d, cbuf, 256, flags);
  const ret = Module.UTF8ToString(cbuf);
  Module._free(cbuf);
  return ret;
}

Module['c2s'] = function(v) {
  var x = v[0];
  var y = v[1];
  var z = v[2];
  var d2 = x * x + y * y;
  var theta = (d2 == 0.0) ? 0.0 : Math.atan2(y, x);
  var phi = (z === 0.0) ? 0.0 : Math.atan2(z, Math.sqrt(d2));
  return [theta, phi];
}

Module['s2c'] = function(theta, phi) {
  var cp = Math.cos(phi);
  return [Math.cos(theta) * cp, Math.sin(theta) * cp, Math.sin(phi)];
}

// Normalize angle into the range 0 <= a < 2pi.
Module['anp'] = function(a) {
  var v = a % (2 * Math.PI);
  if (v < 0) v += 2 * Math.PI;
  return v;
}

// Normalize angle into the range -pi <= a < +pi.
Module['anpm'] = function(a) {
  var v = a % (2 * Math.PI);
  if (Math.abs(v) >= Math.PI) v -= 2 * Math.PI * Math.sign(a);
  return v;
}

const asFrame = function(f) {
  if (f === 'ASTROM') return Module.FRAME_ASTROM;
  if (f === 'ICRF') return Module.FRAME_ICRF;
  if (f === 'CIRS') return Module.FRAME_CIRS;
  if (f === 'JNOW') return Module.FRAME_JNOW;
  if (f === 'OBSERVED') return Module.FRAME_OBSERVED;
  if (f === 'OBSERVED_GEOM') return Module.FRAME_OBSERVED_GEOM;
  if (f === 'MOUNT') return Module.FRAME_MOUNT;
  if (f === 'VIEW') return Module.FRAME_VIEW;
  assert(typeof(f) === 'number');
  return f;
}

/*
 * Function: convertFrame
 * Rotate the passed apparent coordinate vector from a Reference Frame to
 * another.
 *
 * Check the 4th component of the input vector
 * to know if the source is at infinity. If in[3] == 0.0, the source is at
 * infinity and the vector must be normalized, otherwise assume the vector to
 * contain the real object's distance in AU.
 *
 * The vector represents the apparent position/direction of the source as seen
 * by the observer in his reference system (usually GCRS for earth observation).
 * This means that effects such as space motion, light deflection or annual
 * aberration must already be taken into account before calling this function.
 *
 * Parameters:
 *   obs    - The observer.
 *   origin - Origin frame ('ASTROM', 'ICRF', 'CIRS', 'JNOW', 'OBSERVED',
 *            'OBSERVED_GEOM', 'VIEW').
 *   dest   - Destination frame (same as origin).
 *   v      - A 4d vector.
 *
 * Return:
 *   A 4d vector.
 */
Module['convertFrame'] = function(obs, origin, dest, v) {
  origin = asFrame(origin);
  dest = asFrame(dest);
  var v4 = [v[0], v[1], v[2], v[3] || 0.0];
  var ptr = Module._malloc(8 * 8);
  var i;
  for (i = 0; i < 4; i++)
    Module._setValue(ptr + i * 8, v4[i], 'double');
  Module._convert_framev4(obs.v, origin, dest, ptr, ptr + 4 * 8);
  var ret = new Array(4);
  for (i = 0; i < 4; i++)
    ret[i] = Module._getValue(ptr + (4 + i) * 8, 'double')
  Module._free(ptr);
  return ret;
}

/*
 * Function: lookAt
 * Move view direction to the given position.
 *
 * For example this can be used after core_get_point_for_mag to estimate the
 * angular size a circle should have to exactly fit the object.
 *
 * Parameters:
 *   pos      - The wanted pointing 3D direction in the OBSERVED frame.
 *   duration - Movement duration in sec.
 */
Module['lookAt'] = function(pos, duration) {
  if (duration === undefined)
    duration = 1.0;
  if (Module._apiActivity) Module._apiActivity();
  var v = Module._malloc(3 * 8);
  var i;
  for (i = 0; i < 3; i++)
    Module._setValue(v + i * 8, pos[i], 'double');
  Module._core_lookat(v, duration);
  Module._free(v);
}

/*
 * Function: pointAndLock
 * Move view direction to the given object and lock on it.
 *
 * Parameters:
 *   target   - The target object.
 *   duration - Movement duration in sec.
 */
Module['pointAndLock'] = function(target, duration) {
  if (duration === undefined)
    duration = 1.0;
  if (Module._apiActivity) Module._apiActivity();
  Module._core_point_and_lock(target.v, duration);
}

/*
 * Function: zoomTo
 * Change FOV to the passed value.
 *
 * Parameters:
 *   fov      - The target FOV diameter in rad.
 *   duration - Movement duration in sec.
 */
Module['zoomTo'] = function(fov, duration) {
  if (duration === undefined)
    duration = 1.0;
  if (Module._apiActivity) Module._apiActivity();
  Module._core_zoomto(fov, duration);
}

/*
 * Function: otypeToStr
 * Get the name for an object's otype.
 *
 * Parameters:
 *   otype    - The input 1-4 chars otype code.
 *
 * Return:
 *   The english name for an otype.
 */
Module['otypeToStr'] = function(otype) {
  var otype_to_str = Module.cwrap('otype_to_str', 'number', ['string']);
  var cret = otype_to_str(otype);
  return Module.UTF8ToString(cret);
}

let onClickCallback;
let onClickFn;
let onRectCallback;
let onRectFn;
/*
 * Function: on
 * Allow to listen to events on the sky map
 *
 * For the moment we only support the 'click' and 'rect' event.
 */
Module['on'] = function(eventName, callback) {
  if (eventName === 'click') {
    if (!onClickFn) {
      onClickFn = Module.addFunction(function(x, y) {
        return onClickCallback({point: {x: x, y: y}});
      }, 'idd');
    }
    onClickCallback = callback;
    Module.core.on_click = onClickFn;
  }
  if (eventName === 'rectSelection') {
    // Register the trampoline once and only swap the callback, like the click
    // path above; re-adding it every call permanently leaks a function-table
    // slot.
    if (!onRectFn) {
      onRectFn = Module.addFunction(function(x1, y1, x2, y2) {
        return onRectCallback({rect: [{x: x1, y: y1}, {x: x2, y: y2}]});
      }, 'idddd');
    }
    onRectCallback = callback;
    Module.core.on_rect = onRectFn;
  }
}


/*
 * Function: setFont
 * Load a font from a url and add it into the engine.
 *
 * If we add several fonts to the same face ('regular' or 'bold'), the
 * former are used as fallback.
 *
 * Parameters:
 *   font   - One of 'regular' or 'bold'
 *   url    - Url to a ttf font.
 *
 * Return:
 *   A promise that can be used to be notified once the font has been loaded.
 */
Module['setFont'] = function(font, url) {
  // Helper function to add the internal fallback font.
  function addFallbackFont(fontName) {
    const fallbackUrl = (fontName === 'regular') ? 'asset://font/NotoSans-Regular.ttf' :
                                                   'asset://font/NotoSans-Bold.ttf';
    Module.ccall('core_add_font', null,
                 ['number', 'string', 'string', 'number', 'number'],
                 [0, fontName, fallbackUrl, 0, 0]);
  }

  return fetch(url).then(function(response) {
    if (!response.ok) throw new Error(`Cannot get ${url}`);
    return response.arrayBuffer();
  }).then(function(data) {
    data = new Uint8Array(data);
    let ptr = Module._malloc(data.length);
    Module.writeArrayToMemory(data, ptr);
    Module.ccall('core_add_font', null,
                 ['number', 'string', 'string', 'number', 'number'],
                 [0, font, null, ptr, data.length]);

    // Also add the internal fallback font.
    addFallbackFont(font);
  }).catch(function(err) {
    console.error(`Failed to load font ${font} from ${url}:`, err);
    // Still add the fallback font so at least basic text can be displayed.
    console.log(`Adding fallback font for ${font}`);
    addFallbackFont(font);
    // Re-throw the error so the caller can handle it if needed.
    throw err;
  });
}
