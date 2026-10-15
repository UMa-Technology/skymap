// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import FramingRing from './framing-ring.vue'

beforeEach(() => {
  window.innerWidth = 852
  window.innerHeight = 393
})

const mountRing = (props = {}) => mount(FramingRing, {
  props: { angleToNorth: 0, targetPa: 0, zeroPa: 0, busy: false, showHints: true, ...props },
  attachTo: document.body
})

// 圆环在屏幕中心 (426, 196.5)，R = 168.5
const pt = (bearing, r = 168.5) => {
  const t = bearing * Math.PI / 180
  return { clientX: 426 + r * Math.sin(t), clientY: 196.5 - r * Math.cos(t), pointerId: 1 }
}

describe('画法', () => {
  it('圆环与刻度是同一条 path（交叠处不叠色）', () => {
    const w = mountRing()
    const ring = w.find('[data-test="ring-path"]')
    expect(ring.exists()).toBe(true)
    // 1 个圆（两段弧）+ 36 根刻度 = 至少 37 个 M
    expect((ring.attributes('d').match(/M/g) || []).length).toBeGreaterThanOrEqual(37)
    expect(w.findAll('[data-test="ring-path"]').length).toBe(1)
  })
  it('标签显示 当前 − 目标，顺时针为正', () => {
    const w = mountRing({ zeroPa: 123, targetPa: 98 })
    expect(w.find('[data-test="ring-tag"]').text()).toBe('+25°')
  })
  it('|Δ| ≤ 1 变绿、显示 0°，不画转动弧', () => {
    const w = mountRing({ zeroPa: 98, targetPa: 98 })
    const tag = w.find('[data-test="ring-tag"]')
    expect(tag.text()).toBe('0°')
    expect(tag.attributes('style')).toContain('rgb(42, 187, 57)')
    expect(w.find('[data-test="ring-arc"]').exists()).toBe(false)
  })
  it('showHints 时两侧提示箭头可见', () => {
    expect(mountRing({ showHints: true }).findAll('[data-test="ring-hint"]').length).toBe(2)
    expect(mountRing({ showHints: false }).findAll('[data-test="ring-hint"]').length).toBe(0)
  })
  it('busy 时整组 30% 不透明', () => {
    expect(mountRing({ busy: true }).find('[data-test="ring-root"]').attributes('style')).toContain('opacity: 0.3')
  })
})

describe('宿主下发半径', () => {
  it('给了 ringRadius 就按它画（宿主按安全区与过程卡位置算），不按视口公式', () => {
    const w = mountRing({ ringRadius: 123 })
    const d = w.find('[data-test="ring-path"]').attributes('d')
    // 圆从 (cx − r, cy) 起笔：426 − 123 = 303
    expect(d.startsWith('M303 196.5')).toBe(true)
  })
  it('没给（老宿主）就按视口公式', () => {
    const d = mountRing().find('[data-test="ring-path"]').attributes('d')
    expect(d.startsWith('M257.5 196.5')).toBe(true)
  })
})

describe('拖动', () => {
  it('从圆环带起手、顺时针拖 10° → 目标 PA 减 10，按整数度 emit', async () => {
    const w = mountRing({ zeroPa: 0, targetPa: 0 })
    const band = w.find('[data-test="ring-band"]')
    await band.trigger('pointerdown', pt(0))
    await band.trigger('pointermove', pt(10))
    const out = w.emitted('rotate')
    expect(out[out.length - 1][0]).toBe(350)
    expect(w.emitted('drag-start')).toBeTruthy()
  })
  it('从任意位置按下不跳：在 90° 处按下不动，不 emit', async () => {
    const w = mountRing({ targetPa: 0 })
    await w.find('[data-test="ring-band"]').trigger('pointerdown', pt(90))
    expect(w.emitted('rotate')).toBeFalsy()
  })
  it('同一整数度不重复 emit', async () => {
    const w = mountRing({ targetPa: 0 })
    const band = w.find('[data-test="ring-band"]')
    await band.trigger('pointerdown', pt(0))
    await band.trigger('pointermove', pt(5.2))
    await band.trigger('pointermove', pt(5.4))
    expect(w.emitted('rotate').length).toBe(1)
  })
  it('busy 时按下不响应', async () => {
    const w = mountRing({ busy: true })
    const band = w.find('[data-test="ring-band"]')
    await band.trigger('pointerdown', pt(0))
    await band.trigger('pointermove', pt(20))
    expect(w.emitted('rotate')).toBeFalsy()
  })
})

describe('目标入口 absoluteLabel', () => {
  it('标签显示目标角度本身，不是差值', () => {
    const w = mountRing({ zeroPa: 0, targetPa: 125, absoluteLabel: true })
    expect(w.find('[data-test="ring-tag"]').text()).toBe('125°')
  })
  it('负角归一到 0–359', () => {
    const w = mountRing({ zeroPa: 0, targetPa: -235, absoluteLabel: true })
    expect(w.find('[data-test="ring-tag"]').text()).toBe('125°')
  })
  it('不画差值弧，目标在 0° 也不变绿', () => {
    const w = mountRing({ zeroPa: 0, targetPa: 0, absoluteLabel: true })
    expect(w.find('[data-test="ring-arc"]').exists()).toBe(false)
    expect(w.find('[data-test="ring-tag"]').text()).toBe('0°')
    expect(w.vm.aligned).toBe(false)
  })
  // 顺时针拖 PA 减小、标签数变小：顺时针一侧的提示要标 −，否则往「+」拖数反而变小
  it('提示箭头正负跟标签走：顺时针一侧标 −、逆时针一侧标 +', () => {
    const w = mountRing({ zeroPa: 0, targetPa: 30, absoluteLabel: true })
    const signs = Object.fromEntries(w.vm.hintPaths.map(h => [h.key, h.sign]))
    expect(signs[1]).toBe('−')
    expect(signs[-1]).toBe('+')
  })
})

describe('设备入口提示箭头', () => {
  // 标签是 当前 − 目标，顺时针拖差值变大
  it('顺时针一侧标 +、逆时针一侧标 −', () => {
    const signs = Object.fromEntries(mountRing({ zeroPa: 0, targetPa: 30 }).vm.hintPaths.map(h => [h.key, h.sign]))
    expect(signs[1]).toBe('+')
    expect(signs[-1]).toBe('−')
  })
})

