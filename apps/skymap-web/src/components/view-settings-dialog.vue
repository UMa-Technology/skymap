// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
<!-- Rendered as the content of a floating v-menu anchored to the toolbar gear
     button (a popover, not a fullscreen modal). -->
<v-card class="bg-secondary text-white settings-card" width="260" style="border-radius: 28px;">
  <v-card-text>
    <v-text-field :model-value="lat" @change="e => setLatLon(e.target.value, null)" label="Lat" suffix="°" type="number"
      density="compact" variant="outlined" hide-details class="mb-3"></v-text-field>
    <v-text-field :model-value="lng" @change="e => setLatLon(null, e.target.value)" label="Lon" suffix="°" type="number"
      density="compact" variant="outlined" hide-details class="mb-2"></v-text-field>
    <v-checkbox hide-details :label="$t('Stars')" v-model="starsOn"></v-checkbox>
    <v-checkbox hide-details :label="$t('Space stations')" v-model="satellitesOn"></v-checkbox>
    <v-checkbox hide-details :label="$t('Milky Way')" v-model="milkyWayOn"></v-checkbox>
    <!-- These dense deep-sky catalogs are shown one at a time as an overlay:
         picking one hides every other object type (incl. NGC/IC/M) and shows
         only that catalog; the default (None) shows none of them. -->
    <v-select :items="dsoCatalogItems" v-model="dsoCatalog" :label="$t('Catalog')"
      :menu-props="{ contentClass: 'catalog-menu' }"
      density="compact" variant="outlined" hide-details class="my-2"></v-select>
    <v-checkbox hide-details :label="$t('DSS')" v-model="dssOn"></v-checkbox>
    <!-- Hα narrow-band survey overlay: independent of DSS (both can be on), with
         a deep-red / neutral-grey colour mode. Colour select only shown when on. -->
    <v-checkbox hide-details :label="$t('Hα')" v-model="halphaOn"></v-checkbox>
    <v-select v-if="halphaOn" :items="halphaColorItems" v-model="halphaColor" :label="$t('Hα Color')"
      density="compact" variant="outlined" hide-details class="my-2"></v-select>
    <v-checkbox hide-details :label="$t('Meridian Line')" v-model="meridianOn"></v-checkbox>
    <v-checkbox hide-details :label="$t('Ecliptic Line')" v-model="eclipticOn"></v-checkbox>
    <v-checkbox hide-details :label="$t('Equator Line')" v-model="equatorLineOn"></v-checkbox>
    <v-checkbox hide-details :label="$t('Equatorial Grid J2000')" v-model="equatorialGridJ2000On"></v-checkbox>
  </v-card-text>
</v-card>
</template>

<script>

