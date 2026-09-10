// Pure geometry/interpolation for the custom horizon silhouette.
// No engine or DOM access — unit-testable in isolation.
// Coordinates are [az, alt] degrees. Used by custom-horizon.js to normalize a
// pushed profile and resample it to a uniform azimuth grid for the engine's
// `customhorizon` C module (which does the actual FOV-robust paint_quad fill).

// Euclidean modulus: result carries the divisor's sign, so azimuths wrap into
// [0, 360). Port of custom_horizion euclidianModulus().
export function euclideanModulus (x, y) {
  const r = x % y
  return r < 0 ? r + y : r
}

// Coerce array-of-pairs, array-of-objects, or {points:[...]} into {az,alt}[].
function toPoints (input) {
  if (!input) return []
  if (Array.isArray(input.points)) return toPoints(input.points)
  if (!Array.isArray(input)) return []
  return input.map((p) => Array.isArray(p)
    ? { az: p[0], alt: p[1] }
    : { az: p.az, alt: p.alt })
}

// Ensure both 0 and 360 keys exist. Port of CustomHorizon._groom.
function groom (map) {
  const has0 = map.has(0)
  const has360 = map.has(360)
  if (!has0 && !has360) {
    const keys = [...map.keys()]
    const nearest0 = keys.reduce((a, b) => Math.abs(a) < Math.abs(b) ? a : b)
    const nearest360 = keys.reduce((a, b) => Math.abs(a) > Math.abs(b) ? a : b)
    let key = nearest0
    if (360 - nearest360 < nearest0) key = nearest360
    const v = map.get(key)
    map.set(0, v)
    map.set(360, v)
  } else if (!has0 && has360) {
    map.set(0, map.get(360))
  } else if (has0 && !has360) {
    map.set(360, map.get(0))
  }
  // Due north is a single direction: force az=0 and az=360 equal so the
  // silhouette never tears there, even for a hand-edited profile whose two
  // endpoints disagree. (Deviates from the Dart _groom, which leaves an explicit
  // 0/360 mismatch untouched; matches the editor's north-twin sync + the spec's
  // north-continuity guarantee.)
  map.set(360, map.get(0))
}

// Normalize arbitrary input into a groomed, sorted profile: {az,alt}[] sorted
// ascending by az, duplicates removed (last wins), altitudes clamped to [0,90],
// with both az=0 and az=360 guaranteed present. Returns null if <2 points.
export function normalizeProfile (input) {
  const map = new Map()
  for (const p of toPoints(input)) {
    if (!Number.isFinite(p.az) || !Number.isFinite(p.alt)) continue
    // Keep az in [0,360] (0 and 360 preserved as distinct endpoints); wrap only
    // genuinely out-of-range azimuths so they map to a real direction instead of
    // becoming unreachable dead data.
    const az = (p.az < 0 || p.az > 360) ? euclideanModulus(p.az, 360) : p.az
    map.set(az, Math.min(90, Math.max(0, p.alt))) // last write wins (dedup)
  }
  if (map.size < 2) return null
  groom(map)
  return [...map.entries()]
    .map(([az, alt]) => ({ az, alt }))
    .sort((a, b) => a.az - b.az)
}

// Binary search for the segment [lo, lo+1] bracketing azimuth x (assumes the
// profile is sorted and x is strictly inside its azimuth range).
function bracketOf (profile, x) {
  let lo = 0
  let hi = profile.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (profile[mid].az <= x) lo = mid
    else hi = mid
  }
  return lo
}

// Linear-interpolated altitude for any azimuth. Input wrapped to [0,360);
// held flat beyond the first/last sample. Port of getAltitude/_interpolate1D.
export function altitudeAt (profile, az) {
  const x = euclideanModulus(az, 360)
  const n = profile.length
  if (x <= profile[0].az) return profile[0].alt
  if (x >= profile[n - 1].az) return profile[n - 1].alt
  const lo = bracketOf(profile, x)
  const hi = lo + 1
  const span = profile[hi].az - profile[lo].az
  if (span === 0) return profile[lo].alt
  const t = (x - profile[lo].az) / span
  return profile[lo].alt + t * (profile[hi].alt - profile[lo].alt)
}

const D2R = Math.PI / 180

// Unit direction for (az, alt) degrees: x=N, y=E, z=up (handedness is
// irrelevant here — only internal consistency matters).
function unitVec (azDeg, altDeg) {
  const ca = Math.cos(altDeg * D2R)
  return [ca * Math.cos(azDeg * D2R), ca * Math.sin(azDeg * D2R), Math.sin(altDeg * D2R)]
}

// Segments wider than this interpolate linearly in (az, alt) instead of along
// the great circle: over a wide gap the GC's azimuth sweep no longer matches
// the profile's (it can even dip below the horizon), while the 2D-chart-style
// linear ramp is what the sparse data actually means.
const GC_MAX_SPAN_DEG = 90

// The star map may deviate from the Flutter 2D chart's linear model by at most
// this much. Small enough to keep map/chart editing parity; large enough to
// cover the sag of every realistic ridge edge (a 50°-wide segment at alt
// 69–77° sags ~2.4°).
const GC_MAX_DEV_DEG = 3

