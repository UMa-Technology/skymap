// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>

<v-app>
  <v-main>
    <v-container class="fill-height" fluid style="padding: 0">
      <div id="stel">
        <div style="position: relative; width: 100%; height: 100%">
          <component v-bind:is="guiComponent"></component>
          <canvas id="stel-canvas" ref='stelCanvas'></canvas>
        </div>
      </div>
    </v-container>
  </v-main>

</v-app>

</template>

<script>

import Gui from '@/components/gui.vue'
import GuiLoader from '@/components/gui-loader.vue'
import WebGui from '@/components/webgui.vue'
import swh from '@/assets/sw_helpers.js'
import jsbridge from '@/utils/jsbridge'
import { wantsWebGui } from '@/utils/webgui.js'
import Moment from 'moment'

export default {
  data (context) {
    return {
      guiComponent: 'GuiLoader',
      startTimeIsSet: false,
      initDone: false,
      dataSourceInitDone: false
    }
  },
  components: { Gui, GuiLoader, WebGui },
  methods: {
    setStateFromQueryArgs: function () {
      // Set the core's state from URL query arguments such
      // as date, location, view direction & fov
      var that = this

      if (!this.initDone) {
        this.$stel.core.time_speed = 1
        let d = new Date()
        if (this.$route.query.date) {
          d = new Moment(this.$route.query.date).toDate()
          this.$stel.core.observer.utc = d.getMJD()
          this.startTimeIsSet = true
        }

        if (this.$route.query.lng && this.$route.query.lat) {
          const pos = { lat: Number(this.$route.query.lat), lng: Number(this.$route.query.lng), alt: this.$route.query.elev ? Number(this.$route.query.elev) : 0, accuracy: 1 }
          swh.geoCodePosition(pos, that).then((loc) => {
            that.$store.commit('setCurrentLocation', loc)
          }, (error) => { console.log(error) })
        }

        this.$stel.core.observer.yaw = this.$route.query.az ? Number(this.$route.query.az) * Math.PI / 180 : 0
        this.$stel.core.observer.pitch = this.$route.query.alt ? Number(this.$route.query.alt) * Math.PI / 180 : 30 * Math.PI / 180
        this.$stel.core.fov = this.$route.query.fov ? Number(this.$route.query.fov) * Math.PI / 180 : 120 * Math.PI / 180

        // Sky-text language can be seeded at load (race-free), same as the
        // lat/lng/date/az/alt/fov args above: ?lang=zh_cn applies during this
        // (pre-first-frame) init pass so the very first painted frame is
        // already localized. Post-ready the host switches it live via
        // swh.setSkyLanguage() / the setSkyLanguage bridge action (§2.2/§2.9).
        if (this.$route.query.lang) {
          swh.setSkyLanguage(this.$route.query.lang)
        }

        this.initDone = true
      }

      if (this.$route.path.startsWith('/skysource/')) {
        const name = decodeURIComponent(this.$route.path.substring(11))
        console.log('Will select object: ' + name)
        // 直接从本地引擎查找对象（离线，不走 NoctuaSky）
        const obj = this.$stel.getObj(name)
        if (obj) {
          swh.setSweObjAsSelection(obj)
        } else {
          console.log("Couldn't find skysource for name: " + name)
        }
      }
    }
  },
  computed: {
    storeCurrentLocation: function () {
      return this.$store.state.currentLocation
    }
  },
  watch: {
    storeCurrentLocation: function (loc) {
      const DD2R = Math.PI / 180
      this.$stel.core.observer.latitude = loc.lat * DD2R
      this.$stel.core.observer.longitude = loc.lng * DD2R
      this.$stel.core.observer.elevation = loc.alt

      // At startup, we need to wait for the location to be set before deciding which
      // startup time to set so that it's night time.
      if (!this.startTimeIsSet) {
        // App 嵌入形态：时间由宿主 App 喂入（observer.utc），不自动跳到日落后
        // this.$stel.core.observer.utc = swh.getTimeAfterSunset(this.$stel)
        this.startTimeIsSet = true
      }
      // Init of time and date is complete
      this.$store.commit('setValue', { varName: 'initComplete', newValue: true })
    },
    $route: function () {
      // react to route changes...
      this.setStateFromQueryArgs()
    }
  },
  mounted: function () {
    var that = this

    // WebView 嵌入：全局禁用右键/长按上下文菜单
    window.addEventListener('contextmenu', (e) => {
      e.preventDefault()
      return false
    })

    for (const i in this.$stellariumWebPlugins()) {
      const plugin = this.$stellariumWebPlugins()[i]
      if (plugin.onAppMounted) {
        plugin.onAppMounted(that)
      }
    }

    // Host readiness contract (§2.9): tell the native host we are booting
    // (downloading + instantiating the wasm) so it keeps its splash up instead
    // of revealing a black WebView. window.StellariumInitPhase is already
    // 'booting' (set at sw_helpers load) for hosts that poll instead.
    jsbridge.postMessage('initProgress', { phase: 'booting', base: window.SkymapBase })

    import('@/assets/js/stellarium-web-engine.wasm?url').then(f => {
      // Initialize the StelWebEngine viewer singleton
      // After this call, the StelWebEngine state will always be available in vuex store
      // in the $store.stel object in a reactive way (useful for vue components).
      // To modify the state of the StelWebEngine, it's enough to call/set values directly on the $stel object
      try {
        swh.initStelWebEngine(that.$store, f.default, that.$refs.stelCanvas, function () {
          // Engine is ready (window.$stel usable). sw_helpers already marked
          // phase 'engineReady'; mirror it to the native host so it knows it
          // may now push observer location / time / language. Still keep the
          // splash up until 'firstFrame' below. (§2.9 readiness contract.)
          jsbridge.postMessage('initProgress', { phase: 'engineReady', base: window.SkymapBase })

          // No browser/GeoIP auto-detection: the location is supplied by the
          // host (Flutter) app via `$stel.core.observer.latitude/longitude/
          // elevation` (see USAGE.md) or by the
          // ?lat=&lng= URL query args (handled in setStateFromQueryArgs). If
          // nothing is supplied the engine keeps its default observer.

          // Merged all-script fonts (Alibaba Sans latin + PuHuiTi CJK subset +
          // Noto KR Hangul subset — built by tools/make-app-fonts.py), so no
          // per-language font loading is needed anywhere.
          that.$stel.setFont('regular', process.env.BASE_URL + 'fonts/SkyFont-Regular.ttf')
          that.$stel.setFont('bold', process.env.BASE_URL + 'fonts/SkyFont-Bold.ttf')
          // 只有当挪动到指定区域的时候，才显示这个区域的星座图像
          that.$stel.core.constellations.show_only_pointed = true
          that.$stel.core.constellations.images_visible = false
          that.$stel.core.atmosphere.visible = false
          // Comets join the single-select catalog dropdown (Settings):
          // hidden by default like the other overlay catalogs, shown only
          // while "Comets" is the selected catalog.
          that.$stel.core.comets.visible = false

          // Dim only the star field so bright stars are less glary on
          // high-brightness (mobile) screens: point sources (stars) use the
          // lower star_exposure_scale, while the sky / Milky Way / DSS keep the
          // default exposure_scale (2) untouched. Tune live via
          // $stel.core.star_exposure_scale (lower = dimmer stars).
          that.$stel.core.star_exposure_scale = 0.8

          // Flatten the bright/faint size contrast so bright stars are less
          // dominant. star_relative_scale is the exponent in the point radius
          // (radius = s_linear * pow(luminance, star_relative_scale / 2)):
          // lower -> the size gap between bright and faint stars narrows.
          // Only affects point size, not per-star luminance. Engine default is
          // 0.8. Tune live via $stel.core.star_relative_scale.
          that.$stel.core.star_relative_scale = 0.5

          // The additive halo/glow around bright stars (shader u_glow; final
          // alpha = core + glow * brightness * star_glow_scale) is off by
          // engine default (0). Restore the historical bloom live via
          // $stel.core.star_glow_scale = 0.2 (higher = more glary).

          // Show star names earlier while zooming. The engine gates star
          // labels on "the faintest vmag whose point radius reaches 0.4px"
          // (painter.hints_limit_mag) minus fixed offsets — and the two star
          // dimming tweaks above shrink point radii, which as a side effect
          // pushed that gate later on phones. This offset shifts ONLY star
          // labels (DSO hints have their own core.dsos.hints_mag_offset).
          // Tune live via $stel.core.stars.hints_mag_offset (higher = labels
          // appear earlier / on fainter stars).
          that.$stel.core.stars.hints_mag_offset = 1.5

          that.setStateFromQueryArgs()
          // ?webgui=1: development GUI; hosts get the bare overlay.
          that.guiComponent = wantsWebGui(window.location.search) ? 'WebGui' : 'Gui'

          // AR 模式：拖动星图（超过阈值）即退出 AR 跟随
          const canvas = that.$refs.stelCanvas
          let startX, startY
          let isMoving = false
          const threshold = 5

          const onMove = (x, y) => {
            if (isMoving && that.$store.state.arMode) {
              if (Math.abs(x - startX) > threshold || Math.abs(y - startY) > threshold) {
                that.$store.commit('setARMode', false)
              }
            }
          }

          canvas.addEventListener('mousedown', (e) => {
            isMoving = true
            startX = e.clientX
            startY = e.clientY
          })
          window.addEventListener('mousemove', (e) => onMove(e.clientX, e.clientY))
          window.addEventListener('mouseup', () => { isMoving = false })

          canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
              isMoving = true
              startX = e.touches[0].clientX
              startY = e.touches[0].clientY
            } else {
              isMoving = false
            }
          }, { passive: true })
          window.addEventListener('touchmove', (e) => {
            if (e.touches.length > 1) {
              isMoving = false
            }
            if (e.touches.length === 1) onMove(e.touches[0].clientX, e.touches[0].clientY)
          }, { passive: true })
          window.addEventListener('touchend', () => { isMoving = false })

          for (const i in that.$stellariumWebPlugins()) {
            const plugin = that.$stellariumWebPlugins()[i]
            if (plugin.onEngineReady) {
              plugin.onEngineReady(that)
            }
          }

          if (!that.dataSourceInitDone) {
            // Set all default data sources
            const core = that.$stel.core
            core.stars.addDataSource({ url: process.env.BASE_URL + 'skydata/stars' })

            // Allow to specify a custom path for sky culture data
            if (that.$route.query.sc) {
              const key = that.$route.query.sc.substring(that.$route.query.sc.lastIndexOf('/') + 1)
              // ?sc= 只取 key，数据仍走本地 skydata（离线）
              const url = process.env.BASE_URL + `skydata/skycultures/${key}`
              core.skycultures.addDataSource({ url: url, key: key })
              core.skycultures.current_id = key
            } else {
              core.skycultures.addDataSource({ url: process.env.BASE_URL + 'skydata/skycultures/western', key: 'western' })
            }

            core.dsos.addDataSource({ url: process.env.BASE_URL + 'skydata/dso' })
            // Show more deep-sky objects (circles + labels), especially at the
            // wide default FOV. The engine treats zoom like a telescope: at wide
            // FOV the "light grasp" saturates at its floor, brightening the
            // limiting magnitude and culling faint DSOs. This DSO-only offset
            // raises the DSO hint limit without touching star rendering. Range
            // ~+1.5..+3 is safe (headroom to the star-limit cull is ~3.5 mag).
            // +1.5 (bottom of the safe range) keeps the chart from crowding on
            // both desktop and phone; the engine adds a per-screen bump on top
            // (dso.c) so small screens still aren't sparse. Live-tunable:
            // $stel.core.dsos.hints_mag_offset = <n>  (lower = fewer/less dense).
            core.dsos.hints_mag_offset = 0.5
            // Landscape. The engine activates whichever source is registered
            // FIRST (landscape.c:landscapes_add_data_source), and this is the
            // only one, so drakkar is the horizon. Built by
            // tools/make-landscape-survey.py as a HiPS pyramid up to order 2 --
            // a Norder0-only landscape gets clamped by hips_get_render_order_
            // clamped() and renders 12 hugely magnified tiles (soft, with
            // visible tile edges); see that tool's docstring.
            core.landscapes.addDataSource({ url: process.env.BASE_URL + 'skydata/landscapes/drakkar', key: 'drakkar' })
            core.milkyway.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/milkyway' })
            // Deep-sky imaging background (DSS2 color). Offline HiPS orders 3-4
            // (CDS server tiles, capped by hips_order=4 so the engine never
            // requests missing deeper tiles; order_min=3 since DSS only shows
            // below ~10 deg FOV where render order is always >=3 - the Milky Way
            // covers wider views). dss.c fades it in as the Milky Way fades out.
            // The survey is the star-removed, plate-seam-cleaned build (the
            // engine draws stars from its catalog on top); see
            // the internal design notes and tools/plate_eq/.
            core.dss.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/dss' })
            // Hα narrow-band survey overlay (MDW in the north; WHAM south later).
            // Off by default and fov-gated, so tiles are only fetched once the
            // user turns it on and zooms in. This is an optional dataset not
            // shipped in this repository (the layer stays off by default);
            // see the make-halpha-survey pipeline and the internal design notes.
            core.halpha.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/halpha' })
            core.minor_planets.addDataSource({ url: process.env.BASE_URL + 'skydata/mpcorb.dat', key: 'mpc_asteroids' })
            core.planets.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/sso/moon', key: 'moon' })
            core.planets.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/sso/sun', key: 'sun' })
            core.planets.addDataSource({ url: process.env.BASE_URL + 'skydata/surveys/sso/moon', key: 'default' })
            core.comets.addDataSource({ url: process.env.BASE_URL + 'skydata/CometEls.txt', key: 'mpc_comets' })
            // Space stations (ISS + CSS/Tiangong) are wired separately in
            // sw_helpers.js via installSatellites(): it loads a build-day TLE
            // baseline (skydata/tle_satellite_baseline.json) with createObj —
            // deliberately NOT addDataSource/gz (avoids the one-shot `loaded`
            // latch and the .gz Content-Encoding trap). Fresh TLE is pushed in
            // at runtime via window.Satellites.setTLE() (native fetches CelesTrak).
            // 嵌入端默认禁用：引擎 satellites_init 把 visible/hints_visible 置 true，
            // 这里改回 false，由原生按需调用 jsbridge 的 toggleSatellites(true) 打开。
            if (core.satellites) {
              core.satellites.visible = false
              core.satellites.hints_visible = false
            }
          }

          // First-frame gate for the host readiness contract (§2.9). The GUI is
          // now the real canvas (guiComponent='Gui') and every data source is
          // wired; mark 'firstFrame' once the engine has painted the sky at
          // least once — this resolves window.__stelReady and posts 'ready', so
          // the host reveals its WebView / drops its native splash and the user
          // never sees the black GuiLoader stage.
          let firstFrameSent = false
          const emitFirstFrame = function () {
            if (firstFrameSent) return
            firstFrameSent = true
            swh.notifyInitPhase('firstFrame')
            jsbridge.postMessage('initProgress', { phase: 'firstFrame', base: window.SkymapBase })
            jsbridge.postMessage('ready', {
              phase: 'firstFrame',
              fov: that.$stel.core.fov * 180 / Math.PI,
              location: that.$store.state.currentLocation,
              mjd: that.$stel.core.observer.utc
            })
          }
          // Paint-accurate path (visible WebView): two rAFs guarantee at least
          // one real paint happened (a single rAF fires before the paint).
          requestAnimationFrame(function () { requestAnimationFrame(emitFirstFrame) })
          // Fallback: if the host keeps the WebView hidden until 'ready', rAF is
          // paused (document.hidden) and would deadlock — a timer still fires,
          // so signal readiness regardless. The one-shot guard dedupes.
          setTimeout(emitFirstFrame, 200)
        })
      } catch (e) {
        this.$store.commit('setValue', { varName: 'wasmSupport', newValue: false })
        // Terminal failure: tell the host so it stops waiting for 'ready' and
        // can show its own fallback instead of a spinner forever. (§2.9)
        window.StellariumInitPhase = 'error'
        jsbridge.postMessage('initProgress', { phase: 'error', reason: 'wasm-unsupported', base: window.SkymapBase })
      }
    })
  }
}
</script>

