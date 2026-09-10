// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { app } from '@/app'
import set from 'lodash/set'
import StelWebEngine from '@/assets/js/stellarium-web-engine.js'
import Moment from 'moment'
import { installCustomHorizon } from './custom-horizon.js'
import { installSatellites } from './satellites.js'
import { installSkyPhotos } from './sky-photos.js'
import { installSkyAr } from './sky-ar.js'

var DDDate = Date
DDDate.prototype.getJD = function () {
  return (this.getTime() / 86400000) + 2440587.5
}

DDDate.prototype.setJD = function (jd) {
  this.setTime((jd - 2440587.5) * 86400000)
}

DDDate.prototype.getMJD = function () {
  return this.getJD() - 2400000.5
}

DDDate.prototype.setMJD = function (mjd) {
  this.setJD(mjd + 2400000.5)
}

// --- Sky-text i18n (Task #5) -----------------------------------------------
// The engine translates every sky label per-frame via sys_translate("sky", ..),
// which calls translateFn below. We look the source string up in the catalog for
// the active language (fetched on demand); a miss returns the English source, so
// untranslated names fall back automatically. Because translation is applied
// every frame, switching language = swap skyCatalog + let the render loop repaint
// (the engine's malloc cache is keyed by the *output* string, so it stays correct
// across switches with no invalidation).
let skyCatalog = {}
let stelInstance = null
let skyHintsLayer = null            // engine layer for the circumpolar mask (module-scope read)
const skyCatalogCache = {}          // lang -> catalog object (memoized fetch)
// No per-language font loading here anymore: App.vue loads the merged
// SkyFont-Regular/Bold (latin + CJK + Hangul, tools/make-app-fonts.py) once.

// --- Host-facing initialization readiness contract -----------------------
// Created synchronously at module load (this file is imported before the
// engine boots) so a host injecting JS — or the native bridge — can grab
// window.__stelReady the instant the page exists, with no polling race.
// Phases advance: 'booting' (wasm downloading / instantiating) -> 'engineReady'
// (window.$stel usable, safe to push observer / language) -> 'firstFrame' (the
// sky's first frame is painted, safe to reveal the WebView — no black flash).
// window.__stelReady resolves with the engine instance at 'firstFrame'. The
// postMessage half of the contract is emitted by App.vue (embedded frontend).
// See dev_docs/app-embedding-handoff.md §2.9.
let _resolveStelReady = null
const _stelReadyPromise = (typeof window !== 'undefined')
  ? new Promise(function (res) { _resolveStelReady = res })
  : Promise.resolve()
if (typeof window !== 'undefined') {
  window.__stelReady = _stelReadyPromise
  window.StellariumReady = false
  window.StellariumInitPhase = 'booting'
}

