// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <v-card v-if="selectedObject && $store.state.showSelectedInfo" style="background: rgba(66, 66, 66, 0.7); border-radius: 28px;">
    <v-btn icon style="position: absolute; right: 0; background: rgba(66, 66, 66, 0.7) !important;" v-on:click="unselect()"><v-icon>mdi-close</v-icon></v-btn>
    <v-card-title primary-title>
      <div style="width: 100%">
        <img :src="icon" height="48" width="48" align="left" style="margin-top: 3px; margin-right: 10px"/>
        <div style="overflow: hidden; text-overflow: ellipsis;">
          <div class="text-h5">{{ title }}</div>
          <div class="text-grey text-body-2">{{ type }}</div>
        </div>
      </div>
    </v-card-title>
    <v-card-text style="padding-bottom: 5px;">
      <v-row v-if="otherNames.length > 1" style="width: 100%;">
        <v-col cols="12">
          <span style="position: absolute;">{{ $t('Also known as') }}</span><span style="padding-left: 33.3333%">&nbsp;</span><span class="text-caption text-white" v-for="mname in otherNames1to7" :key="mname" style="margin-right: 15px; font-weight: 500;">{{ mname }}</span>
          <v-btn size="small" icon variant="text" class="text-grey" v-if="otherNames.length > 8" v-on:click="showMinorNames = !showMinorNames" style="margin-top: -5px; margin-bottom: -5px;"><v-icon>mdi-dots-horizontal</v-icon></v-btn>
          <span class="text-caption text-white" v-for="mname in otherNames8andMore" :key="mname" style="margin-right: 15px; font-weight: 500">{{ mname }}</span>
        </v-col>
      </v-row>
    </v-card-text>
    <v-card-text>
      <template v-for="item in items" :key="item.key">
        <v-row style="width: 100%" no-gutters>
          <v-col cols="4" style="color: #dddddd">{{ item.key }}</v-col>
          <v-col cols="8" style="font-weight: 500" class="text-white"><span v-html="item.value"></span></v-col>
        </v-row>
      </template>
    </v-card-text>
    <v-card-actions v-if="pluginsSelectedInfoExtraGuiComponents.length" style="margin-top: -25px">
      <v-spacer/>
      <template v-for="item in pluginsSelectedInfoExtraGuiComponents" :key="item">
        <component :is="item"></component>
      </template>
    </v-card-actions>
    <div v-if="$store.state.showSelectedInfoButtons" style="position: absolute; right: 0px; bottom: -50px;">
      <v-btn v-if="showPointToButton" icon size="small" variant="text" v-on:click="lockToSelection()">
        <img src="@/assets/images/svg/ui/point_to.svg" height="40px" style="min-height: 40px"></img>
      </v-btn>
      <v-btn v-if="!showPointToButton" icon size="small" variant="text" @mousedown="zoomOutButtonClicked()">
        <img :class="{bt_disabled: !zoomOutButtonEnabled}" src="@/assets/images/svg/ui/remove_circle_outline.svg" height="40px" style="min-height: 40px"></img>
      </v-btn>
      <v-btn v-if="!showPointToButton" icon size="small" variant="text" @mousedown="zoomInButtonClicked()">
        <img :class="{bt_disabled: !zoomInButtonEnabled}" src="@/assets/images/svg/ui/add_circle_outline.svg" height="40px" style="min-height: 40px"></img>
      </v-btn>
    </div>
  </v-card>
</template>

<script>

import Moment from 'moment'
import swh from '@/assets/sw_helpers.js'