export default {
  data: function () {
    return {
    }
  },
  computed: {
    dssOn: {
      get: function () {
        return this.$store.state.stel.dss.visible
      },
      set: function (newValue) {
        this.$stel.core.dss.visible = newValue
      }
    },
    // Hα narrow-band overlay: on/off plus a red/neutral colour mode. The engine
    // module (core.halpha) exposes `visible` and `red`; both mirror into the
    // stel tree like every other module.
    halphaOn: {
      get: function () {
        return this.$store.state.stel.halpha.visible
      },
      set: function (newValue) {
        this.$stel.core.halpha.visible = newValue
      }
    },
    halphaColorItems: function () {
      return [
        { title: this.$t('Red'), value: true },
        { title: this.$t('Neutral'), value: false }
      ]
    },
    halphaColor: {
      get: function () {
        return this.$store.state.stel.halpha.red
      },
      set: function (newValue) {
        this.$stel.core.halpha.red = newValue
      }
    },
    starsOn: {
      get: function () {
        return this.$store.state.stel.stars.visible
      },
      set: function (newValue) {
        this.$stel.core.stars.visible = newValue
      }
    },
    // Space stations (ISS + CSS/Tiangong). The satellites node may be absent for
    // the first frame before getTree() populates it, so guard the getter.
    satellitesOn: {
      get: function () {
        const s = this.$store.state.stel.satellites
        return s ? s.visible : false
      },
      set: function (newValue) {
        this.$stel.core.satellites.visible = newValue
        this.$stel.core.satellites.hints_visible = newValue
      }
    },
    milkyWayOn: {
      get: function () {
        return this.$store.state.stel.milkyway.visible
      },
      set: function (newValue) {
        this.$stel.core.milkyway.visible = newValue
      }
    },
    // Dense per-catalog overlays (LDN/LBN/SH2/PK/ACO/B). The engine keeps one
    // boolean per catalog, but the UI exposes them as a single-select dropdown
    // so at most one is ever active: picking one clears the rest. Default (None)
    // -> all off, so none of these clutter the default view.
    dsoCatalogItems: function () {
      return [
        { title: this.$t('None'), value: null },
        { title: 'LDN', value: 'dark_nebulae' },
        { title: 'LBN', value: 'lbn' },
        { title: 'SH2', value: 'sh2' },
        { title: 'PK', value: 'pk' },
        { title: 'ACO', value: 'aco' },
        { title: 'B', value: 'barnard' },
        { title: this.$t('Comets'), value: 'comets' }
      ]
    },
    dsoCatalog: {
      get: function () {
        const d = this.$store.state.stel.dsos
        for (const key of ['dark_nebulae', 'lbn', 'sh2', 'pk', 'aco', 'barnard']) {
          if (d[key]) return key
        }
        // Comets live in their own engine module, not under dsos, but the UI
        // treats them as one more single-select catalog overlay.
        if (this.$store.state.stel.comets && this.$store.state.stel.comets.visible) return 'comets'
        return null
      },
      set: function (newValue) {
        const dsos = this.$stel.core.dsos
        for (const key of ['dark_nebulae', 'lbn', 'sh2', 'pk', 'aco', 'barnard']) {
          dsos[key] = (key === newValue)
        }
        this.$stel.core.comets.visible = (newValue === 'comets')
        // Comets are almost all fainter than the default gates (points show
        // at stars_limit+2, labels at hints_limit+2; even a bright mag-7
        // comet gets a dot but no label at wide zoom). While the catalog is
        // selected, open both gates — same "you picked it, show it" boost
        // idea as the focused DSO catalogs. Tune live via
        // $stel.core.comets.hints_mag_offset.
        this.$stel.core.comets.hints_mag_offset = (newValue === 'comets') ? 8 : 0
        // "Only the picked catalog shows": for the dsos-class catalogs the
        // ENGINE hides the normal DSOs (any_special in dso.c); comets are a
        // separate module, so mirror that by switching the DSO layer off
        // while Comets is picked. The bottom-bar DSO button reflects (and
        // can override) this.
        this.$stel.core.dsos.visible = (newValue !== 'comets')
      }
    },
    meridianOn: {
      get: function () {
        return this.$store.state.stel.lines.meridian.visible
      },
      set: function (newValue) {
        this.$stel.core.lines.meridian.visible = newValue
      }
    },
    eclipticOn: {
      get: function () {
        return this.$store.state.stel.lines.ecliptic.visible
      },
      set: function (newValue) {
        this.$stel.core.lines.ecliptic.visible = newValue
      }
    },
    equatorLineOn: {
      get: function () {
        return this.$store.state.stel.lines.equator_line.visible
      },
      set: function (newValue) {
        this.$stel.core.lines.equator_line.visible = newValue
      }
    },
    equatorialGridJ2000On: {
      get: function () {
        return this.$store.state.stel.lines.equatorial.visible
      },
      set: function (newValue) {
        this.$stel.core.lines.equatorial.visible = newValue
      }
    },
    lat: function () {
      const l = this.$store.state.currentLocation
      return l && l.lat != null ? Number(Number(l.lat).toFixed(4)) : 0
    },
    lng: function () {
      const l = this.$store.state.currentLocation
      return l && l.lng != null ? Number(Number(l.lng).toFixed(4)) : 0
    }
  },
  methods: {
    // Lat/lon inputs set the observer location; committing currentLocation
    // triggers App.vue's watcher -> engine observer.
    setLatLon: function (lat, lng) {
      const cur = this.$store.state.currentLocation || {}
      const num = (v, fallback) =>
        (v !== null && v !== '' && !isNaN(Number(v))) ? Number(v) : fallback
      this.$store.commit('setCurrentLocation', {
        ...cur,
        lat: num(lat, cur.lat || 0),
        lng: num(lng, cur.lng || 0),
        short_name: 'Custom',
        accuracy: 1
      })
    }
  }
}
</script>

<style>
.input-group {
  margin: 0px;
}
/* Compact each checkbox row to 40px (density-default renders taller). */
.settings-card .v-checkbox .v-input__control,
.settings-card .v-checkbox .v-selection-control {
  min-height: 40px;
  height: 40px;
}
/* Catalog dropdown: opaque original grey so the item list stays readable — the
   global translucent .v-select__content .v-list (rgba(66,66,66,0.7)) let the sky
   show through and washed the text out. Scoped to this select via its menu
   contentClass so the language dropdown is unaffected; the extra class raises
   specificity to beat that !important rule. */
.v-select__content.catalog-menu .v-list {
  background: #424242 !important;
}
</style>
