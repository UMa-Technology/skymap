// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import FramingOverlay from './framing-overlay.vue'

// 引擎桩：只给 overlay 方法真的会碰的成员。缺成员导致的 TypeError 一律补桩，
// **不要**为了过测试弱化断言。
function makeStel () {
  return {
    canvas: { width: 800, height: 1600, clientWidth: 400, clientHeight: 800 },
    core: {
      observer: { yaw: 0, pitch: 0, roll: 0 },
      fov: 1, fovX: 0.6, fovY: 1, selection: null
    },
    convertFrame: () => [0, 0, 1],
    c2s: () => [0, 0],
    // s2c 返回一条与 convertFrame 的视轴 [0,0,1] 正交的方向：桩里的"目标"因此
    // 离屏幕中心 90°，scaleFov2Target 才有可缩放的距离可算（否则目标恰在视轴上）。
    s2c: () => [0, 1, 0],
    anp: (a) => a,
    anpm: (a) => a,
    zoomTo: vi.fn(),
    pointAndLock: vi.fn()
  }
}
const makeStore = () => ({ state: { stel: { fov: 1 }, arMode: false } })

function mountIt (data = {}) {
  return mount(FramingOverlay, {
    data: () => data,
    global: { mocks: { $stel: makeStel(), $store: makeStore() } }
  })
}

let raf, caf
beforeEach(() => {
  raf = vi.fn(() => 7)
  caf = vi.fn()
  vi.stubGlobal('requestAnimationFrame', raf)
  vi.stubGlobal('cancelAnimationFrame', caf)
  window.StellariumActions = { updateFov: vi.fn() }
})
afterEach(() => {
  vi.unstubAllGlobals()
  delete window.StellariumActions
})

describe('对 jsbridge.vue 的四个接口', () => {
  it('actions() 恰好是 8 个取景 action', () => {
    const w = mountIt()
    expect(Object.keys(w.vm.actions()).sort()).toEqual([
      'clearOffCenterRect', 'drawRectWithAltAndAz', 'getMosaicCenters', 'hideMosaic',
      'restoreScaledFov', 'scaleFov2Target', 'showMosaic', 'toggleCenterFov'
    ])
    w.unmount()
  })

  it('stateFields() 初值与今天 getState 里的两项一致', () => {
    const w = mountIt()
    expect(w.vm.stateFields()).toEqual({
      showMosaic: false,
      mosaicConfig: { x: 2, y: 2, overlap: 10 }
    })
    w.unmount()
  })

  it('cameraLongEdgeDeg() 未设置为 -1，toggleCenterFov 设过后取长边', () => {
    const w = mountIt()
    expect(w.vm.cameraLongEdgeDeg()).toBe(-1)
    w.vm.actions().toggleCenterFov({ fovX: 4, fovY: 3 })
    expect(w.vm.cameraLongEdgeDeg()).toBe(4)
    w.unmount()
  })

  it("shape: 'circle' 按给的尺寸画圆，不是写死的 2°", () => {
    // 目镜的真实视场从 0.2° 到 3° 都有。固定 2° 的那个圈（下面那条 -1 哨兵）
    // 对望远镜用户是个假数，这一条就是为了它加的。
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: 1.24, fovY: 1.24, shape: 'circle' })
    expect(w.vm.isCenterCircle).toBe(true)
    expect(w.vm.targetFovX).toBe(1.24)
    expect(w.vm.targetFovY).toBe(1.24)
    w.unmount()
  })

  it("圆只认一个直径：宽高不等时取大的那个，不画椭圆", () => {
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: 1.2, fovY: 0.9, shape: 'circle' })
    expect(w.vm.targetFovX).toBe(1.2)
    expect(w.vm.targetFovY).toBe(1.2)
    w.unmount()
  })

  it('不传 shape 还是矩形，宽高各按各的', () => {
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: 4, fovY: 3 })
    expect(w.vm.isCenterCircle).toBe(false)
    expect(w.vm.targetFovX).toBe(4)
    expect(w.vm.targetFovY).toBe(3)
    w.unmount()
  })

  it('老哨兵 -1 / -1 照旧画 2° 的圆——宿主里还有按它调的旧代码', () => {
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: -1, fovY: -1 })
    expect(w.vm.isCenterCircle).toBe(true)
    expect(w.vm.targetFovX).toBe(2)
    w.unmount()
  })

  it('从圆换回矩形要真的换回去，不留在圆上', () => {
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: 1.2, fovY: 1.2, shape: 'circle' })
    expect(w.vm.isCenterCircle).toBe(true)
    w.vm.actions().toggleCenterFov({ fovX: 4, fovY: 3 })
    expect(w.vm.isCenterCircle).toBe(false)
    w.unmount()
  })

  it('scaleFov2Target / restoreScaledFov 经公开桥 updateFov 改视场', () => {
    const w = mountIt()
    w.vm.actions().toggleCenterFov({ fovX: 4, fovY: 3 })
    // lastRectParams 由 drawRectWithAltAndAz 落下，scaleFov2Target 缩的就是它——
    // 走模块自己的公开 action 布置前置状态，不直接塞 data。
    w.vm.actions().drawRectWithAltAndAz({ alt: 45, az: 90, fovX: 4, fovY: 3 })
    w.vm.actions().scaleFov2Target()
    // 目标离视轴 90°（见上方 s2c 桩注释）+ targetHalfSize = max(4,3)/2 = 2，
    // newFov = (90 + 2) × 1.5 = 138，钳到 80 上限。
    expect(window.StellariumActions.updateFov).toHaveBeenNthCalledWith(1, 80)
    w.vm.actions().restoreScaledFov()
    // 恢复到 scaleFov2Target 执行前的 currentFov：$store.state.stel.fov = 1 弧度。
    expect(window.StellariumActions.updateFov).toHaveBeenNthCalledWith(2, 180 / Math.PI)
    w.unmount()
  })

  it('tick() 在什么都不显示时不抛', () => {
    const w = mountIt()
    expect(() => w.vm.tick()).not.toThrow()
    w.unmount()
  })
})

describe('rAF 循环按可见性启停', () => {
  it('挂载时什么都不显示 → 不请求 rAF', () => {
    const w = mountIt()
    expect(raf).not.toHaveBeenCalled()
    w.unmount()
  })

  it('任一取景框可见 → 启动；全部隐藏 → 停止', async () => {
    const w = mountIt()
    w.vm.showMosaic = true
    await nextTick()
    expect(raf).toHaveBeenCalledTimes(1)
    w.vm.showMosaic = false
    await nextTick()
    expect(caf).toHaveBeenCalledWith(7)
    w.unmount()
  })

  it('挂载时就可见 → 挂载即启动；卸载即停止', () => {
    const w = mountIt({ showOffCenterRect: true })
    expect(raf).toHaveBeenCalledTimes(1)
    w.unmount()
    expect(caf).toHaveBeenCalledWith(7)
  })
})

describe('overlay 挂到 document.body 之下', () => {
  it('挂载后根元素在 body 下，卸载后移除', () => {
    const w = mountIt()
    const el = w.vm.$refs.overlay
    expect(el.parentNode).toBe(document.body)
    w.unmount()
    expect(el.parentNode).toBeNull()
  })
})
