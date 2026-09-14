// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <framing-overlay ref="framing" />
</template>
<script>
import Moment from 'moment'
import jsbridge from '@/utils/jsbridge'
import swh from '@/assets/sw_helpers'
import { customHorizonAltAt } from '@/assets/custom-horizon.js'
import FramingOverlay from './framing-overlay.vue'

export default {
  components: { FramingOverlay },
  data: function () {
    return {
      calibrationOffset: {
        azimuth: 0,
        altitude: 0
      },
      linesLayer: null,
      linesObj: null,
      linesArrowObj: null,
      linesArrowBuilder: null,
      // 中天标记（菱形 + 时刻文本）：尺寸随 fov 缩放，单独 obj + builder
      linesTransitObj: null,
      linesTransitBuilder: null,
      // 时间标签随 fov 动态加密：单独 obj + builder，fov 档位变化时重建
      linesLabelObj: null,
      linesLabelBuilder: null,
      linesLabelInterval: null,
      // 按轨迹角尺寸修正后的间隔计算函数（高赤纬轨迹圆小，标签需抽稀）
      linesLabelIntervalFn: null,
      // 最近一次 drawLines 的原始入参，自定义地平线变化时用于重画（夜间色地平线判定即时生效）
      lastLinesData: null,
      linesRedrawTimer: null,
      currentRectLayer: null,
      currentRectObj: null,
      smoothing: {
        enabled: true,
        factor: 0.3,
        current: { azimuth: 0, altitude: 0 },
        target: { azimuth: 0, altitude: 0 }
      },
      isEnabled: false,
      lastUpdate: 0,
      lastStableAzimuth: 0,
      lastAlt: undefined,
      // 自定义地平线桥状态（window.CustomHorizon 是单向桥，引擎不回读，本地记录用于 getState 上报）
      customHorizonHasProfile: false,
      customHorizonVisible: false,
      // 标记是否通过 jsbridge 设置过时间
      hasSetDateTime: false,
      // 触摸禁用标志
      touchDisabled: false,
      // 连续缩放定时器（zoomIn/zoomOut 循环，stopZoom 清除）
      zoomTimeout: null,
      // 锁定视图：拖动开关状态，实际禁用由引擎 movements.pan_enabled 承担；
      // 此处仅保留字段供上报/备用
      viewLocked: false
    }
  },
  mounted () {
    this.registerBridgeActions()
  },
  beforeUnmount () {
    this.stopZoom()
    if (this.linesRedrawTimer) {
      clearTimeout(this.linesRedrawTimer)
      this.linesRedrawTimer = null
    }
  },
  watch: {
    '$store.state.arMode': function (newVal) {
      this.updateState()
    },
    '$store.state.stel.fov': function () {
      this.updateArrows()
    }
  },
  methods: {
    updateFov (data) {
      let fovYDeg

      if (typeof data === 'object' && data !== null) {
        // 处理 {fovX, fovY} 对象参数，直接使用 fovY
        fovYDeg = Number(data.fovY)

        if (isNaN(fovYDeg)) {
          return
        }
      } else {
        // 处理单个数值参数（传统方式，fovY）
        fovYDeg = Number(data)
      }

      // 限制范围
      if (fovYDeg < 0.1) fovYDeg = 0.1
      if (fovYDeg > 180) fovYDeg = 180

      this.$stel.zoomTo(fovYDeg * Math.PI / 180, 0.5)
      this.updateState()
    },
    // 单选 DSO 星表叠加层的可选项（与 view-settings-dialog.vue 的 dsoCatalogItems 保持一致）。
    // 密集 DSO 分类（LDN/LBN/SH2/PK/ACO/B）引擎各有一个布尔开关，UI 层收敛成单选：
    // 任意时刻最多一个生效；彗星（comets）是独立模块，也并入这个单选。
    getDsoCatalogItems () {
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
    // 当前选中的星表值（null 表示 None）
    getDsoCatalog () {
      const d = this.$store.state.stel.dsos
      for (const key of ['dark_nebulae', 'lbn', 'sh2', 'pk', 'aco', 'barnard']) {
        if (d[key]) return key
      }
      // 彗星在独立模块里，不在 dsos 下，但 UI 把它当作单选星表之一
      if (this.$store.state.stel.comets && this.$store.state.stel.comets.visible) return 'comets'
      return null
    },
    // 应用单选星表：选中的开、其余全关（含彗星互斥）
    setDsoCatalog (value) {
      const dsos = this.$stel.core.dsos
      for (const key of ['dark_nebulae', 'lbn', 'sh2', 'pk', 'aco', 'barnard']) {
        dsos[key] = (key === value)
      }
      this.$stel.core.comets.visible = (value === 'comets')
      // 彗星普遍暗于默认门限，选中时放开点/名门限（"选了就显示"）
      this.$stel.core.comets.hints_mag_offset = (value === 'comets') ? 8 : 0
      // 只显示选中的：dsos 类由引擎 any_special 隐藏普通 DSO；彗星是独立模块，
      // 选彗星时手动把 DSO 层关掉，与 dsos 类行为对齐
      this.$stel.core.dsos.visible = (value !== 'comets')
    },
    // 一个名字展开成引擎 designation 候选列表。引擎 core_search 按 designation
    // 精确匹配（大小写不敏感、空格敏感，见 src/core.c core_search），所以要把
    // App 侧常见写法归一化：M31 → M 31、NGC224 → NGC 224、Sh2 155 → SH 2-155，
    // 行星/专名走 NAME 前缀（NAME Mars / NAME Moon）。
    buildNameCandidates (raw) {
      const n = String(raw).trim()
      if (!n) return []
      const out = [n, 'NAME ' + n]
      const sh = n.match(/^Sh\s*2[\s-]*(\d+)$/i)
      if (sh) out.push('SH 2-' + sh[1])
      const m = n.match(/^([A-Za-z]+)\s*(\d+)$/)
      if (m) out.push(m[1] + ' ' + m[2])
      return out
    },
    // 从 gotoAndLock 载荷的 name/names 数组解析引擎真实天体；解析不到返回 undefined
    resolveTargetByName (ss) {
      const names = ss.name || ss.names
      const list = Array.isArray(names) ? names : (names ? [names] : [])
      for (const raw of list) {
        for (const cand of this.buildNameCandidates(raw)) {
          const obj = this.$stel.getObj(cand)
          if (obj) return obj
        }
      }
      return undefined
    },
    updateState () {
      const data =
        {
          toggleConstellationLines: this.$store.state.stel.constellations.lines_visible,
          toggleConstellationArt: this.$store.state.stel.constellations.images_visible,
          toggleAtmosphere: this.$store.state.stel.atmosphere.visible,
          toggleLandscape: this.$store.state.stel.landscapes.visible,
          toogleMilkyway: this.$store.state.stel.milkyway.visible,
          toggleStars: this.$store.state.stel.stars.visible,
          toggleStarLabels: this.$store.state.stel.stars.hints_visible,
          // 空间站（ISS/天宫）显隐
          toggleSatellites: this.$store.state.stel.satellites ? this.$store.state.stel.satellites.visible : false,
          toggleEquatorLine: this.$store.state.stel.lines.equator_line.visible,
          toggleMeridian: this.$store.state.stel.lines.meridian.visible,
          toggleEcliptic: this.$store.state.stel.lines.ecliptic.visible,
          toggleAzimuthalGrid: this.$store.state.stel.lines.azimuthal.visible,
          toggleEquatorialGrid: this.$store.state.stel.lines.equatorial_jnow.visible,
          toggleEquatorialJ2000Grid: this.$store.state.stel.lines.equatorial.visible,
          // 单选 DSO 星表叠加层：当前选中值 + 可选项列表（供 native 渲染 picker）
          dsoCatalog: this.getDsoCatalog(),
          dsoCatalogItems: this.getDsoCatalogItems(),
          // 自定义地平线：是否已设置廓线 + 是否显示
          hasCustomHorizon: this.customHorizonHasProfile,
          showCustomHorizon: this.customHorizonVisible,
          toggleNightMode: this.$store.state.nightmode,
          currentTime: this.getLocalTime(),
          location: this.$store.state.currentLocation,
          speedTime: this.$store.state.stel.time_speed,
          fov: this.$store.state.stel.fov * 180 / Math.PI,
          fovX: this.$stel.core.fovX * 180 / Math.PI,
          fovY: this.$stel.core.fovY * 180 / Math.PI,
          arMode: this.$store.state.arMode,
          enableArMode: this.$store.state.appEnableARMode,
          currentLocation: this.getCenterRaDecValue(),
          direction: ((this.$stel.core.observer.yaw * 180 / Math.PI) % 360 + 360) % 360,
          // 当前星空文化的 key（引擎的 current_id）
          skyCulture: this.$stel.core.skycultures.current_id,
          drawSelectedTargetLine: this.linesObj != null,
          ...this.$refs.framing.stateFields()
        }
      this.$refs.framing.tick()
      jsbridge.postMessage('getState', data)
    },
    registerBridgeActions () {
      const actions = {
        // 星座线
        toggleConstellationLines: (visible) => {
          this.$stel.core.constellations.lines_visible = visible
          this.$stel.core.constellations.labels_visible = visible
          this.updateState()
        },
        toogleMilkyway: (visible) => {
          this.$stel.core.milkyway.visible = visible
          this.updateState()
        },
        // 恒星
        toggleStars: (visible) => {
          this.$stel.core.stars.visible = visible
          this.updateState()
        },
        // 恒星名字（拜耳 / 弗兰斯蒂德 / 专名）显隐，不影响恒星本身，也不影响
        // 星座名与 DSO 名。选中的那颗仍然显示名字（stars.c 的 `selected ||`），
        // 否则选中后无从确认选中的是哪颗。
        toggleStarLabels: (visible) => {
          this.$stel.core.stars.hints_visible = visible
          this.updateState()
        },
        // 运行期切换星空文化（'western' / 'western-new' / 'chinese' / ...）。
        // key 必须同时是 skydata/skycultures/<key>/ 的目录名和该目录 index.json
        // 里的顶层 "id"——引擎 skycultures.c 的 assert 就是比这两者。
        // addDataSource 在引擎侧按 key 幂等（已加过直接 return），所以重复切换
        // 不会重复下载；切换时 skyculture_deactivate() 会清空全部星座对象再按新
        // 文化重建，因此两套文化的星座 id 相同也不冲突。
        setSkyCulture: (key) => {
          // key 会被拼进 URL，限定字符集挡掉 ../ 之类的路径穿越。
          if (typeof key !== 'string' || !/^[A-Za-z0-9_-]+$/.test(key)) {
            console.error('setSkyCulture: bad key ' + key)
            return
          }
          const core = this.$stel.core
          core.skycultures.addDataSource({
            url: process.env.BASE_URL + 'skydata/skycultures/' + key, key: key
          })
          core.skycultures.current_id = key
          this.updateState()
        },
        // 空间站（ISS/天宫）显隐
        toggleSatellites: (visible) => {
          this.$stel.core.satellites.visible = visible
          this.$stel.core.satellites.hints_visible = visible
          this.updateState()
        },
        // 空间站 TLE 刷新：原生抓取 CelesTrak 后把最新 TLE 推入（window.Satellites
        // 单向桥）。records: [{ model_data: { norad_number, tle: [l1, l2], mag }, names }]
        // 引擎按 NORAD 就地更新既有对象的轨道根数（不 remove+add，避免渲染缓存悬空指针）。
        setSatelliteTLE: (records) => {
          if (!window.Satellites) return
          window.Satellites.setTLE(records)
          this.updateState()
        },
        // 天球赤道线
        toggleEquatorLine: (visible) => {
          this.$stel.core.lines.equator_line.visible = visible
          this.updateState()
        },
        toggleMeridian: (visible) => {
          this.$stel.core.lines.meridian.visible = visible
          this.updateState()
        },
        toggleEcliptic: (visible) => {
          this.$stel.core.lines.ecliptic.visible = visible
          this.updateState()
        },
        // 单选 DSO 星表叠加层（None/LDN/LBN/SH2/PK/ACO/B/Comets）
        // 传入 value: null | 'dark_nebulae' | 'lbn' | 'sh2' | 'pk' | 'aco' | 'barnard' | 'comets'
        setDsoCatalog: (value) => {
          this.setDsoCatalog(value)
          this.updateState()
        },
        // 星座图
        toggleConstellationArt: (visible) => {
          this.$stel.core.constellations.images_visible = visible
          this.updateState()
        },
        // 大气层
        toggleAtmosphere: (visible) => {
          this.$stel.core.atmosphere.visible = visible
          this.updateState()
        },
        // 地景
        toggleLandscape: (visible) => {
          this.$stel.core.landscapes.visible = visible
          this.updateState()
        },
        // 自定义地平线（window.CustomHorizon 单向桥，见 USAGE.md）
        // profile: [[az,alt]] | [{az,alt}] | {points:[{az,alt}]}，az/alt 单位为度。
        // 非法/空廓线等价于清除；引擎侧默认隐藏，set 后需 showCustomHorizon(true) 才显示。
        setCustomHorizon: (profile) => {
          if (!window.CustomHorizon) return
          window.CustomHorizon.set(profile)
          const points = (profile && profile.points) ? profile.points : profile
          this.customHorizonHasProfile = Array.isArray(points) && points.length >= 2
          this.updateState()
          this.scheduleLinesRedraw()
        },
        showCustomHorizon: (visible) => {
          if (!window.CustomHorizon) return
          window.CustomHorizon.show(visible)
          this.customHorizonVisible = !!visible
          this.updateState()
          this.scheduleLinesRedraw()
        },
        clearCustomHorizon: () => {
          if (!window.CustomHorizon) return
          window.CustomHorizon.clear()
          this.customHorizonHasProfile = false
          this.updateState()
          this.scheduleLinesRedraw()
        },
        // 地平网格
        toggleAzimuthalGrid: (visible) => {
          this.$stel.core.lines.azimuthal.visible = visible
          this.updateState()
        },
        // 赤道网格
        toggleEquatorialGrid: (visible) => {
          this.$stel.core.lines.equatorial_jnow.visible = visible
          this.updateState()
        },
        // 赤道 J2000 网格
        toggleEquatorialJ2000Grid: (visible) => {
          this.$stel.core.lines.equatorial.visible = visible
          this.updateState()
        },
        // 夜间模式
        toggleNightMode: (enabled) => {
          this.setNightMode(enabled)
          this.updateState()
        },
        enableARMode: (enabled) => {
          this.$store.commit('setAppEnableARMode', enabled)
          if (enabled) {
            this.$store.commit('setARMode', false)
          } else {
            this.$store.commit('setARMode', false)
          }
          this.updateState()
          this.updateState()
        },
        // 仅用于配置星图的 armode,和 app 本身的 armode 没关系
        updateArMode: (v) => {
          this.$store.commit('setARMode', v)
        },
        gotoByAltAndAzWithArMode: (ss) => {
          if (!this.$store.state.appEnableARMode) {
            return
          }
          const currentAlt = ss.alt
          if (!this.$store.state.arMode) {
            if (this.lastAlt !== undefined) {
              const diff = Math.abs(currentAlt - this.lastAlt)
              // 当高度变化超过 2 度时，认为用户在上下晃动手机，重新开启 AR 模式
              if (diff > 2) {
                this.$store.commit('setARMode', true)
                // 开启 AR 模式后立即执行移动，不再 return
              } else {
                this.lastAlt = currentAlt
                return
              }
            } else {
              this.lastAlt = currentAlt
              return
            }
          }
          this.lastAlt = currentAlt
          // Engine yaw IS standard azimuth (X=N, Y=E), matching App.vue's
          // ?az= handling, the s2c(az,alt) draw paths and updateState's
          // reported direction — all positive. (Was negated here, which put
          // the same az 2×az away from every other surface.)
          this.$stel.core.observer.yaw = ss.az * 0.017453292519943295
          this.$stel.core.observer.pitch = ss.alt * 0.017453292519943295
        },
        gotoByAltAndAz: (ss) => {
          this.$stel.core.observer.yaw = ss.az * 0.017453292519943295
          this.$stel.core.observer.pitch = ss.alt * 0.017453292519943295
        },
        gotoAndLock: (ss) => {
          // 名称优先（远端功能）：name/names 里任一能解析成引擎真实天体就直接
          // 选它——信息面板/高亮/跟踪都是真对象。解析不到（本地化名、目标 tile
          // 未加载等）时回落到下面的 ra/dec 坐标路径。
          const named = this.resolveTargetByName(ss)
          if (named) {
            swh.setSweObjAsSelection(named, ss.lock ?? true)
            this.updateState()
            return
          }
          // Build a coordinates target from ss.model_data.ra/dec, but only when
          // both are finite: an undefined ra/dec (e.g. an orbital-element data
          // source with no ra/dec fields) would otherwise feed NaN into s2c and
          // poison the observer orientation, blanking the whole view.
          const selectByCoords = () => {
            const raDeg = ss.model_data && ss.model_data.ra
            const decDeg = ss.model_data && ss.model_data.dec
            if (!Number.isFinite(raDeg) || !Number.isFinite(decDeg)) return false
            const coords = this.$stel.createObj('coordinates', {
              pos: this.$stel.s2c(raDeg * Math.PI / 180, decDeg * Math.PI / 180)
            })
            swh.setSweObjAsSelection(coords, ss.lock ?? true)
            return true
          }
          if (ss.model === 'custom') {
            selectByCoords()
          } else {
            let obj = swh.skySource2SweObj(ss)
            if (!obj) {
              obj = this.$stel.createObj(ss.model, ss)
              this.$selectionLayer.add(obj)
              swh.setSweObjAsSelection(obj)
            } else if (!selectByCoords()) {
              // No usable coordinates: select the resolved object itself
              // (keeps its name/magnitude rather than an anonymous point).
              swh.setSweObjAsSelection(obj, ss.lock ?? true)
            }
          }
          this.updateState()
        },
        lockToSelection: () => {
          if (this.$stel.core.selection) {
            this.$stel.pointAndLock(this.$stel.core.selection, 0.5)
            // 居中后调整视场：星图 FOV 短边 = 相机 FOV 长边 × 2。
            // 引擎 fov 即视口短边 FOV（见 framing-overlay.vue 里 updateFovBox 的 aspect 换算），
            // 所以直接把 2× 相机长边喂给 updateFov 即可。
            const camLongEdge = this.$refs.framing.cameraLongEdgeDeg()
            if (camLongEdge > 0) {
              // 自动缩放下限 1°，避免小目标把视场缩得过小
              this.updateFov(Math.max(camLongEdge * 2, 1))
            }
          }
        },
        unselect: () => {
          // 引擎只在手动拖动时自动解除跟踪锁，取消选中必须连 lock 一起清
          //（见 USAGE.md），否则相机会一直追着
          // 已取消选中的天体。新基座引擎已支持直接写 core.lock = 0。
          this.$stel.core.lock = 0
          this.$stel.core.selection = 0
          this.lastAlt = undefined
          this.$store.commit('setARMode', false)
        },
        // updateFov 支持两种调用方式：
        // 1. updateFov(fovDeg) - 传入单个 fovY 度数
        // 2. updateFov({fovX, fovY}) - 传入包含 fovX 和 fovY 的对象
        // 使用 fovY 作为垂直视场角，与 drawRectWithAltAndAz 保持一致
        updateFov: (data) => {
          this.updateFov(data)
        },
        setLocation: (loc) => {
          this.setLocation(loc)
          this.updateState()
        },
        // 运行时切换天体名显示语言（不重载 URL），当帧生效
        // lang: en / zh_cn / zh_tw / pl / fr / de / ja / ru / it / ko / es
        setSkyLanguage: (lang) => {
          swh.setSkyLanguage(lang)
        },
        setDateTime:
          (million) => {
            const isoString = new Date(million).toISOString()
            const m = Moment(isoString)
            m.local()
            this.$stel.core.observer.utc = m.toDate().getMJD()
            this.hasSetDateTime = true
            this.updateState()
          },
        speedTime:
          (speed) => {
            this.$stel.core.time_speed = speed
            this.updateState()
          },
        zoomIn:
          (b) => {
            this.startZoom(b, 0.4)
          },
        zoomOut:
          (b) => {
            this.startZoom(b, 0.6)
          },
        stopZoom:
          () => {
            this.stopZoom()
            this.updateState()
          },
        // 锁定视图：引擎级禁用拖动（movements.pan_enabled），缩放不受影响
        lockView: (enabled) => {
          this.viewLocked = !!enabled
          if (this.$stel && this.$stel.core.movements) {
            this.$stel.core.movements.pan_enabled = !enabled
          }
        },
        // 获取当前状态
        getState:
          () => {
            this.updateState()
          },
        // 启用/禁用触摸
        enableTouch: (enabled) => {
          this.touchDisabled = !enabled
        },
        drawLines: (data) => {
          this.clearLines()
          const {
            points: pointsList = [],
            color = '#F48123',
            width = 2,
            timeLabels = null,
            showLabels = false,
            showArrow = false,
            nightStartIndex = null,
            nightEndIndex = null,
            nightColor = null,
            // 中天：曲线上的（可含小数）点索引 + 专用高亮色 + 文本（如 "中天 21:34"）
            transitIndex = null,
            transitColor = null,
            transitLabel = null,
            // Flutter 新版协议：曲线起点时刻（当天分钟数）+ 每点间隔分钟，供 fov 动态加密标签
            startTimeMinutes = null,
            durationMinutes = null
          } = data

          if (!pointsList || pointsList.length < 2) {
            this.lastLinesData = null
            return
          }
          this.lastLinesData = data

          // 1. 转换坐标并生成虚线段 (Manual Dashing)
          const features = []
          const toRad = Math.PI / 180
          const dashSizeDeg = 0.1 // 虚线实线部分长度 (度)
          const gapSizeDeg = 0.3 // 虚线间隔部分长度 (度)
          const dashRad = dashSizeDeg * toRad
          const gapRad = gapSizeDeg * toRad

          // Helper: Spherical Linear Interpolation
          const slerp = (v1, v2, t) => {
            const omega = Math.acos(Math.min(1, Math.max(-1, v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2])))
            if (Math.abs(omega) < 1e-6) return v1
            const sinOmega = Math.sin(omega)
            const k1 = Math.sin((1 - t) * omega) / sinOmega
            const k2 = Math.sin(t * omega) / sinOmega
            return [
              k1 * v1[0] + k2 * v2[0],
              k1 * v1[1] + k2 * v2[1],
              k1 * v1[2] + k2 * v2[2]
            ]
          }

          const getVecIcrf = (pt) => {
            // 新协议：Flutter 直接传 J2000 ICRF ra/dec（度），不再走 OBSERVED→ICRF 反变换
            if (pt.ra !== undefined && pt.dec !== undefined) {
              return this.$stel.s2c(pt.ra * toRad, pt.dec * toRad)
            }
            // 兼容旧 alt/az：用当前 observer 反变换（存在时间不一致问题，仅作兜底）
            const azR = pt.az * toRad
            const altR = pt.alt * toRad
            const vObs = this.$stel.s2c(azR, altR)
            return this.$stel.convertFrame(this.$stel.core.observer, 'OBSERVED', 'ICRF', vObs)
          }

          const vecToRaDecDeg = (v) => {
            const radec = this.$stel.c2s(v)
            return [radec[0] * 180 / Math.PI, radec[1] * 180 / Math.PI]
          }

          // 2. 将所有点转换为 ICRF 向量
          const rawIcrfPoints = pointsList.map(pt => getVecIcrf(pt))

          // 3. 检测首尾点是否接近重合（闭合圆），如果接近则将最后一个点调整为第一个点的位置
          if (rawIcrfPoints.length >= 2) {
            const vFirst = rawIcrfPoints[0]
            const vLast = rawIcrfPoints[rawIcrfPoints.length - 1]
            const dotFirstLast = vFirst[0] * vLast[0] + vFirst[1] * vLast[1] + vFirst[2] * vLast[2]
            const angleBetween = Math.acos(Math.min(1, Math.max(-1, dotFirstLast)))
            // 如果首尾点角度差小于5度，认为是闭合圆，将最后一个点调整为第一个点的位置
            if (angleBetween < 5 * toRad) {
              rawIcrfPoints[rawIcrfPoints.length - 1] = [...vFirst]
            }
          }

          // 4. 对原始点列表进行插值细分，使圆形更加圆滑
          const interpolationStepDeg = 0.5 // 每0.5度插值一个点
          const interpolationStepRad = interpolationStepDeg * toRad
          const icrfPoints = []
          // 记录每个 rawIcrfPoints[i] 在 icrfPoints 中的索引，方便后续按 raw 索引区间映射累积角度
          const rawIndexToIcrfIndex = new Array(rawIcrfPoints.length).fill(-1)

          for (let i = 0; i < rawIcrfPoints.length - 1; i++) {
            const v1 = rawIcrfPoints[i]
            const v2 = rawIcrfPoints[i + 1]

            const dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
            const segAngle = Math.acos(Math.min(1, Math.max(-1, dot)))

            rawIndexToIcrfIndex[i] = icrfPoints.length
            // 几乎重合：补一个点占位，保证 raw 索引可定位
            if (segAngle < 1e-9) {
              icrfPoints.push(v1)
              continue
            }

            // 计算需要插值的点数
            const numSteps = Math.max(1, Math.ceil(segAngle / interpolationStepRad))

            for (let j = 0; j < numSteps; j++) {
              const t = j / numSteps
              icrfPoints.push(slerp(v1, v2, t))
            }
          }
          // 添加最后一个点
          if (rawIcrfPoints.length > 0) {
            rawIndexToIcrfIndex[rawIcrfPoints.length - 1] = icrfPoints.length
            icrfPoints.push(rawIcrfPoints[rawIcrfPoints.length - 1])
          }

          // 5. 计算每段的角度和累积角度
          const segmentAngles = []
          let totalAngle = 0
          for (let i = 0; i < icrfPoints.length - 1; i++) {
            const v1 = icrfPoints[i]
            const v2 = icrfPoints[i + 1]
            const dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
            const angle = Math.acos(Math.min(1, Math.max(-1, dot)))
            segmentAngles.push({ start: totalAngle, angle: angle, v1: v1, v2: v2 })
            totalAngle += angle
          }

          // 5b. 每个 raw 点对应的累积弧长，便于把 raw 索引（含小数）映射到角度区间
          const icrfCumulative = [0]
          for (const seg of segmentAngles) {
            icrfCumulative.push(seg.start + seg.angle)
          }
          const rawIndexToAngle = (idx) => {
            if (idx == null || !isFinite(idx)) return null
            const maxRaw = rawIcrfPoints.length - 1
            if (idx <= 0) return 0
            if (idx >= maxRaw) return totalAngle
            const i0 = Math.floor(idx)
            const i1 = i0 + 1
            const a0Idx = rawIndexToIcrfIndex[i0]
            const a1Idx = rawIndexToIcrfIndex[i1]
            if (a0Idx < 0 || a1Idx < 0) return null
            const a0 = icrfCumulative[a0Idx]
            const a1 = icrfCumulative[a1Idx]
            return a0 + (a1 - a0) * (idx - i0)
          }
          const nightStartAngle = rawIndexToAngle(nightStartIndex)
          const nightEndAngle = rawIndexToAngle(nightEndIndex)
          const hasNight = nightColor && nightStartAngle != null && nightEndAngle != null && nightEndAngle > nightStartAngle
          const angleIsNight = (a) => hasNight && a >= nightStartAngle && a <= nightEndAngle
          const indexIsNight = (idx) => hasNight && nightStartIndex != null && nightEndIndex != null && idx >= nightStartIndex && idx <= nightEndIndex
          // 低于地平线的目标即使处于夜间时段也不可观测，不应显示夜间色（保持基础橙色）。
          // 判定叠加自定义地平线廓线（若已设置且显示）：目标须同时高于几何地平线和廓线。
          // 用 OBSERVED_GEOM（几何帧，无折射），与 customhorizon C 模块渲染帧一致。
          const isAboveHorizon = (v) => {
            const vObs = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'OBSERVED_GEOM', v)
            const azalt = this.$stel.c2s(vObs)
            const altDeg = azalt[1] * 180 / Math.PI
            if (altDeg < 0) return false
            const ridgeAlt = customHorizonAltAt(azalt[0] * 180 / Math.PI)
            return ridgeAlt == null || altDeg >= ridgeAlt
          }

          // 6. 沿整个圆周连续生成虚线
          const getPointAtAngle = (targetAngle) => {
            // 找到目标角度所在的线段
            for (let i = 0; i < segmentAngles.length; i++) {
              const seg = segmentAngles[i]
              if (targetAngle >= seg.start && targetAngle <= seg.start + seg.angle) {
                // 在这个线段内插值
                const localT = seg.angle > 1e-9 ? (targetAngle - seg.start) / seg.angle : 0
                return slerp(seg.v1, seg.v2, localT)
              }
            }
            // 如果超出范围，返回最后一个点
            return icrfPoints[icrfPoints.length - 1]
          }

          let currentAngle = 0
          while (currentAngle < totalAngle) {
            const dashEndAngle = Math.min(currentAngle + dashRad, totalAngle)

            // 在虚线段内细分多个点，确保弧线平滑
            const dashLength = dashEndAngle - currentAngle
            const numSubPoints = Math.max(2, Math.ceil(dashLength / (0.01 * toRad))) // 每0.01度一个点
            const dashCoords = []

            for (let j = 0; j <= numSubPoints; j++) {
              const t = j / numSubPoints
              const angle = currentAngle + t * dashLength
              if (angle <= totalAngle) {
                const v = getPointAtAngle(angle)
                dashCoords.push(vecToRaDecDeg(v))
              }
            }

            if (dashCoords.length >= 2) {
              const midAngle = (currentAngle + dashEndAngle) / 2
              const strokeColor = angleIsNight(midAngle) && isAboveHorizon(getPointAtAngle(midAngle)) ? nightColor : color
              features.push({
                type: 'Feature',
                properties: {
                  stroke: strokeColor,
                  'stroke-width': width,
                  'stroke-glow': true,
                  'stroke-opacity': 0.7
                },
                geometry: {
                  type: 'LineString',
                  coordinates: dashCoords
                }
              })
            }

            currentAngle += dashRad + gapRad
          }

          // 时间基准：新版协议直接下发起点时刻+间隔；旧版 App 从 4 小时标签锚点反推
          const parseMin = (t) => {
            const m = /^(\d{1,2}):(\d{2})$/.exec(t)
            return m ? Number(m[1]) * 60 + Number(m[2]) : null
          }
          let timeBase = null
          if (Array.isArray(timeLabels) && timeLabels.length > 0) {
            if (startTimeMinutes != null && Number(durationMinutes) > 0 && isFinite(Number(startTimeMinutes))) {
              timeBase = { anchorIdx: 0, anchorMin: Number(startTimeMinutes), minutesPerIndex: Number(durationMinutes) }
            } else {
              const anchor = timeLabels.find(l => parseMin(l.text) != null)
              if (anchor) {
                let minutesPerIndex = 30
                const second = timeLabels.find(l => l !== anchor && parseMin(l.text) != null && l.index !== anchor.index)
                if (second) {
                  const dm = (((parseMin(second.text) - parseMin(anchor.text)) % 1440) + 1440) % 1440
                  const di = second.index - anchor.index
                  if (dm > 0 && di > 0) minutesPerIndex = dm / di
                }
                timeBase = { anchorIdx: anchor.index, anchorMin: parseMin(anchor.text), minutesPerIndex }
              }
            }
          }

          // 高赤纬目标的周日运动圆很小（半径 ∝ cos 赤纬），固定时间间隔的标签会挤在一起。
          // 在 fov 档位基础上按"相邻标签的球面间距 ≥ fov 的 10%"逐档抽稀。
          const intervalTiers = [30, 60, 120, 240, 480, 720]
          const curveMinutesSpan = timeBase ? (rawIcrfPoints.length - 1) * timeBase.minutesPerIndex : 1440
          // 曲线自身的角半径：闭合小圆的弧长 = 2π·半径，所以 totalAngle/2π 就是半径
          // （≈ 90° − |赤纬|）。下面那条按角距抽稀的规则把标签当成沿曲线均匀铺开的"点"，
          // 没算标签文字的宽度；天极附近曲线绕成小圈，同样的角距在屏幕上会横向叠在一起，
          // 所以先按曲线尺寸补一档，再走角距抽稀。
          const curveRadiusDeg = (totalAngle / (2 * Math.PI)) * 180 / Math.PI
          const sizeBump = curveRadiusDeg <= 8 ? 2 : (curveRadiusDeg <= 15 ? 1 : 0)
          const labelIntervalForFov = (fovYRad) => {
            let ti = intervalTiers.indexOf(this.curveLabelIntervalMinutes(fovYRad))
            if (ti < 0) ti = 0
            ti = Math.min(intervalTiers.length - 1, ti + sizeBump)
            if (!(totalAngle > 0) || !(curveMinutesSpan > 0)) return intervalTiers[ti]
            const minSpacingRad = fovYRad * 0.10
            while (ti < intervalTiers.length - 1 &&
                   totalAngle * (intervalTiers[ti] / curveMinutesSpan) < minSpacingRad) {
              ti++
            }
            return intervalTiers[ti]
          }

          // 时间标签随 fov 加密：fov 越小间隔越细，最小 30 分钟。
          // 下发的 timeLabels 是 4 小时粒度锚点，据其推出任意索引对应的时刻。
          const getLabelsForFov = (fovYRad) => {
            if (!Array.isArray(timeLabels) || timeLabels.length === 0) return []
            const intervalMinutes = labelIntervalForFov(fovYRad)
            if (intervalMinutes === 240) return timeLabels
            if (intervalMinutes > 240) {
              // 4 小时锚点仍嫌密（高赤纬）：按整点对齐抽稀，兜底隔位取
              const filtered = timeLabels.filter(l => {
                const m = parseMin(l.text)
                return m != null && m % intervalMinutes === 0
              })
              if (filtered.length >= 2) return filtered
              const step = Math.max(1, Math.round(intervalMinutes / 240))
              return timeLabels.filter((l, i) => i % step === 0)
            }
            if (!timeBase) return timeLabels
            const { anchorIdx, anchorMin, minutesPerIndex } = timeBase
            const out = []
            const seen = new Set()
            for (let i = 0; i < rawIcrfPoints.length; i++) {
              const minutesReal = anchorMin + (i - anchorIdx) * minutesPerIndex
              // 对齐"最近整刻"而非要求相位恰好为零：曲线起点是真太阳时中午等
              // 非整刻时（断开盒子回落 GPS、定位与设备时区错配），原先的
              // minutes % interval === 0 一个采样点都命不中，放大到细档后
              // 时间标签（和画在标签处的箭头）整层消失
              const nearest = Math.round(minutesReal / intervalMinutes) * intervalMinutes
              if (Math.abs(minutesReal - nearest) > minutesPerIndex / 2) continue
              const minutes = ((nearest % 1440) + 1440) % 1440
              // 闭合圆首尾是同一时刻，只标一次
              if (seen.has(minutes)) continue
              seen.add(minutes)
              const hh = String(Math.floor(minutes / 60)).padStart(2, '0')
              const mm = String(minutes % 60).padStart(2, '0')
              out.push({ index: i, text: `${hh}:${mm}` })
            }
            return out
          }

          // 时间点：文本标签（随 fov 档位变化由 watch 重建）
          let buildLabelFeatures = null
          if (Array.isArray(timeLabels) && showLabels) {
            buildLabelFeatures = (currentFovY) => {
              const labelFeatures = []
              for (const lbl of getLabelsForFov(currentFovY)) {
                if (lbl.index < 0 || lbl.index >= rawIcrfPoints.length) continue
                const v2 = rawIcrfPoints[lbl.index]
                const tip = vecToRaDecDeg(v2)
                const lblColor = indexIsNight(lbl.index) && isAboveHorizon(v2) ? nightColor : color
                labelFeatures.push({
                  type: 'Feature',
                  properties: {
                    title: lbl.text,
                    fill: lblColor,
                    stroke: lblColor,
                    'fill-opacity': 0,
                    'text-size': 13,
                    'text-anchor': 'center',
                    'text-offset': [0, -20]
                  },
                  geometry: { type: 'Point', coordinates: tip }
                })
              }
              return labelFeatures
            }
          }

          // 箭头三角形：球面尺寸随 fov 缩放，封装成 builder 供 fov watch 重建
          let buildArrowFeatures = null
          if (Array.isArray(timeLabels) && showArrow && rawIcrfPoints.length >= 2) {
            buildArrowFeatures = (currentFovY) => {
              // 三角形大小按当前 fov 等比缩放（约占屏幕高度 2.4%），上限 4°
              const wingRad = Math.min(currentFovY * 0.024, 4 * toRad)
              const spreadRad = 22 * toRad
              const cw = Math.cos(wingRad); const sw = Math.sin(wingRad)
              const cs = Math.cos(spreadRad); const ss = Math.sin(spreadRad)
              const arrowFeatures = []

              // 与文本标签同一动态时间集合，箭头/标签一一对应
              for (const lbl of getLabelsForFov(currentFovY)) {
                if (lbl.index < 0 || lbl.index >= rawIcrfPoints.length) continue
                const v2 = rawIcrfPoints[lbl.index]
                const tip = vecToRaDecDeg(v2)
                const lblColor = indexIsNight(lbl.index) && isAboveHorizon(v2) ? nightColor : color

                // 箭头：用 (prev, lbl.index) 的方向构造 V 字形翼，箭尖在 lbl.index 处指向"未来"
                // index==0 时（如 12:00 起点）用闭合圆的 length-2 处作为 prev
                const prevIdx = lbl.index >= 1 ? lbl.index - 1 : rawIcrfPoints.length - 2
                const v1 = rawIcrfPoints[prevIdx]
                const dotProd = v2[0] * v1[0] + v2[1] * v1[1] + v2[2] * v1[2]
                let tx = -(v1[0] - dotProd * v2[0])
                let ty = -(v1[1] - dotProd * v2[1])
                let tz = -(v1[2] - dotProd * v2[2])
                const tLen = Math.sqrt(tx * tx + ty * ty + tz * tz) || 1
                tx /= tLen; ty /= tLen; tz /= tLen

                const bx = v2[1] * tz - v2[2] * ty
                const by = v2[2] * tx - v2[0] * tz
                const bz = v2[0] * ty - v2[1] * tx

                const makeWingVec = (sign) => {
                  const s = ss * sign
                  const dx = -cs * tx + s * bx
                  const dy = -cs * ty + s * by
                  const dz = -cs * tz + s * bz
                  return [
                    v2[0] * cw + dx * sw,
                    v2[1] * cw + dy * sw,
                    v2[2] * cw + dz * sw
                  ]
                }
                const vW1 = makeWingVec(+1)
                const vW2 = makeWingVec(-1)
                // 绕开 stellarium 在 iOS WebGL 上 Polygon fill 走 stencil 路径产生大色块的 bug：
                // 用 LineString 闭合三角形轮廓，边在球面上细分，视觉接近实心三角形
                const edgeSteps = 6
                const interpEdge = (vA, vB) => {
                  const arr = []
                  for (let k = 1; k <= edgeSteps; k++) {
                    arr.push(vecToRaDecDeg(slerp(vA, vB, k / edgeSteps)))
                  }
                  return arr
                }
                const triCoords = [
                  tip,
                  ...interpEdge(v2, vW1),
                  ...interpEdge(vW1, vW2),
                  ...interpEdge(vW2, v2)
                ]

                // 70% 观感用预混暗色（黑底下与 alpha 0.7 视觉等效）而非 fill-opacity：
                // iOS WebGL 上 Polygon 的半透明 fill 会走出问题的 stencil 路径，
                // 箭头直接消失（fill-opacity 必须保持 1）
                const dimArrowColor = (hex => {
                  const m = /^#([0-9a-fA-F]{6})/.exec(hex)
                  if (!m) return hex
                  const n = parseInt(m[1], 16)
                  const r = Math.round(((n >> 16) & 255) * 0.7)
                  const g = Math.round(((n >> 8) & 255) * 0.7)
                  const b = Math.round((n & 255) * 0.7)
                  return '#' + ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')
                })(lblColor)
                arrowFeatures.push({
                  type: 'Feature',
                  properties: {
                    fill: dimArrowColor,
                    stroke: dimArrowColor,
                    'fill-opacity': 1,
                    'stroke-width': 1
                  },
                  geometry: {
                    type: 'Polygon',
                    coordinates: [triCoords]
                  }
                })
              }
              return arrowFeatures
            }
          }

          // 中天标记：在曲线上目标过中天处画一个专色菱形 + 时刻文本，与橙色轨迹、绿色夜间段区分开
          let buildTransitFeatures = null
          const transitIdxNum = Number(transitIndex)
          if (transitColor && transitIndex != null && isFinite(transitIdxNum) && rawIcrfPoints.length >= 2) {
            // 中天时刻一般落在两个采样点之间，按小数索引在球面上插值取点
            const maxRawIdx = rawIcrfPoints.length - 1
            const clampedIdx = Math.min(maxRawIdx, Math.max(0, transitIdxNum))
            const ti0 = Math.floor(clampedIdx)
            const ti1 = Math.min(maxRawIdx, ti0 + 1)
            const tFrac = clampedIdx - ti0
            const vT = (ti0 === ti1 || tFrac < 1e-9)
              ? rawIcrfPoints[ti0]
              : slerp(rawIcrfPoints[ti0], rawIcrfPoints[ti1], tFrac)

            // 以中天点为极点构造球面正交基，用来摆出菱形的四个顶点
            const refV = Math.abs(vT[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]
            const dotRef = refV[0] * vT[0] + refV[1] * vT[1] + refV[2] * vT[2]
            let e1 = [refV[0] - dotRef * vT[0], refV[1] - dotRef * vT[1], refV[2] - dotRef * vT[2]]
            const e1Len = Math.sqrt(e1[0] * e1[0] + e1[1] * e1[1] + e1[2] * e1[2]) || 1
            e1 = [e1[0] / e1Len, e1[1] / e1Len, e1[2] / e1Len]
            const e2 = [
              vT[1] * e1[2] - vT[2] * e1[1],
              vT[2] * e1[0] - vT[0] * e1[2],
              vT[0] * e1[1] - vT[1] * e1[0]
            ]

            buildTransitFeatures = (currentFovY) => {
              // 菱形外接半径按 fov 等比缩放（约占屏幕高度 1.6%），上限 3°
              const rRad = Math.min(currentFovY * 0.016, 3 * toRad)
              const cr = Math.cos(rRad)
              const sr = Math.sin(rRad)
              const vertexAt = (dx, dy) => [
                vT[0] * cr + (e1[0] * dx + e2[0] * dy) * sr,
                vT[1] * cr + (e1[1] * dx + e2[1] * dy) * sr,
                vT[2] * cr + (e1[2] * dx + e2[2] * dy) * sr
              ]
              const corners = [vertexAt(1, 0), vertexAt(0, 1), vertexAt(-1, 0), vertexAt(0, -1)]
              // 边在球面上细分，大 fov 下菱形才不会走形（与箭头三角形同策略）
              const edgeSteps = 4
              const coords = []
              for (let i = 0; i < corners.length; i++) {
                const vA = corners[i]
                const vB = corners[(i + 1) % corners.length]
                coords.push(vecToRaDecDeg(vA))
                for (let k = 1; k < edgeSteps; k++) {
                  coords.push(vecToRaDecDeg(slerp(vA, vB, k / edgeSteps)))
                }
              }
              coords.push(coords[0])

              const transitFeatures = [{
                type: 'Feature',
                properties: {
                  fill: transitColor,
                  stroke: transitColor,
                  'fill-opacity': 1,
                  'stroke-width': 1
                },
                geometry: { type: 'Polygon', coordinates: [coords] }
              }]

              if (transitLabel) {
                // 文本挂在菱形下方，与整点时间标签（上方 -20）错开，避免叠字
                transitFeatures.push({
                  type: 'Feature',
                  properties: {
                    title: transitLabel,
                    fill: transitColor,
                    stroke: transitColor,
                    'fill-opacity': 0,
                    'text-size': 13,
                    'text-anchor': 'center',
                    'text-offset': [0, 24]
                  },
                  geometry: { type: 'Point', coordinates: vecToRaDecDeg(vT) }
                })
              }
              return transitFeatures
            }
          }

          // 先清除旧的 geojson 对象（如果存在）
          this.clearLines()

          // 获取或创建 layer
          let layer = this.$stel.getObj('jsbridge-lines')
          if (!layer) {
            layer = this.$stel.createLayer({
              id: 'jsbridge-lines',
              z: 40,
              visible: true
            })
          }
          layer.visible = true

          // 静态 obj：虚线轨迹
          const lineObj = this.$stel.createObj('geojson', {
            data: { type: 'FeatureCollection', features: features }
          })
          layer.add(lineObj)
          this.linesLayer = layer
          this.linesObj = lineObj

          const currentFovY = this.$store.state.stel.fov || (60 * toRad)

          // 动态 obj：三角形箭头（随 fov 变化由 watch 重建）
          // 先加箭头再加文本标签：layer 按添加顺序绘制，保证时间文字压在箭头上面
          if (buildArrowFeatures) {
            const arrowObj = this.$stel.createObj('geojson', {
              data: { type: 'FeatureCollection', features: buildArrowFeatures(currentFovY) }
            })
            layer.add(arrowObj)
            this.linesArrowObj = arrowObj
            this.linesArrowBuilder = buildArrowFeatures
          }

          // 动态 obj：中天菱形 + 时刻文本（随 fov 变化由 watch 重建）
          if (buildTransitFeatures) {
            const transitObj = this.$stel.createObj('geojson', {
              data: { type: 'FeatureCollection', features: buildTransitFeatures(currentFovY) }
            })
            layer.add(transitObj)
            this.linesTransitObj = transitObj
            this.linesTransitBuilder = buildTransitFeatures
          }

          // 动态 obj：时间文本标签（fov 档位变化时由 watch 重建）
          if (buildLabelFeatures) {
            const labelObj = this.$stel.createObj('geojson', {
              data: { type: 'FeatureCollection', features: buildLabelFeatures(currentFovY) }
            })
            layer.add(labelObj)
            this.linesLabelObj = labelObj
            this.linesLabelBuilder = buildLabelFeatures
            this.linesLabelIntervalFn = labelIntervalForFov
            this.linesLabelInterval = labelIntervalForFov(currentFovY)
          }
        },
        clearLines: () => {
          this.lastLinesData = null
          this.clearLines()
        }
      }
      // 取景 action 合入，基座已有的键不覆盖。两边重名等于两个实现抢一个名字，
      // 静态测试 bridge-actions.test.js 会拦，这里再拦一道运行时的。
      const framingActions = this.$refs.framing.actions()
      for (const name of Object.keys(framingActions)) {
        if (name in actions) throw new Error(`bridge action 重名：${name}`)
        actions[name] = framingActions[name]
      }
      jsbridge.registerActions(actions)
    },
    // 自定义地平线 set/show/clear 后重画缓存的曲线，使夜间色的地平线判定即时生效。
    // Flutter 侧 set+show 常被连续调用，用短延时合并成一次重画。
    scheduleLinesRedraw: function () {
      if (!this.lastLinesData) return
      if (this.linesRedrawTimer) clearTimeout(this.linesRedrawTimer)
      this.linesRedrawTimer = setTimeout(() => {
        this.linesRedrawTimer = null
        if (this.lastLinesData && window.StellariumActions) {
          window.StellariumActions.drawLines(this.lastLinesData)
        }
      }, 50)
    },
    // 连续缩放：每 b.timeout 毫秒按 b.speed 比例缩放一次，直到 stopZoom。
    // duration 是单次 zoomTo 的动画时长（秒）。递归带上原参数（修复旧版
    // this.zoomIn() 引用不存在方法且丢参的 TypeError）。
    startZoom: function (b, duration) {
      if (!b || isNaN(Number(b.speed))) return
      this.stopZoom()
      const currentFov = this.$store.state.stel.fov * 180 / Math.PI
      this.$stel.zoomTo(currentFov * b.speed * Math.PI / 180, duration)
      const interval = Number(b.timeout)
      if (interval > 0) {
        this.zoomTimeout = setTimeout(() => {
          this.startZoom(b, duration)
        }, interval)
      }
      this.updateState()
    },
    stopZoom: function () {
      if (this.zoomTimeout) {
        clearTimeout(this.zoomTimeout)
        this.zoomTimeout = null
      }
    },
    clearLines: function () {
      // remove() only drops the layer's reference; the createObj reference must
      // be released with destroy() or the geojson meshes leak (updateArrows
      // rebuilds the arrow ~every fov tick during a pinch-zoom).
      if (this.linesLayer) {
        if (this.linesObj) { this.linesLayer.remove(this.linesObj); this.linesObj.destroy() }
        if (this.linesLabelObj) { this.linesLayer.remove(this.linesLabelObj); this.linesLabelObj.destroy() }
        if (this.linesArrowObj) { this.linesLayer.remove(this.linesArrowObj); this.linesArrowObj.destroy() }
        if (this.linesTransitObj) { this.linesLayer.remove(this.linesTransitObj); this.linesTransitObj.destroy() }
        this.linesLayer.visible = false
      }
      this.linesObj = null
      this.linesLabelObj = null
      this.linesLabelBuilder = null
      this.linesLabelInterval = null
      this.linesLabelIntervalFn = null
      this.linesArrowObj = null
      this.linesArrowBuilder = null
      this.linesTransitObj = null
      this.linesTransitBuilder = null
    },
    // fov（弧度）→ 升降曲线时间标签间隔（分钟）：fov 越小越精细，最小半小时
    curveLabelIntervalMinutes: function (fovYRad) {
      const fovDeg = fovYRad * 180 / Math.PI
      if (fovDeg > 90) return 240
      if (fovDeg > 40) return 120
      if (fovDeg > 20) return 60
      return 30
    },
    updateArrows: function () {
      if (!this.linesLayer) return
      const currentFovY = this.$store.state.stel.fov || (60 * Math.PI / 180)

      // 时间标签只在 fov 档位（间隔）变化时重建，避免缩放过程中每帧重建
      if (this.linesLabelBuilder) {
        const interval = this.linesLabelIntervalFn
          ? this.linesLabelIntervalFn(currentFovY)
          : this.curveLabelIntervalMinutes(currentFovY)
        if (interval !== this.linesLabelInterval) {
          this.linesLabelInterval = interval
          const newLabelObj = this.$stel.createObj('geojson', {
            data: { type: 'FeatureCollection', features: this.linesLabelBuilder(currentFovY) }
          })
          this.linesLayer.add(newLabelObj)
          if (this.linesLabelObj) {
            this.linesLayer.remove(this.linesLabelObj)
            this.linesLabelObj.destroy()
          }
          this.linesLabelObj = newLabelObj
        }
      }

      if (this.linesArrowBuilder) {
        const newArrowObj = this.$stel.createObj('geojson', {
          data: { type: 'FeatureCollection', features: this.linesArrowBuilder(currentFovY) }
        })
        this.linesLayer.add(newArrowObj)
        if (this.linesArrowObj) {
          this.linesLayer.remove(this.linesArrowObj)
          this.linesArrowObj.destroy()
        }
        this.linesArrowObj = newArrowObj
      }

      // 中天菱形同样按 fov 等比缩放，跟着一起重建
      if (this.linesTransitBuilder) {
        const newTransitObj = this.$stel.createObj('geojson', {
          data: { type: 'FeatureCollection', features: this.linesTransitBuilder(currentFovY) }
        })
        this.linesLayer.add(newTransitObj)
        if (this.linesTransitObj) {
          this.linesLayer.remove(this.linesTransitObj)
          this.linesTransitObj.destroy()
        }
        this.linesTransitObj = newTransitObj
      }

      // 新箭头 / 中天 obj 追加在 layer 末尾会盖到文字上面，把时间文本重新置顶
      if (this.linesLabelObj) {
        this.linesLayer.remove(this.linesLabelObj)
        this.linesLayer.add(this.linesLabelObj)
      }
    },
    getLocalTime: function () {
      // 只有通过 jsbridge 调用 setDateTime 设置过时间才返回时间值
      if (!this.hasSetDateTime) {
        return null
      }
      if (this.$store.state.stel.observer.utc == null) {
        return null
      }
      var d = new Date()
      d.setMJD(this.$store.state.stel.observer.utc)
      const m = Moment(d)
      // 转换成毫秒值
      return m.utc().toDate().getTime()
    },
    // 获取中心点的坐标（alt/az 地平坐标 + ra/dec 赤道坐标）
    getCenterRaDecValue: function () {
      const that = this

      const formatDec = function (a) {
        const raf = that.$stel.a2af(a, 1)
        // 正确转换：十进制度 = degrees + arcminutes/60 + arcseconds/3600
        const decimalDegrees = Math.abs(raf.degrees) + raf.arcminutes / 60 + raf.arcseconds / 3600
        return raf.sign === '-' ? -decimalDegrees : decimalDegrees
      }
      const formatAz = function (a) {
        const raf = that.$stel.a2af(a, 1)
        // 正确转换：十进制度 = degrees + arcminutes/60 + arcseconds/3600
        const degrees = raf.degrees < 0 ? raf.degrees + 360 : raf.degrees
        return degrees + raf.arcminutes / 60 + raf.arcseconds / 3600
      }
      const formatRA = function (a) {
        const raf = that.$stel.a2tf(a, 1)
        // 正确转换：十进制小时 = hours + minutes/60 + seconds/3600
        return raf.hours + raf.minutes / 60 + raf.seconds / 3600
      }

      let vIcrf
      // 如果有选中的天体（锁定状态），直接使用天体的 ICRF 坐标以避免转换误差
      if (this.$stel.core.selection) {
        const obj = this.$stel.core.selection
        vIcrf = obj.getInfo('radec')
      } else {
        // 没有锁定时，使用 VIEW frame 的中心 (0,0,-1) 转换获取
        const vView = [0, 0, -1] // VIEW frame 中心方向
        const vObs = this.$stel.convertFrame(this.$stel.core.observer, 'VIEW', 'OBSERVED', vView)
        vIcrf = this.$stel.convertFrame(this.$stel.core.observer, 'OBSERVED', 'ICRF', vObs)
      }

      // 计算 Alt/Az（从 ICRF 转换到 OBSERVED）
      const vObs = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'OBSERVED', vIcrf)
      const azalt = this.$stel.c2s(vObs)

      // 计算 J2000 (ICRF)
      const radecIcrf = this.$stel.c2s(vIcrf)
      const raIcrf = this.$stel.anp(radecIcrf[0])
      const decIcrf = this.$stel.anpm(radecIcrf[1])

      // 计算 JNow
      const vJnow = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'JNOW', vIcrf)
      const radecJnow = this.$stel.c2s(vJnow)
      const raJnow = this.$stel.anp(radecJnow[0])
      const decJnow = this.$stel.anpm(radecJnow[1])

      const result = {
        az: formatAz(this.$stel.anp(azalt[0])),
        alt: formatDec(this.$stel.anpm(azalt[1])),
        ra: formatRA(raJnow),
        dec: formatDec(decJnow),
        ra_j2000: formatRA(raIcrf),
        dec_j2000: formatDec(decIcrf)
      }
      return result
    },
    setLocation: function (loc) {
      // 确保 loc 包含必要字段
      const location = {
        short_name: loc.short_name || 'Unknown',
        country: loc.country || 'Unknown',
        street_address: loc.street_address || '',
        lat: Number(loc.lat),
        lng: Number(loc.lng),
        alt: Number(loc.alt) || 0,
        accuracy: Number(loc.accuracy) || 1
      }
      this.$store.commit('setCurrentLocation', location)
    },
    setNightMode: function (b) {
      // Set to the requested state (not toggle): this is called from the App
      // with an explicit value, so toggling would invert on a repeated call.
      this.$store.commit('setValue', { varName: 'nightmode', newValue: b })
      if (window.navigator.userAgent.indexOf('Edge') > -1) {
        document.getElementById('nightmode').style.opacity = b ? '0.5' : '0'
      }
      document.getElementById('nightmode').style.visibility = b ? 'visible' : 'hidden'
      // Tell the engine, so selected-object labels/markers paint white and the
      // #FF6C20 overlay renders them as #FF6C20 (not a doubled dark red).
      if (this.$stel && this.$stel.core) {
        this.$stel.core.nightmode = b
      }
    }
  }
}
</script>