// Altitude of the great circle through unit vectors a, b at azimuth `phi`
// (radians): intersect the GC plane with the vertical half-plane at phi.
// Returns null for degenerate geometry (coincident/antipodal endpoints, or
// phi on the GC's axis).
function gcPlaneAltitude (a, b, phi) {
  const gc = [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0]
  ]
  if (Math.hypot(gc[0], gc[1], gc[2]) < 1e-9) return null
  const m = [Math.sin(phi), -Math.cos(phi), 0] // vertical plane's normal
  let p = [
    gc[1] * m[2] - gc[2] * m[1],
    gc[2] * m[0] - gc[0] * m[2],
    gc[0] * m[1] - gc[1] * m[0]
  ]
  // Horizontal component along azimuth phi; flip p onto the requested
  // half-plane (the GC crosses each azimuth twice, at phi and phi+180°).
  let h = p[0] * Math.cos(phi) + p[1] * Math.sin(phi)
  if (h < 0) { p = [-p[0], -p[1], -p[2]]; h = -h }
  if (h < 1e-12 && Math.abs(p[2]) < 1e-12) return null
  return Math.atan2(p[2], h) / D2R
}

// Altitude at `az` interpolated along the GREAT CIRCLE between the two
// bracketing profile vertices. This is what "a straight ridge edge" means on
// the celestial sphere: a path linear in (az, alt) physically sags below the
// taut line near the zenith (azimuth lines converge there), which projects as
// a spurious concave dip in the star map at any FOV.
//
// The deviation from the linear (2D-chart) model is bounded: per segment, the
// GC correction is scaled down so it never exceeds GC_MAX_DEV_DEG anywhere.
// Realistic ridge edges deviate less than that and render fully taut, while
// pathological segments (near-vertical cliffs, sparse wide-and-high spans,
// a clamped alt-90 vertex) stay within GC_MAX_DEV_DEG of the chart the user
// actually drew instead of diverging by tens of degrees. Spans wider than
// GC_MAX_SPAN_DEG and degenerate geometry fall back to linear entirely.
export function altitudeAtGreatCircle (profile, az) {
  const x = euclideanModulus(az, 360)
  const n = profile.length
  if (x <= profile[0].az) return profile[0].alt
  if (x >= profile[n - 1].az) return profile[n - 1].alt
  const lo = bracketOf(profile, x)
  const A = profile[lo]
  const B = profile[lo + 1]
  const span = B.az - A.az
  if (span === 0) return A.alt
  const linear = A.alt + (x - A.az) / span * (B.alt - A.alt)
  if (span > GC_MAX_SPAN_DEG) return linear
  const a = unitVec(A.az, A.alt)
  const b = unitVec(B.az, B.alt)
  const raw = gcPlaneAltitude(a, b, x * D2R)
  if (raw === null) return linear
  // Segment-wide max |GC - linear|, from fixed samples (so the scale is
  // near-constant across the segment — no wiggle) plus the query point itself
  // (so the bound is airtight, and still continuous in x).
  let devMax = Math.abs(raw - linear)
  for (let k = 1; k < 8; k++) {
    const s = A.az + span * k / 8
    const g = gcPlaneAltitude(a, b, s * D2R)
    if (g === null) continue
    devMax = Math.max(devMax, Math.abs(g - (A.alt + (B.alt - A.alt) * k / 8)))
  }
  const scale = devMax > GC_MAX_DEV_DEG ? GC_MAX_DEV_DEG / devMax : 1
  return Math.min(90, Math.max(0, linear + (raw - linear) * scale))
}

// Circular Gaussian smoothing of a uniform-azimuth sample array (indices wrap
// at the 0/360 seam). Rounds the sharp corners of a piecewise-linear ridge for
// a softer silhouette. `sigma` is in samples; sigma <= 0 is a no-op copy.
export function smoothCircular (values, sigma) {
  const n = values.length
  if (!(sigma > 0) || n < 3) return values.slice()
  const radius = Math.max(1, Math.ceil(sigma * 3))
  const kernel = []
  let sum = 0
  for (let k = -radius; k <= radius; k++) {
    const w = Math.exp(-(k * k) / (2 * sigma * sigma))
    kernel.push(w)
    sum += w
  }
  const out = new Array(n)
  for (let i = 0; i < n; i++) {
    let acc = 0
    for (let k = -radius; k <= radius; k++) {
      acc += values[(((i + k) % n) + n) % n] * kernel[k + radius]
    }
    out[i] = acc / sum
  }
  return out
}

// Altitude-adaptive circular Gaussian smoothing: the kernel width at each
// sample is chosen by sigmaOfValue(value[i]) (in samples). Used to round
// low-altitude corners (valleys) hard while keeping high, near-zenith peaks
// sharp — a uniform width either under-rounds valleys or flattens a high apex
// enough that it projects as a spurious double-bump near the zenith.
// sigmaOfValue <= 0 leaves that sample untouched.
export function smoothAdaptiveCircular (values, sigmaOfValue) {
  const n = values.length
  if (n < 3) return values.slice()
  const out = new Array(n)
  for (let i = 0; i < n; i++) {
    const sigma = sigmaOfValue(values[i])
    if (!(sigma > 0)) { out[i] = values[i]; continue }
    const radius = Math.max(1, Math.ceil(sigma * 3))
    let acc = 0
    let sum = 0
    for (let k = -radius; k <= radius; k++) {
      const w = Math.exp(-(k * k) / (2 * sigma * sigma))
      acc += values[(((i + k) % n) + n) % n] * w
      sum += w
    }
    out[i] = acc / sum
  }
  return out
}

// Densely sample the profile from 0..360 inclusive at ~stepDeg spacing.
export function sampleProfile (profile, stepDeg) {
  // Floor the step so a non-positive value can't divide to Infinity and hang.
  const steps = Math.max(2, Math.ceil(360 / Math.max(0.1, stepDeg)))
  const out = []
  for (let i = 0; i <= steps; i++) {
    const az = (i * 360) / steps
    out.push({ az, alt: altitudeAt(profile, az) })
  }
  return out
}
