// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import {
  gridCoord, screenFromView, viewFromScreen, screenDeltaToGrid, pressMode, tileHittable,
  fitScale, normalizeTile, TAP_MAX_MOVE, MIN_HIT_PX
} from './mosaic-layout-math'

describe('gridCoord', () => {
  it('网格中心为原点，奇偶行列都对称', () => {
    expect(gridCoord({ col: 0, row: 0 }, 1, 2)).toEqual({ gx: 0, gy: -0.5 })
    expect(gridCoord({ col: 2, row: 1 }, 3, 3)).toEqual({ gx: 1, gy: 0 })
  })
  it('单格微调叠加在格位上；补出来的格可在网格外', () => {
    expect(gridCoord({ col: 1, row: 0, dx: 0.25, dy: -0.5 }, 2, 1)).toEqual({ gx: 0.75, gy: -0.5 })
    expect(gridCoord({ col: -1, row: 0 }, 2, 1)).toEqual({ gx: -1.5, gy: 0 })
  })
})

describe('屏幕投影正反算', () => {
  const W = 874
  const H = 402
  const fov = 0.8
  it('屏幕中心 ↔ 视线方向', () => {
    expect(screenFromView([0, 0, -1], W, H, fov)).toEqual([W / 2, H / 2])
    const v = viewFromScreen(W / 2, H / 2, W, H, fov)
    expect(v[0]).toBeCloseTo(0)
    expect(v[1]).toBeCloseTo(0)
    expect(v[2]).toBeCloseTo(-1)
  })
  it('任意屏幕点反算再正算回到原处', () => {
    for (const [x, y] of [[10, 20], [800, 390], [437, 50], [600, 201]]) {
      const back = screenFromView(viewFromScreen(x, y, W, H, fov), W, H, fov)
      expect(back[0]).toBeCloseTo(x, 6)
      expect(back[1]).toBeCloseTo(y, 6)
    }
  })
  it('视线背后不投影', () => {
    expect(screenFromView([0, 0, 1], W, H, fov)).toBeNull()
  })
  it('反算出的是单位向量', () => {
    const v = viewFromScreen(100, 300, W, H, fov)
    expect(Math.hypot(...v)).toBeCloseTo(1, 10)
  })
})

describe('screenDeltaToGrid', () => {
  it('网格不转时按步距换算', () => {
    expect(screenDeltaToGrid(50, -20, 0, 100, 40)).toEqual({ gx: 0.5, gy: -0.5 })
  })
  it('网格转 90° 时屏幕向下 = 网格向右', () => {
    const g = screenDeltaToGrid(0, 100, 90, 100, 100)
    expect(g.gx).toBeCloseTo(1)
    expect(g.gy).toBeCloseTo(0)
  })
})

describe('手势与易达性', () => {
  it('位移不超过阈值仍在判断，超过算拖动', () => {
    expect(pressMode(0)).toBe('pending')
    expect(pressMode(TAP_MAX_MOVE)).toBe('pending')
    expect(pressMode(TAP_MAX_MOVE + 0.1)).toBe('drag')
  })
  it('格子短边 < 44 px 不接手手势', () => {
    expect(tileHittable(MIN_HIT_PX, 100)).toBe(true)
    expect(tileHittable(100, MIN_HIT_PX - 1)).toBe(false)
  })
  it('外接框超过画面 70% 才要缩', () => {
    expect(fitScale(350, 140, 1000, 400)).toBeLessThan(1)
    expect(fitScale(1400, 140, 1000, 400)).toBeCloseTo(2)
  })
})

describe('normalizeTile', () => {
  it('补齐缺省字段', () => {
    expect(normalizeTile({ key: 'a', col: 1, row: 0 })).toEqual({
      key: 'a', col: 1, row: 0, dx: 0, dy: 0, enabled: true, label: '', state: 'normal'
    })
  })
  it('补格虚位一律不算启用', () => {
    expect(normalizeTile({ key: 's', col: -1, row: 0, enabled: true, state: 'slot' }).enabled).toBe(false)
  })
  it('非法格丢掉，未知状态回落 normal', () => {
    expect(normalizeTile(null)).toBeNull()
    expect(normalizeTile({ col: 0, row: 0 })).toBeNull()
    expect(normalizeTile({ key: 1, col: 'x', row: 0 })).toBeNull()
    expect(normalizeTile({ key: 1, col: 0, row: 0, state: 'boom', label: 3 })).toMatchObject({ key: '1', state: 'normal', label: '3' })
  })
})
