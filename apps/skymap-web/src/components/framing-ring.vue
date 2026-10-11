<!--
SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd

This program is licensed under the terms of the GNU AGPL v3.
The terms of the AGPL v3 license can be found in the main directory of this
repository.
-->
<template>
  <div
    data-test="ring-root"
    :style="{ position: 'absolute', left: 0, top: 0, width: vw + 'px', height: vh + 'px', pointerEvents: 'none', opacity: busy ? 0.3 : 1 }"
  >
    <svg :width="vw" :height="vh" style="position: absolute; left: 0; top: 0; overflow: visible;">
      <!-- 圆环与刻度同一条 path、一次描边：交叠处不叠色，不出亮点 -->
      <path data-test="ring-path" :d="ringPath" fill="none" stroke="#fff" stroke-width="1.5" :stroke-opacity="pressed ? 0.5 : 0.3" />
      <path v-if="arcPath" data-test="ring-arc" :d="arcPath" fill="none" stroke="rgba(244, 129, 35, 0.7)" stroke-width="3" stroke-linecap="round" />
      <path :d="zeroTickPath" stroke="rgba(255, 255, 255, 0.9)" stroke-width="2" stroke-linecap="round" />
      <template v-if="showHints && !busy">
        <g v-for="h in hintPaths" :key="h.key" data-test="ring-hint">
          <path :d="h.d" fill="none" stroke="rgba(255, 255, 255, 0.5)" stroke-width="1.5" stroke-linecap="round" />
          <text :x="h.tx" :y="h.ty" text-anchor="middle" dominant-baseline="central" fill="rgba(255, 255, 255, 0.5)" font-size="14" font-weight="bold">{{ h.sign }}</text>
        </g>
      </template>
      <!-- 圆环带热区：透明粗描边，只认描边上的指针 -->
      <circle
        data-test="ring-band"
        :cx="cx" :cy="cy" :r="r" fill="none" stroke="transparent" :stroke-width="HIT_BAND * 2"
        :style="{ pointerEvents: busy ? 'none' : 'stroke', touchAction: 'none' }"
        @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"
      />
    </svg>
    <!-- 56×56 热区包着可见标签 -->
    <div
      :style="tagHitStyle"
      @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"
    >
      <div data-test="ring-tag" :style="tagStyle">{{ label }}</div>
    </div>
  </div>
</template>
<script>
import {
  HIT_BAND, ringRadius, norm360, displayDelta, deltaLabel, screenAngleOfPa,
  tagTextRotation, pointerBearing, bearingDelta, pointOnRing
} from './framing-ring-math'

const ORANGE = '#F48123'
const GREEN = 'rgb(42, 187, 57)'