export default {
  data: function () {
    return {
      showMinorNames: false,
      items: []
    }
  },
  computed: {
    selectedObject: function () {
      return this.$store.state.selectedObject
    },
    stelSelectionId: function () {
      return this.$store.state.stel && this.$store.state.stel.selection ? this.$store.state.stel.selection : undefined
    },
    title: function () {
      return this.selectedObject ? this.otherNames[0] : 'Selection'
    },
    otherNames: function () {
      return this.selectedObject ? swh.namesForSkySource(this.selectedObject, 26) : undefined
    },
    otherNames1to7: function () {
      return this.otherNames.slice(1, 8)
    },
    otherNames8andMore: function () {
      return this.showMinorNames ? this.otherNames.slice(8) : []
    },
    type: function () {
      if (!this.selectedObject) return this.$t('Unknown')
      let morpho = ''
      if (this.selectedObject.model_data && this.selectedObject.model_data.morpho) {
        morpho = swh.nameForGalaxyMorpho(this.selectedObject.model_data.morpho)
        if (morpho) {
          morpho = morpho + ' '
        }
      }
      return morpho + swh.nameForSkySourceType(this.selectedObject.types[0])
    },
    icon: function () {
      return swh.iconForSkySource(this.selectedObject)
    },
    showPointToButton: function () {
      if (!this.$store.state.stel.lock) return true
      if (this.$store.state.stel.lock !== this.$store.state.stel.selection) return true
      return false
    },
    zoomInButtonEnabled: function () {
      if (!this.$store.state.stel.lock || !this.selectedObject) return false
      return true
    },
    zoomOutButtonEnabled: function () {
      if (!this.$store.state.stel.lock || !this.selectedObject) return false
      return true
    },
    extraButtons: function () {
      return swh.selectedObjectExtraButtons
    },
    pluginsSelectedInfoExtraGuiComponents: function () {
      let res = []
      for (const i in this.$stellariumWebPlugins()) {
        const plugin = this.$stellariumWebPlugins()[i]
        if (plugin.selectedInfoExtraGuiComponents) {
          res = res.concat(plugin.selectedInfoExtraGuiComponents)
        }
      }
      return res
    }
  },
  watch: {
    selectedObject: function (s) {
      this.showMinorNames = false
      if (this.timer) { clearInterval(this.timer); this.timer = undefined }
      // The details card is hidden unless showSelectedInfo is on; only then is
      // there anything to compute or refresh once per second.
      if (!s || !this.$store.state.showSelectedInfo) return
      var that = this
      that.items = that.computeItems()
      that.timer = setInterval(() => { that.items = that.computeItems() }, 1000)
    },
    stelSelectionId: function (s) {
      if (!this.$stel.core.selection) {
        // Deselected from any path (close button, tap on empty sky...):
        // drop the tracking lock too, otherwise the camera keeps following
        // the old object forever (the engine only clears lock on manual pan).
        if (this.$stel.core.lock) this.$stel.core.lock = 0
        this.$store.commit('setSelectedObject', 0)
        return
      }
      swh.sweObj2SkySource(this.$stel.core.selection).then(res => {
        this.$store.commit('setSelectedObject', res)
      }, err => {
        console.log("Couldn't find info for object " + s + ':' + err)
        this.$store.commit('setSelectedObject', 0)
      })
    }
  },
  methods: {
    computeItems: function () {
      const obj = this.$stel.core.selection
      if (!obj) return []
      const that = this

      const ret = []

      const addAttr = (key, attr, format) => {
        const v = obj.getInfo(attr)
        if (v && !isNaN(v)) {
          ret.push({
            key: key,
            value: format ? format(v) : v.toString()
          })
        }
      }

      addAttr(that.$t('Magnitude'), 'vmag', this.formatMagnitude)
      addAttr(that.$t('Distance'), 'distance', this.formatDistance)
      if (this.selectedObject.model_data) {
        if (this.selectedObject.model_data.radius) {
          ret.push({
            key: that.$t('Radius'),
            value: this.selectedObject.model_data.radius.toString() + ' Km'
          })
        }
        if (this.selectedObject.model_data.spect_t) {
          ret.push({
            key: that.$t('Spectral Type'),
            value: this.selectedObject.model_data.spect_t
          })
        }
        if (this.selectedObject.model_data.dimx) {
          const dimy = this.selectedObject.model_data.dimy ? this.selectedObject.model_data.dimy : this.selectedObject.model_data.dimx
          ret.push({
            key: that.$t('Size'),
            value: this.selectedObject.model_data.dimx.toString() + "' x " + dimy.toString() + "'"
          })
        }
      }
      const formatInt = function (num, padLen) {
        const pad = new Array(1 + padLen).join('0')
        return (pad + num).slice(-pad.length)
      }
      const formatRA = function (a) {
        const raf = that.$stel.a2tf(a, 1)
        return '<div class="radecVal">' + formatInt(raf.hours, 2) + '<span class="radecUnit">h</span>&nbsp;</div><div class="radecVal">' + formatInt(raf.minutes, 2) + '<span class="radecUnit">m</span></div><div class="radecVal">' + formatInt(raf.seconds, 2) + '.' + raf.fraction + '<span class="radecUnit">s</span></div>'
      }
      const formatAz = function (a) {
        const raf = that.$stel.a2af(a, 1)
        return '<div class="radecVal">' + formatInt(raf.degrees < 0 ? raf.degrees + 180 : raf.degrees, 3) + '<span class="radecUnit">°</span></div><div class="radecVal">' + formatInt(raf.arcminutes, 2) + '<span class="radecUnit">\'</span></div><div class="radecVal">' + formatInt(raf.arcseconds, 2) + '.' + raf.fraction + '<span class="radecUnit">"</span></div>'
      }
      const formatDec = function (a) {
        const raf = that.$stel.a2af(a, 1)
        return '<div class="radecVal">' + raf.sign + formatInt(raf.degrees, 2) + '<span class="radecUnit">°</span></div><div class="radecVal">' + formatInt(raf.arcminutes, 2) + '<span class="radecUnit">\'</span></div><div class="radecVal">' + formatInt(raf.arcseconds, 2) + '.' + raf.fraction + '<span class="radecUnit">"</span></div>'
      }
      const posCIRS = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'JNOW', obj.getInfo('radec'))
      const radecCIRS = this.$stel.c2s(posCIRS)
      const raCIRS = this.$stel.anp(radecCIRS[0])
      const decCIRS = this.$stel.anpm(radecCIRS[1])
      ret.push({
        key: that.$t('Ra/Dec'),
        value: formatRA(raCIRS) + '&nbsp;&nbsp;&nbsp;' + formatDec(decCIRS)
      })
      const azalt = this.$stel.c2s(this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'OBSERVED', obj.getInfo('radec')))
      const az = this.$stel.anp(azalt[0])
      const alt = this.$stel.anpm(azalt[1])
      ret.push({
        key: that.$t('Az/Alt'),
        value: formatAz(az) + '&nbsp;&nbsp;&nbsp;' + formatDec(alt)
      })
      addAttr(that.$t('Phase'), 'phase', this.formatPhase)
      const vis = obj.computeVisibility()
      let str = ''
      if (vis.length === 0) {
        str = that.$t('Not visible tonight')
      } else if (vis[0].rise === null) {
        str = that.$t('Always visible tonight')
      } else {
        str = that.$t('Rise: {0}&nbsp;&nbsp;&nbsp; Set: {1}', [this.formatTime(vis[0].rise), this.formatTime(vis[0].set)])
      }
      ret.push({
        key: that.$t('Visibility'),
        value: str
      })
      return ret
    },
    formatPhase: function (v) {
      return (v * 100).toFixed(0) + '%'
    },
    formatMagnitude: function (v) {
      if (!v) {
        return 'Unknown'
      }
      return v.toFixed(2)
    },
    formatDistance: function (d) {
      // d is in AU
      if (!d) {
        return 'NAN'
      }
      const ly = d * swh.astroConstants.ERFA_AULT / swh.astroConstants.ERFA_DAYSEC / swh.astroConstants.ERFA_DJY
      if (ly >= 0.1) {
        return ly.toFixed(2) + '<span class="radecUnit"> light years</span>'
      }
      if (d >= 0.1) {
        return d.toFixed(2) + '<span class="radecUnit"> AU</span>'
      }
      const meter = d * swh.astroConstants.ERFA_DAU
      if (meter >= 1000) {
        return (meter / 1000).toFixed(2) + '<span class="radecUnit"> km</span>'
      }
      return meter.toFixed(2) + '<span class="radecUnit"> m</span>'
    },
    formatTime: function (jdm) {
      var d = new Date()
      d.setMJD(jdm)
      const utc = new Moment(d)
      utc.utcOffset(this.$store.state.stel.utcoffset)
      return utc.format('HH:mm')
    },
    unselect: function () {
      // Also drop the tracking lock: the engine only clears it on manual
      // panning, so without this the camera keeps following the (now
      // unselected) object forever.
      this.$stel.core.lock = 0
      this.$stel.core.selection = 0
    },
    lockToSelection: function () {
      if (this.$stel.core.selection) {
        this.$stel.pointAndLock(this.$stel.core.selection, 0.5)
      }
    },
    zoomInButtonClicked: function () {
      const currentFov = this.$store.state.stel.fov * 180 / Math.PI
      this.$stel.zoomTo(currentFov * 0.3 * Math.PI / 180, 0.4)
      const that = this
      this.zoomTimeout = setTimeout(_ => { that.zoomInButtonClicked() }, 300)
    },
    zoomOutButtonClicked: function () {
      const currentFov = this.$store.state.stel.fov * 180 / Math.PI
      this.$stel.zoomTo(currentFov * 3 * Math.PI / 180, 0.6)
      const that = this
      this.zoomTimeout = setTimeout(_ => { that.zoomOutButtonClicked() }, 200)
    },
    stopZoom: function () {
      if (this.zoomTimeout) {
        clearTimeout(this.zoomTimeout)
        this.zoomTimeout = undefined
      }
    },
    extraButtonClicked: function (btn) {
      btn.callback()
    }
  },
  mounted: function () {
    const that = this
    this.onWindowMouseUp = function (event) {
      that.stopZoom()
    }
    window.addEventListener('mouseup', this.onWindowMouseUp)
  },
  beforeUnmount: function () {
    // Stop the per-second refresh so it can't keep firing (and calling $t) on a
    // torn-down instance after unmount / HMR.
    if (this.timer) { clearInterval(this.timer); this.timer = undefined }
    // Kill the press-and-hold zoom repeat chain and its window-level release
    // handler, or both keep firing on a torn-down instance.
    this.stopZoom()
    window.removeEventListener('mouseup', this.onWindowMouseUp)
  }
}
</script>

<style>
.bt_disabled {
  filter: opacity(0.2);
}

.radecVal {
  display: inline-block;
  font-family: monospace;
  padding-right: 2px;
  font-size: 13px;
  font-weight: bold;
}

.radecUnit {
  color: #dddddd;
  font-weight: normal
}
</style>
