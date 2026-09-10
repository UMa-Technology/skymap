// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div style="position: absolute; display:flex; align-items: flex-end;">
    <v-spacer></v-spacer>

    <bottom-button :label="$t('Constellations')"
                v-if="$store.state.showConstellationsLinesButton !== false"
                :img="imgCstLines"
                img_alt="Constellations Button"
                :toggled="$store.state.stel.constellations.lines_visible"
                @clicked="(b) => { $stel.core.constellations.lines_visible = b; $stel.core.constellations.labels_visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Constellations Art')"
                v-if="$store.state.showConstellationsArtButton !== false"
                :img="imgCstArt"
                img_alt="Constellations Art Button"
                :toggled="$store.state.stel.constellations.images_visible"
                @clicked="(b) => { $stel.core.constellations.images_visible = b; if (b) { $stel.core.constellations.lines_visible = true; $stel.core.constellations.labels_visible = true } }">
    </bottom-button>
    <bottom-button :label="$t('Atmosphere')"
                v-if="$store.state.showAtmosphereButton !== false"
                :img="imgAtmosphere"
                img_alt="Atmosphere Button"
                :toggled="$store.state.stel.atmosphere.visible"
                @clicked="(b) => { $stel.core.atmosphere.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Landscape')"
                v-if="$store.state.showLandscapeButton !== false"
                :img="imgLandscape"
                img_alt="Landscape Button"
                :toggled="$store.state.stel.landscapes.visible"
                @clicked="(b) => { $stel.core.landscapes.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Azimuthal Grid')"
                v-if="$store.state.showAzimuthalGridButton !== false"
                :img="imgAzimuthalGrid"
                img_alt="Azimuthal Button"
                :toggled="$store.state.stel.lines.azimuthal.visible"
                @clicked="(b) => { $stel.core.lines.azimuthal.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Equatorial Grid')"
                v-if="$store.state.showEquatorialGridButton !== false"
                :img="imgEquatorialGrid"
                img_alt="Equatorial Grid Button"
                :toggled="$store.state.stel.lines.equatorial_jnow.visible"
                @clicked="(b) => { $stel.core.lines.equatorial_jnow.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Equatorial J2000 Grid')"
                v-if="$store.state.showEquatorialJ2000GridButton !== false"
                :img="imgEquatorialGrid"
                img_alt="Equatorial J2000 Grid Button"
                :toggled="$store.state.stel.lines.equatorial.visible"
                @clicked="(b) => { $stel.core.lines.equatorial.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Deep Sky Objects')"
                :img="imgNebulae"
                img_alt="Deep Sky Objects Button"
                class="mr-auto"
                :toggled="$store.state.stel.dsos.visible"
                @clicked="(b) => { $stel.core.dsos.visible = b }">
    </bottom-button>
    <bottom-button :label="$t('Night Mode')"
                v-if="$store.state.showNightmodeButton !== false"
                :img="imgNightMode"
                img_alt="Night Mode Button"
                class="mr-auto"
                :toggled="$store.state.nightmode"
                @clicked="(b) => { setNightMode(b) }">
    </bottom-button>
    <bottom-button :label="$t('Fullscreen')"
                :img="fullscreenBtnImage"
                img_alt="Fullscreen Button"
                class="mr-auto"
                :toggled="$store.state.fullscreen"
                @clicked="(b) => { setFullscreen(b) }">
    </bottom-button>

    <v-spacer></v-spacer>

  </div>
</template>

<script>

import BottomButton from '@/components/bottom-button.vue'
import imgCstLines from '@/assets/images/btn-cst-lines.svg'
import imgCstArt from '@/assets/images/btn-cst-art.svg'
import imgAtmosphere from '@/assets/images/btn-atmosphere.svg'
import imgLandscape from '@/assets/images/btn-landscape.svg'
import imgAzimuthalGrid from '@/assets/images/btn-azimuthal-grid.svg'
import imgEquatorialGrid from '@/assets/images/btn-equatorial-grid.svg'
import imgNebulae from '@/assets/images/btn-nebulae.svg'
import imgNightMode from '@/assets/images/btn-night-mode.svg'
import imgFullscreenEnter from '@/assets/images/svg/ui/fullscreen.svg'
import imgFullscreenExit from '@/assets/images/svg/ui/fullscreen_exit.svg'

export default {
  components: { BottomButton },
  data: function () {
    return {
      imgCstLines, imgCstArt, imgAtmosphere, imgLandscape,
      imgAzimuthalGrid, imgEquatorialGrid, imgNebulae, imgNightMode
    }
  },
  computed: {
    fullscreenBtnImage: function () {
      return this.$store.state.fullscreen ? imgFullscreenExit : imgFullscreenEnter
    }
  },
  methods: {
    setFullscreen: function () {
      const doc = document
      const el = doc.documentElement
      if (!doc.fullscreenElement && !doc.webkitFullscreenElement) {
        (el.requestFullscreen || el.webkitRequestFullscreen).call(el)
      } else {
        (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc)
      }
    },
    setNightMode: function (b) {
      this.$store.commit('toggleBool', 'nightmode')
      if (window.navigator.userAgent.indexOf('Edge') > -1) {
        document.getElementById('nightmode').style.opacity = b ? '0.5' : '0'
      }
      document.getElementById('nightmode').style.visibility = b ? 'visible' : 'hidden'
      // Tell the engine so DSO/star markers + labels paint white and the
      // #FF6C20 overlay renders them as #FF6C20 (instead of a doubled dark red).
      if (this.$stel && this.$stel.core) {
        this.$stel.core.nightmode = b
      }
    },
    onFullscreenChange: function () {
      const isFs = !!(document.fullscreenElement || document.webkitFullscreenElement)
      if (this.$store.state.fullscreen !== isFs) {
        this.$store.commit('toggleBool', 'fullscreen')
      }
    }
  },
  mounted: function () {
    document.addEventListener('fullscreenchange', this.onFullscreenChange)
    document.addEventListener('webkitfullscreenchange', this.onFullscreenChange)
  },
  beforeUnmount: function () {
    document.removeEventListener('fullscreenchange', this.onFullscreenChange)
    document.removeEventListener('webkitfullscreenchange', this.onFullscreenChange)
  }
}
</script>

<style>
@media all and (max-width: 600px) {
  .tmenubt {
    min-width: 30px;
  }
}
@media all and (min-width: 600px) {
  .tbtcontainer {
    width: 300px;
  }
}
</style>