export default {
  props: {
    angleToNorth: { type: Number, default: 0 },
    targetPa: { type: Number, default: 0 },
    zeroPa: { type: Number, default: 0 },
    busy: { type: Boolean, default: false },
    showHints: { type: Boolean, default: false }
  },
  emits: ['rotate', 'drag-start'],
  data () {
    return { vw: window.innerWidth, vh: window.innerHeight, pressed: false, drag: null, HIT_BAND }
  },
  computed: {
    cx () { return this.vw / 2 },
    cy () { return this.vh / 2 },
    r () { return ringRadius(this.vw, this.vh) },
    zeroBearing () { return screenAngleOfPa(this.angleToNorth, this.zeroPa) },
    tagBearing () { return screenAngleOfPa(this.angleToNorth, this.targetPa) },
    delta () { return displayDelta(this.zeroPa, this.targetPa) },
    aligned () { return Math.abs(this.delta) <= 1 },
    label () { return deltaLabel(this.delta) },
    ringPath () {
      const { cx, cy, r } = this
      let d = `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`
      for (let a = 0; a < 360; a += 10) {
        const len = a % 90 === 0 ? 8 : 4
        const [x0, y0] = pointOnRing(cx, cy, r, this.zeroBearing + a)
        const [x1, y1] = pointOnRing(cx, cy, r - len, this.zeroBearing + a)
        d += `M${x0} ${y0}L${x1} ${y1}`
      }
      return d
    },
    zeroTickPath () {
      const [x0, y0] = pointOnRing(this.cx, this.cy, this.r + 7, this.zeroBearing)
      const [x1, y1] = pointOnRing(this.cx, this.cy, this.r - 7, this.zeroBearing)
      return `M${x0} ${y0}L${x1} ${y1}`
    },
    arcPath () {
      if (this.aligned) return null
      const from = this.zeroBearing
      const to = from + this.delta
      const [x0, y0] = pointOnRing(this.cx, this.cy, this.r, from)
      const [x1, y1] = pointOnRing(this.cx, this.cy, this.r, to)
      const large = Math.abs(this.delta) > 180 ? 1 : 0
      const sweep = this.delta > 0 ? 1 : 0
      return `M${x0} ${y0}A${this.r} ${this.r} 0 ${large} ${sweep} ${x1} ${y1}`
    },
    hintPaths () {
      const R = this.r + 16
      return [1, -1].map(sgn => {
        const a0 = this.tagBearing + sgn * 16
        const a1 = this.tagBearing + sgn * 34
        const [x0, y0] = pointOnRing(this.cx, this.cy, R, a0)
        const [x1, y1] = pointOnRing(this.cx, this.cy, R, a1)
        // 箭头两翼：沿切线往回 6
        const [w0x, w0y] = pointOnRing(this.cx, this.cy, R - 5, a1 - sgn * 4)
        const [w1x, w1y] = pointOnRing(this.cx, this.cy, R + 5, a1 - sgn * 4)
        const [tx, ty] = pointOnRing(this.cx, this.cy, this.r + 34, this.tagBearing + sgn * 28)
        return {
          key: sgn,
          d: `M${x0} ${y0}A${R} ${R} 0 0 ${sgn > 0 ? 1 : 0} ${x1} ${y1}M${w0x} ${w0y}L${x1} ${y1}L${w1x} ${w1y}`,
          tx,
          ty,
          sign: sgn > 0 ? '+' : '−'
        }
      })
    },
    tagCenter () { return pointOnRing(this.cx, this.cy, this.r, this.tagBearing) },
    tagHitStyle () {
      const [x, y] = this.tagCenter
      return {
        position: 'absolute', left: (x - 28) + 'px', top: (y - 28) + 'px', width: '56px', height: '56px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        pointerEvents: this.busy ? 'none' : 'auto', touchAction: 'none', cursor: 'grab'
      }
    },
    tagStyle () {
      return {
        minWidth: '64px', height: '32px', padding: '0 12px', boxSizing: 'border-box',
        borderRadius: '16px', background: 'rgba(30, 30, 30, 0.92)', border: '1px solid rgba(255, 255, 255, 0.12)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', whiteSpace: 'nowrap',
        color: this.aligned ? GREEN : ORANGE, fontSize: '15px', fontWeight: 'bold',
        fontFamily: "'SkyFont', sans-serif", fontVariantNumeric: 'tabular-nums',
        transform: `rotate(${tagTextRotation(this.tagBearing)}deg) scale(${this.pressed ? 1.15 : 1})`,
        // 按压 100 / 松开 200，同 App AppMotion.pressDown / pressUp
        transition: `transform ${this.pressed ? 100 : 200}ms`,
        pointerEvents: 'none'
      }
    }
  },
  mounted () { window.addEventListener('resize', this.onResize) },
  beforeUnmount () { window.removeEventListener('resize', this.onResize) },
  methods: {
    onResize () { this.vw = window.innerWidth; this.vh = window.innerHeight },
    onDown (e) {
      if (this.busy) return
      if (e.target.setPointerCapture) e.target.setPointerCapture(e.pointerId)
      this.drag = { id: e.pointerId, last: pointerBearing(e.clientX, e.clientY, this.cx, this.cy), raw: this.targetPa, sent: norm360(Math.round(this.targetPa)) }
      this.pressed = true
      this.$emit('drag-start')
      e.preventDefault()
      e.stopPropagation()
    },
    onMove (e) {
      if (!this.drag || e.pointerId !== this.drag.id) return
      const b = pointerBearing(e.clientX, e.clientY, this.cx, this.cy)
      // 顺时针拖 = 屏幕方位增大 = PA 减小
      this.drag.raw -= bearingDelta(this.drag.last, b)
      this.drag.last = b
      const snapped = norm360(Math.round(this.drag.raw))
      if (snapped !== this.drag.sent) {
        this.drag.sent = snapped
        this.$emit('rotate', snapped)
      }
    },
    onUp (e) {
      if (!this.drag || e.pointerId !== this.drag.id) return
      this.drag = null
      this.pressed = false
    }
  }
}
</script>