<style>

a {
  color: #82b1ff;
}

a:link {
  text-decoration-line: none;
}

.divider_menu {
  margin-top: 8px;
  margin-bottom: 8px;
}

html {
  overflow: hidden;
}

html, body, #app {
  overflow: hidden!important;
  position: fixed!important;
  width: 100%;
  height: 100%;
  padding: 0!important;
  font-size: 14px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Noto Sans', sans-serif;
  touch-action: none;
}

.fullscreen {
  overflow-y: hidden;
  position: fixed;
  width: 100%;
  height: 100%;
  padding: 0!important;
}

.click-through {
  pointer-events: none;
}

.get-click {
  pointer-events: all;
}

.dialog {
  background: transparent;
}

.menu__content {
  background-color: transparent!important;
}

/* Translucent popup surfaces (Settings, time picker, language dropdown):
   ~70% transparent so the sky shows through, matching the selected-object
   panel. An rgba() background (not opacity:) keeps the text/controls fully
   opaque. Scoped under .v-menu so the share-link v-dialog modal stays opaque. */
.v-menu > .v-overlay__content .v-card {
  background-color: rgba(66, 66, 66, 0.7) !important;
}
.v-overlay__content.v-select__content {
  border-radius: 28px !important;
  overflow: hidden;
}
/* The v-select dropdown wraps its list in a v-sheet whose default surface color
   is opaque; make it transparent so only the v-list's rgba() below shows. */
