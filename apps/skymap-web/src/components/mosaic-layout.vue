// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>
  <div
    v-if="visible"
    class="mosaic-layout"
    style="position: absolute; inset: 0; pointer-events: none;"
  >
    <div
      v-for="tile in drawn"
      :key="tile.key"
      :style="tile.style"
      :data-key="tile.key"
      class="mosaic-layout-tile"
      @pointerdown="onDown($event, tile)"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onCancel"
    >
      <svg
        v-if="tile.kind === 'disabled'"
        :width="iconSize(tile)"
        :height="iconSize(tile)"
        viewBox="0 0 24 24"
        :style="{ transform: `rotate(${-tile.rotation}deg)` }"
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          fill="none"
          :stroke="colors.disabled"
          stroke-width="2"
        />
        <line
          x1="5.6"
          y1="18.4"
          x2="18.4"
          y2="5.6"
          :stroke="colors.disabled"
          stroke-width="2"
        />
      </svg>
      <span
        v-else-if="tile.kind === 'slot'"
        :style="{ color: 'rgba(255, 255, 255, 0.6)', fontSize: '22px', fontWeight: 'normal', transform: `rotate(${-tile.rotation}deg)` }"
      >+</span>
      <span
        v-else-if="tile.label"
        :style="{ color: tile.color, fontSize: '15px', fontWeight: 'bold', fontFamily: '\'SkyFont\', sans-serif', transform: `rotate(${-tile.rotation}deg)` }"
      >{{ tile.label }}</span>
      <template v-if="tile.state === 'selected'">
        <div
          v-for="c in corners"
          :key="c"
          :style="cornerStyle(c, tile)"
        />
      </template>
    </div>
    <div
      v-if="dragGrid && outline"
      :style="outline"
    />
    <framing-ring
      v-if="ring"
      :angle-to-north="anchorAngleToNorth"
      :target-pa="gridPa"
      :zero-pa="0"
      :ring-radius="ringRadius"
      :absolute-label="true"
      @rotate="onRingRotate"
    />
  </div>
</template>
<script>
// 可编辑马赛克：网格钉在天上（锚点 = 网格中心的天球坐标），格子可点（停用 / 恢复 / 补格）、可拖（整网格；
// 宿主开 tileEdit 时长按单格后只拖这一格），马赛克态的角度圆环。只负责画与报手势，版面数据的真源在宿主：
// 拖动中本地先跟手，结束时报 phase:'end'，宿主写回后再下发一次 showMosaicLayout 对齐。
// 对 framing-overlay.vue 暴露：show(cfg) / hide() / focus(opts) / centers() / onBackgroundClick() / stateFields()
import jsbridge from '@/utils/jsbridge'
import FramingRing from './framing-ring.vue'
import { mosaicSkyOffset, tangentPlaneToRaDec } from './mosaic-math'
import {
  gridCoord, screenFromView, viewFromScreen, screenDeltaToGrid, pressMode, tileHittable,
  fitScale, normalizeTile, LONG_PRESS_MS
} from './mosaic-layout-math'

const D2R = Math.PI / 180
const DEFAULT_COLORS = { normal: '#F48123', disabled: '#FF3F3F', warn: '#FFD60A' }
// 拖动中往宿主报位置的节流（结束时一定报一次）
const MOVE_REPORT_MS = 100

