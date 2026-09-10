// Engine glue for sky photos — overlaying a plate-solved astrophoto on the star
// map at its true J2000 position. Cloned in structure from satellites.js.
//
// The engine already ships a `photo` object (src/modules/photos.c): given a
// calibration { ra, dec, orientation, pixscale } it paints the image as a
// textured quad in FRAME_ICRF (≈ J2000). We added two properties there:
//   - opacity  : steady per-photo alpha in [0,1] (the built-in `visible` fader
//                is only on/off), for a transparency slider.
//   - flipped  : mirror parity (astrometry "flipped"), reflects the image X
//                axis + negates orientation so a flipped solve isn't mirrored.
//
// This module exposes window.SkyPhotos so the host (Flutter) can add / retune /
// remove overlays at runtime. The image is loaded by URL; the engine XHRs the
// bytes and decodes them (stb_image, so JPEG/PNG), which also works for local
// blob:/data: URLs — i.e. a camera photo needs no upload.

// Units on the public API: ra/dec/orientation in DEGREES, pixscale in ARCSEC
// per pixel (both match the plate-solve readout and photos.c's own conversion),
// opacity in [0,1].

const LAYER_ID = 'jsbridge-photos'

let stel = null
let layer = null
// id -> { obj, url, opacity }. We hold the create-time reference (obj) for each
// photo's lifetime so its opacity can be retuned; both references (ours + the
// layer's) are released in remove()/clear(). `opacity` mirrors the alpha
// currently painted on screen (updated on every fade frame), so any retune
// fades from what the user actually sees — never from 0, never from a stale
// target that an interrupted fade didn't reach.
const photos = new Map()

// id -> requestAnimationFrame handle of the in-flight opacity fade.
const fades = new Map()

const FADE_MS = 300

function cancelFade (id) {
  const pending = fades.get(id)
  if (pending != null) cancelAnimationFrame(pending)
  fades.delete(id)
}

// Fade a photo's steady alpha from its current displayed value to `target`.
// A retune arriving mid-fade restarts from wherever the fade got to.
function fadeOpacity (id, entry, target) {
  cancelFade(id)
  const from = entry.opacity
  const start = performance.now()
  const step = (now) => {
    const t = Math.min(1, (now - start) / FADE_MS)
    const value = from + (target - from) * t
    entry.opacity = value
    entry.obj.opacity = value
    if (t < 1) {
      fades.set(id, requestAnimationFrame(step))
    } else {
      fades.delete(id)
    }
  }
  fades.set(id, requestAnimationFrame(step))
}

function ensureLayer () {
  if (layer) return layer
  if (!stel) return null
  layer = stel.getObj(LAYER_ID) ||
          stel.createLayer({ id: LAYER_ID, z: 45, visible: true })
  layer.visible = true
  return layer
}

// Add (or replace) a photo overlay. Returns true on success.
//   { id, url, ra, dec, orientation, pixscale, flipped?, opacity? }
function add (opts) {
  try {
    if (!ensureLayer()) return false
    if (!opts || typeof opts.id !== 'string' || !opts.url) return false
    const pixscale = Number(opts.pixscale)
    if (!Number.isFinite(pixscale) || pixscale <= 0) {
      console.warn('SkyPhotos.add: pixscale must be > 0', opts)
      return false
    }

    const opacity = opts.opacity == null ? 1.0 : Math.max(0, Math.min(1, Number(opts.opacity)))

    // Same id + same url = an opacity retune (hosts re-send the full add payload
    // from their slider): keep the existing object and fade its alpha from the
    // currently displayed value to the new target. Recreating instead would
    // replay the engine's `visible` fade-in, flashing the photo from 0 on every
    // adjustment. The url doubles as a content key — a genuine replacement of
    // the same id arrives under a fresh url, so calibration never goes stale.
    const existing = photos.get(opts.id)
    if (existing && existing.url === opts.url) {
      fadeOpacity(opts.id, existing, opacity)
      return true
    }

    // Replace an existing id in place (avoids a duplicate stacked overlay and
    // the leaked object it would create).
    if (existing) remove(opts.id)

    // NOTE: photo_fn_calibration (photos.c) reads args->u.array.values[0], i.e.
    // it expects the calibration object wrapped in a single-element ARRAY, not a
    // bare object. url/flipped/opacity/visible take bare values as usual.
    const obj = stel.createObj('photo', {
      url: opts.url,
      calibration: [{
        ra: Number(opts.ra),
        dec: Number(opts.dec),
        orientation: Number(opts.orientation) || 0,
        pixscale: pixscale
      }],
      flipped: !!opts.flipped,
      opacity: opacity,
      visible: true
    })
    if (!obj) return false

    layer.add(obj)
    photos.set(opts.id, { obj, url: opts.url, opacity })
    return true
  } catch (e) {
    console.warn('SkyPhotos.add failed', e)
    return false
  }
}

// Live transparency control (0 = invisible, 1 = opaque). Fades from the
// currently displayed alpha — same animation as an add() retune.
function setOpacity (id, alpha) {
  const entry = photos.get(id)
  if (!entry) return false
  fadeOpacity(id, entry, Math.max(0, Math.min(1, Number(alpha))))
  return true
}

// On/off with the engine's fade animation (separate from opacity).
function setVisible (id, visible) {
  const entry = photos.get(id)
  if (!entry) return false
  entry.obj.visible = !!visible
  return true
}

function remove (id) {
  const entry = photos.get(id)
  if (!entry) return false
  cancelFade(id)
  photos.delete(id)
  try {
    if (layer) layer.remove(entry.obj)    // drop the layer's reference
    if (typeof entry.obj.destroy === 'function') entry.obj.destroy() // drop ours -> freed
  } catch (e) {
    console.warn('SkyPhotos.remove failed', e)
  }
  return true
}

function clear () {
  for (const id of Array.from(photos.keys())) remove(id)
}

// Called once from the engine onReady callback (sw_helpers.js), beside
// installSatellites.
export function installSkyPhotos (stelInstance) {
  stel = stelInstance
  if (typeof window !== 'undefined') {
    window.SkyPhotos = { add, setOpacity, setVisible, remove, clear }
  }
}