.v-select__content .v-sheet {
  background: transparent !important;
}
.v-select__content .v-list {
  background: rgba(66, 66, 66, 0.7) !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}

#stel {height: 100%; width: 100%; position: absolute;}
#stel-canvas {z-index: -10; width: 100%; height: 100%; touch-action: none;}

.right_panel {
  padding-right: 400px;
}

.v-btn {
  margin-left: 8px;
  margin-right: 8px;
  margin-top: 6px;
  margin-bottom: 6px;
}

.v-application--wrap {
  min-height: 100%!important;
}

/* WebView 嵌入硬化：确保所有容器都禁用 scrollbar */
.v-application,
.v-main,
.v-main__wrap,
.container,
.v-container {
  overflow: hidden!important;
}

/* 隐藏所有滚动条（WebKit 浏览器） */
*::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}

/* Firefox + 全局禁文本选择/长按呼出 */
* {
  scrollbar-width: none;
  -webkit-touch-callout: none !important;
  -webkit-user-select: none !important;
  -khtml-user-select: none !important;
  -moz-user-select: none !important;
  -ms-user-select: none !important;
  user-select: none !important;
}

/* 星图引擎同款字体给 DOM 浮层用（Target/Current 框标签等），
   与 canvas 内星名/线标签保持同一字体家族 */
@font-face {
  font-family: 'SkyFont';
  src: url('/fonts/SkyFont-Regular.ttf') format('truetype');
  font-weight: normal;
}
@font-face {
  font-family: 'SkyFont';
  src: url('/fonts/SkyFont-Bold.ttf') format('truetype');
  font-weight: bold;
}

</style>
