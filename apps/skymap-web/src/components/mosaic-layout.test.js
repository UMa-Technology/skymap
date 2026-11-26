// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

const posted = []
vi.mock('@/utils/jsbridge', () => ({ default: { postMessage: (a, d) => posted.push([a, d]) } }))
const { default: MosaicLayout } = await import('./mosaic-layout.vue')

// 引擎桩：ICRF ↔ VIEW 恒等（视线 -z），够验手势与数据流；投影几何由 mosaic-layout-math 的单测管
function makeStel () {
  return {
    canvas: { width: 874, height: 402, clientWidth: 874, clientHeight: 402 },
    core: { observer: {}, lock: 0 },
    convertFrame: (o, from, to, v) => v,
    s2c: (ra, dec) => [Math.cos(dec) * Math.sin(ra), Math.sin(dec), -Math.cos(dec) * Math.cos(ra)],
    c2s: (v) => [Math.atan2(v[0], -v[2]), Math.asin(Math.max(-1, Math.min(1, v[1])))],
    anp: (a) => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI),
    zoomTo: vi.fn(),
    createObj: vi.fn(() => ({})),
    pointAndLock: vi.fn()
  }
}
const cfg = (extra = {}) => ({
  center: { ra: 0, dec: 0 }, gridPa: 0, fovX: 20, fovY: 14, overlap: 10, cols: 2, rows: 1,
  tiles: [
    { key: '0,0', col: 0, row: 0, enabled: true, label: 2 },
    { key: '1,0', col: 1, row: 0, enabled: true, label: 1 }
  ],
  ...extra
})

let w
beforeEach(() => {
  posted.length = 0
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  w = mount(MosaicLayout, { global: { mocks: { $stel: makeStel(), $store: { state: { stel: { fov: 1.2 } } } } } })
})
afterEach(() => {
  w.unmount()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const down = (el, x, y) => el.trigger('pointerdown', { pointerId: 1, clientX: x, clientY: y })
const move = (el, x, y) => el.trigger('pointermove', { pointerId: 1, clientX: x, clientY: y })
const up = (el, x, y) => el.trigger('pointerup', { pointerId: 1, clientX: x, clientY: y })

describe('show / hide', () => {
  it('非法配置不显示', () => {
    expect(w.vm.show({ cols: 0, rows: 1, fovX: 1, fovY: 1 })).toBe(false)
    expect(w.vm.show(cfg({ overlap: 100 }))).toBe(false)
    expect(w.vm.visible).toBe(false)
  })
  it('合法配置画出每一格，停用格不显示编号', async () => {
    w.vm.show(cfg({ tiles: [{ key: 'a', col: 0, row: 0, enabled: false, label: 1 }, { key: 'b', col: 1, row: 0, label: 2 }] }))
    await nextTick()
    const tiles = w.findAll('.mosaic-layout-tile')
    expect(tiles).toHaveLength(2)
    expect(tiles[0].find('svg').exists()).toBe(true)
    expect(tiles[0].text()).toBe('')
    expect(tiles[1].text()).toBe('2')
  })
  it('没给锚点时取屏幕中心并回报宿主', () => {
    w.vm.show(cfg({ center: null }))
    expect(posted.find(([a]) => a === 'mosaicMove')[1].phase).toBe('end')
    expect(w.vm.center.dec).toBeCloseTo(0)
  })
  it('hide 后不再显示', () => {
    w.vm.show(cfg())
    w.vm.hide()
    expect(w.vm.visible).toBe(false)
  })
})

describe('手势', () => {
  it('不动松手 = 点格', async () => {
    w.vm.show(cfg())
    await nextTick()
    const t = w.find('[data-key="1,0"]')
    await down(t, 100, 100)
    await up(t, 103, 101)
    expect(posted).toContainEqual(['mosaicTileTap', { key: '1,0' }])
  })
  it('拖动 = 移动整个网格，结束报一次 end，不报点格', async () => {
    w.vm.show(cfg())
    await nextTick()
    const t = w.find('[data-key="0,0"]')
    const before = { ...w.vm.center }
    await down(t, 100, 100)
    await move(t, 160, 100)
    await up(t, 160, 100)
    expect(posted.some(([a]) => a === 'mosaicTileTap')).toBe(false)
    const end = posted.filter(([a]) => a === 'mosaicMove').pop()
    expect(end[1].phase).toBe('end')
    expect(end[1].center.ra).not.toBeCloseTo(before.ra, 6)
  })
  it('长按（开 tileEdit）进入单格，之后拖动只改这一格', async () => {
    vi.useFakeTimers()
    w.vm.show(cfg({ tileEdit: true }))
    await nextTick()
    const t = w.find('[data-key="1,0"]')
    await down(t, 100, 100)
    vi.advanceTimersByTime(450)
    expect(posted).toContainEqual(['mosaicTileLongPress', { key: '1,0' }])
    await move(t, 130, 100)
    await up(t, 130, 100)
    const end = posted.filter(([a]) => a === 'mosaicTileMove').pop()
    expect(end[1].key).toBe('1,0')
    expect(end[1].phase).toBe('end')
    expect(end[1].dx).toBeGreaterThan(0)
    expect(posted.some(([a]) => a === 'mosaicMove')).toBe(false)
  })
  it('没开 tileEdit 时长按不进单格', async () => {
    vi.useFakeTimers()
    w.vm.show(cfg())
    await nextTick()
    const t = w.find('[data-key="1,0"]')
    await down(t, 100, 100)
    vi.advanceTimersByTime(800)
    expect(posted.some(([a]) => a === 'mosaicTileLongPress')).toBe(false)
  })
  it('补格虚位只能点，拖动不移网格', async () => {
    w.vm.show(cfg({ tiles: [...cfg().tiles, { key: 'x1', col: 2, row: 0, state: 'slot' }] }))
    await nextTick()
    const t = w.find('[data-key="x1"]')
    await down(t, 100, 100)
    await move(t, 200, 100)
    await up(t, 200, 100)
    expect(posted.some(([a]) => a === 'mosaicMove' || a === 'mosaicTileTap')).toBe(false)
  })
  it('不编辑（editing:false）时格子不接手手势', async () => {
    w.vm.show(cfg({ editing: false }))
    await nextTick()
    expect(w.find('[data-key="0,0"]').attributes('style')).toContain('pointer-events: none')
  })
})

describe('入库与背景点击', () => {
  it('centers 只回启用格，按宿主编号排', () => {
    w.vm.show(cfg({ tiles: [{ key: 'a', col: 0, row: 0, label: 2 }, { key: 'b', col: 1, row: 0, label: 1 }, { key: 'c', col: 0, row: 0, enabled: false }] }))
    expect(w.vm.centers().map(c => c.key)).toEqual(['b', 'a'])
  })
  it('有选中格时背景点击被吃掉并通知宿主', () => {
    w.vm.show(cfg({ tiles: [{ key: 'a', col: 0, row: 0, state: 'selected' }] }))
    expect(w.vm.onBackgroundClick()).toBe(true)
    expect(posted).toContainEqual(['mosaicBackgroundTap', {}])
  })
  it('没选中格时背景点击照常交给星图', () => {
    w.vm.show(cfg())
    expect(w.vm.onBackgroundClick()).toBe(false)
  })
})
