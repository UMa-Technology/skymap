// Engine glue for artificial satellites — the space stations (ISS + the Chinese
// Space Station / Tiangong). Cloned in structure from custom-horizon.js.
//
// Two jobs:
//   1. Load a build-day TLE baseline (bundled plain JSON) at startup so the
//      stations render immediately, fully offline, with no network.
//   2. Expose window.Satellites so the host can push fresh TLE at runtime. In
//      the embedded (Flutter) app the native layer owns the CelesTrak fetch,
//      throttling and last-good caching, and calls window.Satellites.setTLE().
//
// Refresh is applied IN PLACE via the engine's satellites_set_tle(norad,l1,l2)
// C function, which rewrites the existing satellite's SGP4 elset without
// changing its object pointer. A remove + re-add refresh would free an object
// the satellites module still references by raw pointer from its cross-frame
// render caches (visibles / render_current) -> use-after-free on the next
// frame, precisely during a visible pass. The baseline only CREATES missing
// stations (never overwrites), so a live push that arrives first is not clobbered
// by the slightly-older baseline.

// Only the two stations users care about: ISS + the Chinese Space Station
// (Tianhe core = the station). Any other NORAD (e.g. the docked Wentian/Mengtian
// modules, which overlap Tianhe and can't be individually picked) is ignored,
// even if the host pushes a wider list. Matches satellite_is_persistent in C.
const STATIONS = new Set([25544, 48274])

let stel = null
let mod = null

function ensureModule () {
  if (mod) return mod
  if (!stel) return null
  mod = (stel.core && stel.core.satellites) ||
        (stel.getModule && stel.getModule('satellites')) || null
  return mod
}

// A record is { model_data: { norad_number, tle: [l1, l2], mag }, names: [...] }.
// The engine's SGP4 parser reads fixed TLE columns, so a malformed/short line
// would read out of range — require the two standard 69-char lines up front.
function validRecord (rec) {
  if (!rec || !rec.model_data) return false
  const md = rec.model_data
  if (!Number.isFinite(md.norad_number)) return false
  if (!STATIONS.has(md.norad_number)) return false
  const tle = md.tle
  if (!Array.isArray(tle) || tle.length !== 2) return false
  const l1 = tle[0]
  const l2 = tle[1]
  if (typeof l1 !== 'string' || typeof l2 !== 'string') return false
  if (l1.length < 69 || l2.length < 69) return false
  return l1[0] === '1' && l2[0] === '2'
}

// Apply a batch of TLE records. The whole batch is validated first (never a
// half-apply). `overwrite` true (live refresh) rewrites an existing station's
// elements in place; false (baseline) only creates stations not already present.
function applyRecords (records, overwrite) {
  if (!ensureModule()) return 0
  if (!Array.isArray(records)) return 0
  const recs = records.filter(validRecord)
  if (recs.length === 0) return 0

  let applied = 0
  for (const rec of recs) {
    const norad = rec.model_data.norad_number
    const l1 = rec.model_data.tle[0]
    const l2 = rec.model_data.tle[1]

    if (overwrite && stel.ccall) {
      // In-place update of the existing station; 0 means it was found+updated.
      const r = stel.ccall('satellites_set_tle', 'number',
        ['number', 'string', 'string'], [norad, l1, l2])
      if (r === 0) { applied++; continue }
    } else {
      // Baseline: skip if this station already exists (a live push may have
      // created a fresher one). Number-based check via the engine, matching how
      // satellites_set_tle keys, so there is no NORAD-designation string mismatch.
      if (stel.ccall &&
          stel.ccall('satellites_has', 'number', ['number'], [norad])) {
        continue
      }
    }

    // Not present yet -> create + add. A pure add is always safe (unlike a
    // remove). Drop our JS handle so the module is the sole owner (create ref
    // 1, module_add retains -> 2, destroy -> 1).
    const obj = mod.add('tle_satellite', rec)
    if (obj && typeof obj.destroy === 'function') obj.destroy()
    applied++
  }
  return applied
}

// Host entry point: push fresh TLE for one or more stations (live refresh).
function setTLE (records) {
  try {
    return applyRecords(records, true)
  } catch (e) {
    console.warn('Satellites.setTLE failed', e)
    return 0
  }
}

// Kept for host-bridge API symmetry. Removing live satellites mid-render is
// unsafe (their pointers live in the module render caches) and the baseline is
// meant to persist, so this is intentionally a no-op.
function clear () {}

async function loadBaseline () {
  if (!ensureModule()) return
  try {
    const url = process.env.BASE_URL + 'skydata/tle_satellite_baseline.json'
    const resp = await fetch(url)
    if (!resp.ok) return
    applyRecords(await resp.json(), false)
  } catch (e) {
    // Only reached if the committed baseline is missing/corrupt; the stations
    // then simply don't show until a live push arrives.
    console.warn('satellite baseline load failed', e)
  }
}

// Called once from the engine onReady callback (sw_helpers.js), beside
// installCustomHorizon.
export function installSatellites (stelInstance) {
  stel = stelInstance
  ensureModule()
  if (typeof window !== 'undefined') {
    window.Satellites = { setTLE, clear }
  }
  loadBaseline()
}
