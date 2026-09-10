/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

Module.afterInit(function() {
  if (!Module.canvas) return;

  // XXX: remove this I guess.
  var mouseDown = false;
  var mouseButtons = 0;
  var mousePos;
  // Render-loop state. When the page is hidden (app backgrounded / covered) the
  // loop stops itself; the visibilitychange handler restarts it.
  var running = true;

  // Adaptive frame rate to cut CPU/GPU/heat (mobile overheating):
  //   - FPS_ACTIVE while the user interacts or the view moves >= 1px/frame
  //     (goto, flick, zoom, fast time-lapse).
  //   - FPS_ANIM while the engine reports animations (faders, eye adaptation,
  //     data still loading) — _core_update() returns nonzero then.
  //   - Otherwise the sky is static: render only when the accumulated
  //     on-screen change since the LAST RENDERED frame exceeds ~1 pixel
  //     (diurnal sky drift, or the camera tracking a locked target — which
  //     previously defeated the throttle entirely and kept 60fps forever),
  //     with a safety-net frame every STATIC_MAX_MS.
  // The rAF loop still ticks at display rate; we only skip the expensive
  // _core_update/_core_render on throttled frames.
  var FPS_ACTIVE = 60;       // cap while active (also tames 120Hz displays)
  var FPS_ANIM = 10;         // while engine-side animations are running
  var IDLE_AFTER_MS = 1000;  // stay at full rate this long after the last activity
  var STATIC_MAX_MS = 3000;  // static sky: at most this long between frames
  var DRIFT_PX = 1.0;        // re-render once this much motion accumulated
  var SIDEREAL_RAD_S = 7.292e-5;  // sky rotation rate (rad/s) at time_speed 1
  // Cap the internal render resolution. 2x is already retina-sharp, so on
  // DPR-3 phones we render at 2x and let the browser upscale to the 3x display:
  // visually ~lossless but ~2.25x fewer pixels to shade every frame (a big
  // GPU/fill-rate/heat saving). No effect at DPR <= 2 (retina Macs, most desktops).
  var MAX_DPR = 2;
  var now_ms = function() { return performance.now(); };
  var lastActivity = now_ms();   // start active so the intro zoom is smooth
  var lastFrameTime = 0;
  var engineAnimating = true;    // last _core_update() return; start true
  // Camera state at the last RENDERED frame (not last tick), so slow motion
  // accumulates until it becomes visible instead of being missed tick-by-tick.
  var refFov = -1, refYaw = 0, refPitch = 0;
  var winWidthCss = window.innerWidth || 800;
  var markActivity = function() { lastActivity = now_ms(); };
  // Expose to the API glue (obj.js/pre.js): any WASM mutation from the host
  // app (selection, goto, time set...) must wake the loop instantly — those
  // calls come from outside the DOM so no pointer/key event marks them.
  Module._apiActivity = markActivity;

  // Accumulated on-screen change since the last rendered frame, in pixels:
  // camera/zoom deltas plus predicted diurnal drift of the sky itself (the
  // stars move even when the camera is perfectly still).
  var motionPx = function(now) {
    try {
      // Use the observer wrapper cached once at init (pre.js) instead of
      // c.observer, which rebuilds a whole SweObj (foreach attr/child) every
      // call — this runs each rAF tick, including throttled idle frames.
      var c = Module.core, o = Module.observer;
      var fov = c.fov;
      var pxPerRad = winWidthCss / (fov > 0 ? fov : 1);
      var d = Math.abs(o.yaw - refYaw) * Math.cos(refPitch) +
              Math.abs(o.pitch - refPitch) +
              Math.abs(fov - refFov);
      var px = d * pxPerRad;
      px += (now - lastFrameTime) / 1000 *
            Math.abs(c.time_speed || 0) * SIDEREAL_RAD_S * pxPerRad;
      return px;
    } catch (e) { return DRIFT_PX + 1; }  // fail open: render
  };

  // Function called at each frame
  var render = function(timestamp) {
    var now = timestamp || now_ms();

    // Pick the frame budget for this tick (see the block comment above).
    var needed;
    if (mouseDown || (now - lastActivity < IDLE_AFTER_MS)) {
      needed = now - lastFrameTime >= 1000 / FPS_ACTIVE - 1;
    } else if (motionPx(now) >= DRIFT_PX) {
      // Visible motion accumulated: render now (still capped at FPS_ACTIVE).
      needed = now - lastFrameTime >= 1000 / FPS_ACTIVE - 1;
    } else if (engineAnimating) {
      needed = now - lastFrameTime >= 1000 / FPS_ANIM - 1;
    } else {
      needed = now - lastFrameTime >= STATIC_MAX_MS;
    }
    if (needed) {
      lastFrameTime = now;

      if (mouseDown)
        Module._core_on_mouse(0, 1, mousePos.x, mousePos.y, mouseButtons);

      // Check for canvas resize
      var canvas = Module.canvas;

      // Device pixel ratio, capped at MAX_DPR to bound the render resolution.
      var dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);

      // Get the size of the canvas in CSS pixels.
      var rect = canvas.getBoundingClientRect();

      var displayWidth  = rect.width;
      var displayHeight = rect.height;
      // Compare against the actual device-pixel backing-store size (rounded to
      // whole pixels), NOT the CSS-pixel layout size. Comparing canvas.width
      // (= displayWidth * dpr) to displayWidth would be true on every frame at
      // any dpr != 1, and re-assigning canvas.width/height reallocates+clears
      // the WebGL drawing buffer each frame — undoing the throttle/DPR savings.
      var bufWidth  = Math.round(displayWidth  * dpr);
      var bufHeight = Math.round(displayHeight * dpr);
      if (canvas.width !== bufWidth || canvas.height !== bufHeight) {
        canvas.width = bufWidth;
        canvas.height = bufHeight;
      }

      // TODO: manage paning and flicking here

      // core_update returns whether engine-side animations (faders, eye
      // adaptation, goto, loading) are still running — drives FPS_ANIM tier.
      engineAnimating = !!Module._core_update();
      Module._core_render(displayWidth, displayHeight, dpr);

      // Snapshot the camera state of this rendered frame; motionPx()
      // accumulates against it until the next render.
      winWidthCss = displayWidth || winWidthCss;
      try {
        refFov = Module.core.fov;
        refYaw = Module.observer.yaw;
        refPitch = Module.observer.pitch;
      } catch (e) {}
    }

    // Pause while the page is hidden: no point rendering frames nobody sees
    // (saves CPU/GPU/battery/heat when the app is backgrounded or covered).
    // Restarted by the visibilitychange handler.
    if (document.hidden) { running = false; return; }
    window.requestAnimationFrame(render)
  }

  var fixPageXY = function(e) {
    if (e.pageX == null && e.clientX != null ) {
      var html = document.documentElement
      var body = document.body
      e.pageX = e.clientX + (html.scrollLeft || body && body.scrollLeft || 0)
      e.pageX -= html.clientLeft || 0
      e.pageY = e.clientY + (html.scrollTop || body && body.scrollTop || 0)
      e.pageY -= html.clientTop || 0
    }
  };

  var setupMouse = function() {
    var canvas = Module.canvas;
    function getMousePos(evt) {
      var rect = canvas.getBoundingClientRect();
      return {
        x: evt.clientX - rect.left,
        y: evt.clientY - rect.top
      };
    }

    canvas.addEventListener('mousedown', function(e) {
      var that = this;
      e = e || event;
      fixPageXY(e);
      mouseDown = true;
      mousePos = getMousePos(e);
      mouseButtons = e.buttons;

      document.onmouseup = function(e) {
        e = e || event;
        fixPageXY(e);
        mouseDown = false;
        mousePos = getMousePos(e);
        Module._core_on_mouse(0, 0, mousePos.x, mousePos.y, mouseButtons);
      };
      document.onmouseleave = function(e) {
        mouseDown = false;
      };

      document.onmousemove = function(e) {
        e = e || event;
        fixPageXY(e);
        mousePos = getMousePos(e);
      }
    });

    canvas.addEventListener('touchstart', function(e) {
      var rect = canvas.getBoundingClientRect();
      for (var i = 0; i < e.changedTouches.length; i++) {
        var id = e.changedTouches[i].identifier;
        var relX = e.changedTouches[i].pageX - rect.left;
        var relY = e.changedTouches[i].pageY - rect.top;
        Module._core_on_mouse(id, 1, relX, relY, 1);
      }
    }, {passive: true});
    canvas.addEventListener('touchmove', function(e) {
      if (e.cancelable) {
        e.preventDefault();
      }
      var rect = canvas.getBoundingClientRect();
      for (var i = 0; i < e.changedTouches.length; i++) {
        var id = e.changedTouches[i].identifier;
        var relX = e.changedTouches[i].pageX - rect.left;
        var relY = e.changedTouches[i].pageY - rect.top;
        Module._core_on_mouse(id, -1, relX, relY, 1);
      }
    }, {passive: false});
    canvas.addEventListener('touchend', function(e) {
      var rect = canvas.getBoundingClientRect();
      for (var i = 0; i < e.changedTouches.length; i++) {
        var id = e.changedTouches[i].identifier;
        var relX = e.changedTouches[i].pageX - rect.left;
        var relY = e.changedTouches[i].pageY - rect.top;
        Module._core_on_mouse(id, 0, relX, relY, 1);
      }
    });

    // Handle touchcancel: iOS fires this instead of touchend when system
    // gestures (e.g. multitasking swipe) intercept touch events.
    // Without this, touch points remain "down" in the C gesture state machine,
    // causing it to get stuck and stop accepting new gestures.
    canvas.addEventListener('touchcancel', function(e) {
      var rect = canvas.getBoundingClientRect();
      for (var i = 0; i < e.changedTouches.length; i++) {
        var id = e.changedTouches[i].identifier;
        var relX = e.changedTouches[i].pageX - rect.left;
        var relY = e.changedTouches[i].pageY - rect.top;
        Module._core_on_mouse(id, 0, relX, relY, 1);
      }
    }); 

    // Fallback: when the page regains visibility (e.g. app returns from
    // background), force-release all touch points to recover from any
    // stuck gesture state that touchcancel might have missed.
    document.addEventListener('visibilitychange', function() {
      if (!document.hidden) {
        // buttons must be 1: movements_on_mouse ignores any event with
        // buttons != 1, so buttons=0 here would never clear the stuck touch.
        Module._core_on_mouse(0, 0, 0, 0, 1);
        Module._core_on_mouse(1, 0, 0, 0, 1);
        mouseDown = false;
        // Render at full rate briefly: the sky may have drifted while hidden.
        markActivity();
        // Restart the render loop if it paused itself while hidden.
        if (!running) { running = true; window.requestAnimationFrame(render); }
      }
    });

    function getMouseWheelDelta(event) {
      var delta = 0;
      switch (event.type) {
        case 'DOMMouseScroll':
          delta = -event.detail;
          break;
        case 'mousewheel':
          delta = event.wheelDelta / 120;
          break;
        default:
          throw 'unrecognized mouse wheel event: ' + event.type;
      }
      return delta;
    }

    var onWheelEvent = function(e) {
      e.preventDefault();
      fixPageXY(e);
      var pos = getMousePos(e);
      var zoom_factor = 1.05;
      var delta = getMouseWheelDelta(e) * 2;
      Module._core_on_zoom(Math.pow(zoom_factor, delta), pos.x, pos.y);
      return false;
    };
    canvas.addEventListener('mousewheel', onWheelEvent, {passive: false});
    canvas.addEventListener('DOMMouseScroll', onWheelEvent, {passive: false});

    canvas.oncontextmenu = function(e) {
      e.preventDefault();
      e.stopPropagation();
    }

  };

  setupMouse();

  // Any interaction anywhere (canvas gestures OR the surrounding Vue UI: toolbar,
  // search, dialogs) counts as activity and keeps the render loop at full frame
  // rate for IDLE_AFTER_MS, so UI-triggered changes/animations render smoothly.
  ['pointerdown', 'pointerup', 'pointermove', 'wheel', 'keydown',
   'touchstart', 'touchmove'].forEach(function(ev) {
    document.addEventListener(ev, markActivity, { passive: true, capture: true });
  });
  window.addEventListener('resize', markActivity, { passive: true });
  window.addEventListener('orientationchange', markActivity, { passive: true });

  // Handle WebGL context loss (common on iOS when GPU memory is under pressure).
  // When context is lost, all GL resources (shaders, textures, VBOs) become invalid.
  // The C/WASM layer caches GL handles that cannot be hot-restored, so we reload
  // the page when the context is restored to rebuild everything from scratch.
  var canvas = Module.canvas;
  canvas.addEventListener('webglcontextlost', function(e) {
    console.warn('[SWE] WebGL context lost');
    e.preventDefault(); // Allow the browser to attempt context restoration
  });
  canvas.addEventListener('webglcontextrestored', function() {
    console.warn('[SWE] WebGL context restored, reloading page...');
    location.reload();
  });

  // Kickoff rendering at max FPS, normally 60 FPS on a browser.
  window.requestAnimationFrame(render)
})