export default {
  components: { FramingRing },
  data () {
    return {
      visible: false,
      // 版面：宿主下发，拖动时本地改 center / 单格 dx dy
      center: null, // { ra: 小时, dec: 度 }
      gridPa: 0,
      fovX: 1,
      fovY: 1,
      overlap: 10,
      cols: 1,
      rows: 1,
      tiles: [],
      editing: true,
      tileEdit: false,
      ring: false,
      ringRadius: null,
      colors: { ...DEFAULT_COLORS },
      // 渲染结果（每帧刷新）
      drawn: [],
      anchorScreen: null,
      anchorAngleToNorth: 0,
      rotation: 0,
      stepPx: [1, 1],
      outline: null,
      press: null,
      dragGrid: false,
      lastReport: 0,
      fitPending: false,
      tooSmall: false,
      animId: null,
      corners: ['tl', 'tr', 'br', 'bl']
    }
  },
  beforeUnmount () {
    this.stopLoop()
    this.clearPress()
  },
  methods: {
    // ── 对 framing-overlay.vue 的接口 ──────────────────────────────────
    show (cfg) {
      if (!cfg || typeof cfg !== 'object') return false
      const cols = Math.round(Number(cfg.cols))
      const rows = Math.round(Number(cfg.rows))
      const fovX = Number(cfg.fovX)
      const fovY = Number(cfg.fovY)
      const overlap = Number(cfg.overlap) || 0
      if (!(cols >= 1 && rows >= 1 && fovX > 0 && fovY > 0 && overlap >= 0 && overlap < 100)) {
        console.warn('showMosaicLayout: invalid config', cfg)
        return false
      }
      const tiles = Array.isArray(cfg.tiles) ? cfg.tiles.map(normalizeTile).filter(Boolean) : []
      // 拖动中宿主的回写不覆盖本地跟手的位置（按压结束后宿主会再下发一次）
      if (!this.press) {
        const c = cfg.center
        const ra = c ? Number(c.ra) : NaN
        const dec = c ? Number(c.dec) : NaN
        if (Number.isFinite(ra) && Number.isFinite(dec)) {
          this.center = { ra, dec }
        } else if (!this.center || cfg.recenter) {
          this.center = this.screenCenterRaDec()
          if (this.center) jsbridge.postMessage('mosaicMove', { center: this.center, phase: 'end' })
        }
        this.tiles = tiles
      }
      this.cols = cols
      this.rows = rows
      this.fovX = fovX
      this.fovY = fovY
      this.overlap = overlap
      this.gridPa = Number.isFinite(Number(cfg.gridPa)) ? Number(cfg.gridPa) : 0
      this.editing = cfg.editing !== false
      this.tileEdit = cfg.tileEdit === true
      this.ring = cfg.ring === true
      this.ringRadius = Number(cfg.ringRadius) > 0 ? Number(cfg.ringRadius) : null
      this.colors = { ...DEFAULT_COLORS, ...(cfg.colors || {}) }
      this.fitPending = cfg.fit === true
      this.visible = true
      this.update()
      this.startLoop()
      return true
    },
    hide () {
      this.clearPress()
      this.tooSmall = false
      this.visible = false
      this.drawn = []
      this.ring = false
      this.stopLoop()
    },
    // 把视图转到锚点。lock = 跟踪锁住（圆环要锚点一直在屏幕中心）；否则转到后放开
    focus (opts) {
      if (!this.center || !this.$stel) return
      const duration = opts && opts.duration !== undefined ? Number(opts.duration) : 0.5
      const icrf = this.$stel.s2c(this.center.ra * 15 * D2R, this.center.dec * D2R)
      const jnow = this.$stel.convertFrame(this.$stel.core.observer, 'ICRF', 'JNOW', icrf)
      const coords = this.$stel.createObj('coordinates', { pos: jnow })
      this.$stel.pointAndLock(coords, duration)
      if (!(opts && opts.lock)) {
        setTimeout(() => { if (this.$stel && this.$stel.core) this.$stel.core.lock = 0 }, duration * 1000 + 50)
      }
    },
    // 入库用：只回启用格，按宿主给的编号排
    centers () {
      return this.drawn
        .filter(t => t.kind === 'enabled')
        .map(t => ({ index: Number(t.label) || 0, key: t.key, ra: t.ra, dec: t.dec, az: t.az, alt: t.alt, pa: this.gridPa }))
        .sort((a, b) => a.index - b.index)
    },
    // 引擎单击（格子以外）：单格编辑态下告诉宿主退出选中，并吃掉这次点击（不选中星体）
    onBackgroundClick () {
      if (!this.visible || !this.editing) return false
      if (!this.tiles.some(t => t.state === 'selected')) return false
      jsbridge.postMessage('mosaicBackgroundTap', {})
      return true
    },
    stateFields () {
      return { showMosaicLayout: this.visible }
    },
    // ── 渲染 ────────────────────────────────────────────────────────────
    startLoop () {
      if (this.animId) return
      const tick = () => {
        if (!this.visible) { this.animId = null; return }
        this.update()
        this.animId = requestAnimationFrame(tick)
      }
      this.animId = requestAnimationFrame(tick)
    },
    stopLoop () {
      if (this.animId) cancelAnimationFrame(this.animId)
      this.animId = null
    },
    fovYRad () {
      const canvas = this.$stel.canvas
      const fov = this.$store.state.stel.fov
      const aspect = canvas.width / canvas.height
      return aspect < 1 ? 4 * Math.atan(Math.tan(fov / 4) / aspect) : fov
    },
    project (raHours, decDeg) {
      const obs = this.$stel.core.observer
      const v = this.$stel.convertFrame(obs, 'ICRF', 'VIEW', this.$stel.s2c(raHours * 15 * D2R, decDeg * D2R))
      const { clientWidth, clientHeight } = this.$stel.canvas
      return screenFromView(v, clientWidth, clientHeight, this.fovYRad())
    },
    unproject (sx, sy) {
      const { clientWidth, clientHeight } = this.$stel.canvas
      const v = viewFromScreen(sx, sy, clientWidth, clientHeight, this.fovYRad())
      const icrf = this.$stel.convertFrame(this.$stel.core.observer, 'VIEW', 'ICRF', v)
      const s = this.$stel.c2s(icrf)
      return { ra: this.$stel.anp(s[0]) / D2R / 15, dec: s[1] / D2R }
    },
    screenCenterRaDec () {
      if (!this.$stel || !this.$stel.canvas) return null
      const { clientWidth, clientHeight } = this.$stel.canvas
      return this.unproject(clientWidth / 2, clientHeight / 2)
    },
    update () {
      if (!this.visible || !this.$stel || !this.$stel.canvas || !this.center) return
      const { clientWidth: W, clientHeight: H } = this.$stel.canvas
      const fovYCur = this.fovYRad()
      const { ra, dec } = this.center
      const a = this.project(ra, dec)
      if (!a) { this.drawn = []; return }
      // 锚点处北向的屏幕角：往北挪一点再投影
      const n = this.project(ra, Math.min(dec + 0.01, 90))
      const north = n ? Math.atan2(n[1] - a[1], n[0] - a[0]) * 180 / Math.PI + 90 : 0
      this.anchorScreen = a
      this.anchorAngleToNorth = north
      this.rotation = north - this.gridPa
      const tileW = H * Math.tan(this.fovX * D2R / 4) / Math.tan(fovYCur / 4)
      const tileH = H * Math.tan(this.fovY * D2R / 4) / Math.tan(fovYCur / 4)
      const k = 1 - this.overlap / 100
      this.stepPx = [tileW * k, tileH * k]
      const planeX = 2 * Math.tan(this.fovX * D2R / 2) * k
      const planeY = 2 * Math.tan(this.fovY * D2R / 2) * k
      const hittable = this.editing && tileHittable(tileW, tileH)
      // 易达性（plan_b R2）：格子太小不接手手势，状态变化时告诉宿主（宿主提示放大星图）
      const small = this.editing && !hittable
      if (small !== this.tooSmall) {
        this.tooSmall = small
        jsbridge.postMessage('mosaicHittable', { hittable: !small })
      }
      const obs = this.$stel.core.observer
      const ra0 = ra * 15 * D2R
      const dec0 = dec * D2R
      let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity
      const out = []
      for (const t of this.tiles) {
        const { gx, gy } = gridCoord(t, this.cols, this.rows)
        const { north: dn, east: de } = mosaicSkyOffset(gx * planeX, gy * planeY, this.gridPa)
        const sky = tangentPlaneToRaDec(ra0, dec0, de, dn)
        const raH = this.$stel.anp(sky.ra) / D2R / 15
        const decD = sky.dec / D2R
        const p = this.project(raH, decD)
        if (!p) continue
        const vObs = this.$stel.convertFrame(obs, 'ICRF', 'OBSERVED', this.$stel.s2c(sky.ra, sky.dec))
        const azalt = this.$stel.c2s(vObs)
        const kind = t.state === 'slot' ? 'slot' : (t.enabled ? 'enabled' : 'disabled')
        const color = kind === 'disabled' ? this.colors.disabled : (t.state === 'warn' ? this.colors.warn : this.colors.normal)
        const sel = t.state === 'selected'
        if (kind !== 'slot') {
          const r = this.rotation * D2R
          for (const [cx, cy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
            const x = p[0] + (cx * tileW / 2) * Math.cos(r) - (cy * tileH / 2) * Math.sin(r)
            const y = p[1] + (cx * tileW / 2) * Math.sin(r) + (cy * tileH / 2) * Math.cos(r)
            minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y)
          }
        }
        let border; let background
        if (kind === 'slot') {
          border = '1px dashed rgba(255, 255, 255, 0.35)'
          background = 'rgba(255, 255, 255, 0.04)'
        } else if (kind === 'disabled') {
          border = `1px dashed ${color}`
          background = 'rgba(255, 63, 63, 0.04)'
        } else {
          border = `${sel ? 2 : 1}px ${sel ? 'solid' : 'dashed'} ${color}`
          background = t.state === 'warn' ? 'rgba(255, 214, 10, 0.07)' : 'rgba(244, 129, 35, 0.05)'
        }
        const inset = kind === 'slot' ? 6 : 0
        out.push({
          key: t.key,
          kind,
          state: t.state,
          label: t.label,
          color,
          rotation: this.rotation,
          w: tileW,
          h: tileH,
          ra: raH,
          dec: decD,
          az: this.$stel.anp(azalt[0]) / D2R,
          alt: azalt[1] / D2R,
          style: {
            position: 'absolute',
            left: p[0] + 'px',
            top: p[1] + 'px',
            width: (tileW - 2 * inset) + 'px',
            height: (tileH - 2 * inset) + 'px',
            transform: `translate(-50%, -50%) rotate(${this.rotation}deg) translateZ(0)`,
            border,
            borderRadius: kind === 'slot' ? '8px' : '0',
            background,
            boxSizing: 'border-box',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: kind === 'disabled' ? 0.85 : 1,
            pointerEvents: hittable ? 'auto' : 'none',
            touchAction: 'none'
          }
        })
      }
      this.drawn = out
      if (this.dragGrid && Number.isFinite(minX)) {
        // 拖动中的外接框（实线），提示「整个网格在动」
        const r = this.rotation
        const w = (this.cols - 1) * this.stepPx[0] + tileW
        const h = (this.rows - 1) * this.stepPx[1] + tileH
        this.outline = {
          position: 'absolute', left: a[0] + 'px', top: a[1] + 'px', width: w + 'px', height: h + 'px',
          transform: `translate(-50%, -50%) rotate(${r}deg)`, border: `2px solid ${this.colors.normal}`,
          boxSizing: 'border-box', pointerEvents: 'none'
        }
      }
      if (this.fitPending && Number.isFinite(minX)) {
        this.fitPending = false
        const s = fitScale(maxX - minX, maxY - minY, W, H)
        if (s > 1.01) {
          const newTan = Math.tan(fovYCur / 4) * s
          const fov = 4 * Math.atan(newTan)
          if (fov <= Math.PI) this.$stel.zoomTo(fov, 0.5)
        }
      }
    },
    iconSize (tile) {
      return Math.max(14, Math.min(28, Math.min(tile.w, tile.h) * 0.35))
    },
    cornerStyle (c, tile) {
      const s = 8
      const pos = { tl: { left: -s / 2, top: -s / 2 }, tr: { right: -s / 2, top: -s / 2 }, br: { right: -s / 2, bottom: -s / 2 }, bl: { left: -s / 2, bottom: -s / 2 } }[c]
      const st = { position: 'absolute', width: s + 'px', height: s + 'px', background: tile.color, pointerEvents: 'none' }
      for (const k of Object.keys(pos)) st[k] = pos[k] + 'px'
      return st
    },
    // ── 手势 ────────────────────────────────────────────────────────────
    onDown (e, tile) {
      if (!this.editing || this.press) return
      if (e.target && e.target.setPointerCapture) {
        try { e.currentTarget.setPointerCapture(e.pointerId) } catch (_) { /* happy-dom / 旧 WebView */ }
      }
      const src = this.tiles.find(t => t.key === tile.key)
      this.press = {
        id: e.pointerId,
        key: tile.key,
        x0: e.clientX,
        y0: e.clientY,
        anchor0: this.anchorScreen ? [...this.anchorScreen] : null,
        mode: tile.state === 'selected' && this.tileEdit ? 'tile-armed' : 'pending',
        slot: tile.kind === 'slot',
        dx0: src ? src.dx : 0,
        dy0: src ? src.dy : 0,
        timer: null
      }
      if (this.tileEdit && !this.press.slot && this.press.mode === 'pending') {
        this.press.timer = setTimeout(() => {
          if (!this.press || this.press.mode !== 'pending') return
          this.press.mode = 'tile-armed'
          jsbridge.postMessage('mosaicTileLongPress', { key: this.press.key })
        }, LONG_PRESS_MS)
      }
    },
    onMove (e) {
      const p = this.press
      if (!p || e.pointerId !== p.id) return
      const ddx = e.clientX - p.x0
      const ddy = e.clientY - p.y0
      const moved = Math.hypot(ddx, ddy)
      if (p.mode === 'pending') {
        if (pressMode(moved) !== 'drag') return
        if (p.slot) { p.mode = 'cancel'; return }
        p.mode = 'grid'
        this.dragGrid = true
        if (p.timer) { clearTimeout(p.timer); p.timer = null }
      } else if (p.mode === 'tile-armed') {
        if (pressMode(moved) !== 'drag') return
        p.mode = 'tile'
      }
      if (p.mode === 'grid' && p.anchor0) {
        const c = this.unproject(p.anchor0[0] + ddx, p.anchor0[1] + ddy)
        if (c && Number.isFinite(c.ra) && Number.isFinite(c.dec)) this.center = c
        this.report('mosaicMove', { center: this.center, phase: 'move' })
      } else if (p.mode === 'tile') {
        const g = screenDeltaToGrid(ddx, ddy, this.rotation, this.stepPx[0], this.stepPx[1])
        const t = this.tiles.find(x => x.key === p.key)
        if (t) {
          t.dx = p.dx0 + g.gx
          t.dy = p.dy0 + g.gy
          this.report('mosaicTileMove', { key: t.key, dx: t.dx, dy: t.dy, phase: 'move' })
        }
      }
    },
    onUp (e) {
      const p = this.press
      if (!p || e.pointerId !== p.id) return
      if (p.mode === 'pending') {
        jsbridge.postMessage('mosaicTileTap', { key: p.key })
      } else if (p.mode === 'grid') {
        jsbridge.postMessage('mosaicMove', { center: this.center, phase: 'end' })
      } else if (p.mode === 'tile') {
        const t = this.tiles.find(x => x.key === p.key)
        if (t) jsbridge.postMessage('mosaicTileMove', { key: t.key, dx: t.dx, dy: t.dy, phase: 'end' })
      }
      this.clearPress()
    },
    onCancel (e) {
      const p = this.press
      if (!p || e.pointerId !== p.id) return
      // 被系统打断：拖动按结束处理（位置已经变了，宿主要知道）
      if (p.mode === 'grid') jsbridge.postMessage('mosaicMove', { center: this.center, phase: 'end' })
      this.clearPress()
    },
    clearPress () {
      if (this.press && this.press.timer) clearTimeout(this.press.timer)
      this.press = null
      this.dragGrid = false
      this.outline = null
    },
    report (action, data) {
      const now = Date.now()
      if (now - this.lastReport < MOVE_REPORT_MS) return
      this.lastReport = now
      jsbridge.postMessage(action, data)
    },
    onRingRotate (pa) {
      this.gridPa = pa
      jsbridge.postMessage('mosaicRotate', { gridPa: pa })
    }
  }
}
</script>