const swh = {
  // Advance the host-facing init phase (see the readiness contract above).
  // Updates the window flags and, at 'firstFrame', resolves window.__stelReady.
  // Idempotent per phase. Safe to call in both frontends (no-op when there is
  // no window, e.g. SSR/tests).
  notifyInitPhase: function (phase) {
    if (typeof window === 'undefined') return
    window.StellariumInitPhase = phase
    if (phase === 'firstFrame') {
      window.StellariumReady = true
      if (_resolveStelReady) {
        _resolveStelReady(stelInstance)
        _resolveStelReady = null
      }
    }
  },

  initStelWebEngine: function (store, wasmFile, canvasElem, callBackOnDone) {
    StelWebEngine({
      wasmFile: wasmFile,
      canvas: canvasElem,
      // Keep the console clean: drop known-benign engine chatter that reaches
      // JS via emscripten's stdout (Module.print). Anything not matched still
      // prints, and real errors go through printErr (console.error) which we
      // leave untouched. Add patterns here to silence more noise.
      print: function (text) {
        if (/Parsed \d+ asteroids/.test(text)) return
        if (/Parsed \d+ comets/.test(text)) return
        if (/comets data seems outdated/.test(text)) return
        if (/Unmatched star designation/.test(text)) return
        console.log(text)
      },
      translateFn: function (domain, str) {
        return skyCatalog[str] || str
      },
      onReady: function (lstel) {
        stelInstance = lstel
        // Integration point for the host app; also exposed for dev/preview.
        if (typeof window !== 'undefined') {
          window.__setSkyLanguage = swh.setSkyLanguage
          // Dev/console convenience: tune star rendering live, e.g.
          // $stel.core.star_glow_scale = 0.1
          window.$stel = lstel
        }
        // Engine is up: window.$stel is usable, so it is now safe for the host
        // to push observer location / time / language. First frame (WebView
        // reveal) is signalled later by App.vue. (§2.9 readiness contract.)
        swh.notifyInitPhase('engineReady')
        store.commit('replaceStelWebEngine', lstel.getTree())
        lstel.onValueChanged(function (path, value) {
          const tree = store.state.stel
          set(tree, path, value)
          store.commit('replaceStelWebEngine', tree)
        })
        const gp = app.config.globalProperties
        gp.$stel = lstel
        gp.$selectionLayer = lstel.createLayer({ id: 'slayer', z: 50, visible: true })
        gp.$observingLayer = lstel.createLayer({ id: 'obslayer', z: 40, visible: true })
        skyHintsLayer = lstel.createLayer({ id: 'skyhintslayer', z: 38, visible: true })
        gp.$skyHintsLayer = skyHintsLayer
        installCustomHorizon(lstel)
        installSatellites(lstel)
        installSkyPhotos(lstel)
        installSkyAr(lstel)
        callBackOnDone()
      }
    })
  },

  // Set the language for sky-map text (constellation / star / DSO / planet
  // names). Loads the catalog on demand; the running render loop repaints
  // with the new labels within a frame. This is the call the host app wires
  // to its language UI. (Fonts cover every script already — see above.)
  // Returns a promise that resolves once the catalog is applied.
  setSkyLanguage: function (lang) {
    lang = (lang || 'en').toLowerCase()
    const base = process.env.BASE_URL
    // Apply AFTER skyCatalog is in place: sys_set_lang tells the engine its
    // language (it gates constellation labels on this — native Latin for
    // en/pt/es, translated otherwise — and uses it for CJK letter-spacing;
    // without it sys_get_lang() stays "en") and clears the engine's translation
    // cache. If we called it before the catalog arrived, the cache would
    // repopulate with the OLD catalog and only a second switch would take. We
    // also poke the render loop so the on-demand renderer repaints with the new
    // labels immediately instead of waiting for the next idle safety frame.
    const apply = function () {
      if (!stelInstance) return
      stelInstance.ccall('sys_set_lang', null, ['string'], [lang])
      if (stelInstance._apiActivity) stelInstance._apiActivity()
    }
    if (lang === 'en') { skyCatalog = {}; apply(); return Promise.resolve() }
    if (skyCatalogCache[lang]) { skyCatalog = skyCatalogCache[lang]; apply(); return Promise.resolve() }
    return fetch(base + 'skydata/sky-i18n/' + lang + '.json')
      .then(function (r) { if (!r.ok) throw new Error('no catalog: ' + lang); return r.json() })
      .then(function (cat) { skyCatalogCache[lang] = cat; skyCatalog = cat; apply() })
      .catch(function (e) { console.warn('[sky-i18n]', lang, e.message); skyCatalog = {}; apply() })
  },

  monthNames: ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ],

  astroConstants: {
    // Light time for 1 au in s
    ERFA_AULT: 499.004782,
    // Seconds per day
    ERFA_DAYSEC: 86400.0,
    // Days per Julian year
    ERFA_DJY: 365.25,
    // Astronomical unit in m
    ERFA_DAU: 149597870000
  },

  iconForSkySourceTypes: function (skySourceTypes) {
    // Array sorted by specificity, i.e. the most generic names at the end
    const iconForType = {
      // Stars
      'Pec?': 'star',
      '**?': 'double_star',
      '**': 'double_star',
      'V*': 'variable_star',
      'V*?': 'variable_star',
      '*': 'star',

      // Candidates
      'As?': 'group_of_stars',
      'SC?': 'group_of_galaxies',
      'Gr?': 'group_of_galaxies',
      'C?G': 'group_of_galaxies',
      'G?': 'galaxy',

      // Multiple objects
      reg: 'region_defined_in_the_sky',
      SCG: 'group_of_galaxies',
      ClG: 'group_of_galaxies',
      GrG: 'group_of_galaxies',
      IG: 'interacting_galaxy',
      PaG: 'pair_of_galaxies',
      'C?*': 'open_galactic_cluster',
      'Gl?': 'globular_cluster',
      GlC: 'globular_cluster',
      OpC: 'open_galactic_cluster',
      'Cl*': 'open_galactic_cluster',
      'As*': 'group_of_stars',
      mul: 'multiple_objects',

      // Interstellar matter
      'PN?': 'planetary_nebula',
      PN: 'planetary_nebula',
      SNR: 'planetary_nebula',
      'SR?': 'planetary_nebula',
      ISM: 'interstellar_matter',

      // Galaxies
      PoG: 'part_of_galaxy',
      QSO: 'quasar',
      G: 'galaxy',

      dso: 'deep_sky',

      // Solar System
      Asa: 'artificial_satellite',
      Moo: 'moon',
      Sun: 'sun',
      Pla: 'planet',
      DPl: 'planet',
      Com: 'comet',
      MPl: 'minor_planet',
      SSO: 'minor_planet',

      Con: 'constellation'
    }
    for (const i in skySourceTypes) {
      if (skySourceTypes[i] in iconForType) {
        return process.env.BASE_URL + 'images/svg/target_types/' + iconForType[skySourceTypes[i]] + '.svg'
      }
    }
    return process.env.BASE_URL + 'images/svg/target_types/unknown.svg'
  },

  iconForSkySource: function (skySource) {
    return swh.iconForSkySourceTypes(skySource.types)
  },

  iconForObservation: function (obs) {
    if (obs && obs.target) {
      return this.iconForSkySource(obs.target)
    } else {
      return this.iconForSkySourceTypes(['reg'])
    }
  },

  cleanupOneSkySourceName: function (name, flags) {
    flags = flags || 4
    return stelInstance.designationCleanup(name, flags)
  },

  nameForSkySource: function (skySource) {
    if (!skySource || !skySource.names) {
      return '?'
    }
    return this.cleanupOneSkySourceName(skySource.names[0])
  },

  culturalNameToList: function (cn) {
    const res = []

    const formatNative = function (_cn) {
      if (cn.name_native && cn.name_pronounce) {
        return cn.name_native + ', <i>' + cn.name_pronounce + '</i>'
      }
      if (cn.name_native) {
        return cn.name_native
      }
      if (cn.name_pronounce) {
        return cn.name_pronounce
      }
    }

    const nativeName = formatNative(cn)
    if (cn.user_prefer_native && nativeName) {
      res.push(nativeName)
    }
    if (cn.name_translated) {
      res.push(cn.name_translated)
    }
    if (!cn.user_prefer_native && nativeName) {
      res.push(nativeName)
    }
    return res
  },

  namesForSkySource: function (ss, flags) {
    // Return a list of cleaned up names
    if (!ss || !ss.names) {
      return []
    }
    if (!flags) flags = 10
    let res = []
    if (ss.culturalNames) {
      for (const i in ss.culturalNames) {
        res = res.concat(this.culturalNameToList(ss.culturalNames[i]))
      }
    }
    res = res.concat(ss.names.map(n => stelInstance.designationCleanup(n, flags)))
    // Remove duplicates, this can happen between * and V* catalogs
    res = res.filter(function (v, i) { return res.indexOf(v) === i })
    res = res.filter(function (v, i) { return !v.startsWith('CON ') })
    return res
  },

  nameForSkySourceType: function (otype) {
    const $stel = stelInstance
    const res = $stel.otypeToStr(otype)
    return res || 'Unknown Type'
  },

  nameForGalaxyMorpho: function (morpho) {
    const galTab = {
      E: 'Elliptical',
      SB: 'Barred Spiral',
      SAB: 'Intermediate Spiral',
      SA: 'Spiral',
      S0: 'Lenticular',
      S: 'Spiral',
      Im: 'Irregular',
      dSph: 'Dwarf Spheroidal',
      dE: 'Dwarf Elliptical'
    }
    for (const morp in galTab) {
      if (morpho.startsWith(morp)) {
        return galTab[morp]
      }
    }
    return ''
  },

  // Return a SweObj matching a passed sky source JSON object if it's already instanciated in SWE
  skySource2SweObj: function (ss) {
    if (!ss || !ss.model) {
      return undefined
    }
    const $stel = stelInstance
    let obj
    if (ss.model === 'tle_satellite') {
      const id = 'NORAD ' + ss.model_data.norad_number
      obj = $stel.getObj(id)
    } else if (ss.model === 'constellation' && ss.model_data.iau_abbreviation) {
      const id = 'CON western ' + ss.model_data.iau_abbreviation
      obj = $stel.getObj(id)
    }
    if (!obj) {
      obj = $stel.getObj(ss.names[0])
    }
    if (!obj && ss.names[0].startsWith('Gaia DR2 ')) {
      const gname = ss.names[0].replace(/^Gaia DR2 /, 'GAIA ')
      obj = $stel.getObj(gname)
    }
    if (obj === null) return undefined
    return obj
  },

  // Offline-only build: name search is a no-op (no online skysource API).
  // Kept so <skysource-search> resolves cleanly; object selection resolves
  // from local engine data via sweObj2SkySource below.
  querySkySources: function () {
    return Promise.resolve([])
  },

  sweObj2SkySource: function (obj) {
    // Offline-only build: build the SkySource straight from local engine data.
    // No NoctuaSky network lookup.
    const ss = obj.jsonData
    if (!ss.model_data) {
      ss.model_data = {}
    }
    // Names fixup
    for (const i in ss.names) {
      if (ss.names[i].startsWith('GAIA')) {
        ss.names[i] = ss.names[i].replace(/^GAIA /, 'Gaia DR2 ')
      }
    }
    ss.culturalNames = obj.culturalDesignations()
    return Promise.resolve(ss)
  },

  // lock=false 时只转向不选中（App 桥的 goto 语义，见 jsbridge.vue）
  setSweObjAsSelection: function (obj, lock = true) {
    const $stel = stelInstance
    if (lock) {
      $stel.core.selection = obj
    }
    $stel.pointAndLock(obj)
  },

  delay: function (t, v) {
    return new Promise(function (resolve) {
      setTimeout(resolve.bind(null, v), t)
    })
  },

  geoCodePosition: function (pos, ctx) {
    // Offline build: no external reverse-geocoder (was
    // nominatim.openstreetmap.org). Label the position by its coordinates only.
    const ll = ctx.$t('Lat {0}° Lon {1}°', [pos.lat.toFixed(3), pos.lng.toFixed(3)])
    const loc = {
      short_name: pos.accuracy > 500 ? ctx.$t('Near {0}', [ll]) : ll,
      country: 'Unknown',
      lng: pos.lng,
      lat: pos.lat,
      alt: pos.alt ? pos.alt : 0,
      accuracy: pos.accuracy,
      street_address: ''
    }
    return Promise.resolve(loc)
  },

  getDistanceFromLatLonInM: function (lat1, lon1, lat2, lon2) {
    var deg2rad = function (deg) {
      return deg * (Math.PI / 180)
    }
    var R = 6371000 // Radius of the earth in m
    var dLat = deg2rad(lat2 - lat1)
    var dLon = deg2rad(lon2 - lon1)
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2)
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
    var d = R * c // Distance in m
    return d
  },

  // Look for the next time starting from now on when the night Sky is visible
  // i.e. when sun is more than 10 degree below horizon.
  // If no such time was found (e.g. in a northern country in summer),
  // we default to current time.
  getTimeAfterSunset: function (stel) {
    const sun = stel.getObj('NAME Sun')
    const obs = stel.observer.clone()
    const utc = Math.floor(obs.utc * 24 * 60 / 5) / (24 * 60 / 5)
    let i
    for (i = 0; i < 24 * 60 / 5 + 1; i++) {
      obs.utc = utc + 1.0 / (24 * 60) * (i * 5)
      const sunRadec = sun.getInfo('RADEC', obs)
      const azalt = stel.convertFrame(obs, 'ICRF', 'OBSERVED', sunRadec)
      const alt = stel.anpm(stel.c2s(azalt)[1])
      if (alt < -13 * Math.PI / 180) {
        break
      }
    }
    if (i === 0 || i === 24 * 60 / 5 + 1) {
      return stel.observer.utc
    }
    return obs.utc
  },

  // Get the list of circumpolar stars in a given magnitude range
  //
  // Arguments:
  //   obs      - An observer.
  //   maxMag   - The maximum magnitude above which objects are discarded.
  //   filter   - a function called for each object returning false if the
  //              object must be filtered out.
  //
  // Return:
  //   An array SweObject. It is the responsibility of the caller to properly
  //   destroy all the objects of the list when they are not needed, by calling
  //   obj.destroy() on each of them.
  //
  // Example code:
  //   // Return all cicumpolar stars between mag -2 and 4
  //   let res = swh.getCircumpolarStars(this.$stel.observer, -2, 4)
  //   // Do something with the stars
  //   console.log(res.length)
  //   // Destroy the objects (don't forget this line!)
  //   res.map(e => e.destroy())
  getCircumpolarStars: function (obs, minMag, maxMag) {
    const $stel = stelInstance
    const filter = function (obj) {
      if (obj.getInfo('vmag', obs) <= minMag) {
        return false
      }
      const posJNOW = $stel.convertFrame(obs, 'ICRF', 'JNOW', obj.getInfo('radec'))
      const radecJNOW = $stel.c2s(posJNOW)
      const decJNOW = $stel.anpm(radecJNOW[1])
      if (obs.latitude >= 0) {
        return decJNOW >= Math.PI / 2 - obs.latitude
      } else {
        return decJNOW <= -Math.PI / 2 + obs.latitude
      }
    }
    return $stel.core.stars.listObjs(obs, maxMag, filter)
  },

  circumpolarMask: undefined,
  showCircumpolarMask: function (obs, show) {
    if (show === undefined) {
      show = true
    }
    const layer = skyHintsLayer
    const $stel = stelInstance
    if (this.circumpolarMask) {
      layer.remove(this.circumpolarMask)
      this.circumpolarMask = undefined
    }
    if (show) {
      const diam = 2.0 * Math.PI - Math.abs(obs.latitude) * 2
      const shapeParams = {
        pos: [0, 0, obs.latitude > 0 ? -1 : 1, 0],
        frame: $stel.FRAME_JNOW,
        size: [diam, diam],
        color: [0.1, 0.1, 0.1, 0.8],
        border_color: [0.1, 0.1, 0.6, 1]
      }
      this.circumpolarMask = layer.add('circle', shapeParams)
    }
  }
}

export default swh
