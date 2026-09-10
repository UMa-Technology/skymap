// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// AR 模式的纯状态逻辑，不碰 DOM、不碰引擎实例，便于在 node 环境下单测
// （vitest 配的是 environment: 'node'，没有 jsdom）。DOM 与引擎交互在 sky-ar.js。
// 与 custom-horizon-geometry.js / custom-horizon.js 的拆分方式一致。

// 星图透明度可用区间：低于 0.2 星图基本看不见，高于 0.8 实景基本没了。
export const OPACITY_MIN = 0.2
export const OPACITY_MAX = 0.8

// 把宿主传来的透明度钳进可用区间。非数值一律退回上限（星图最清晰的一端），
// 宁可 AR 效果弱一点，也不要因为一个坏值把星图整没了。
//
// 用 parseFloat 而不是 Number：Number(null) 是 0、Number('') 也是 0，会被当成
// 「透明度 0」钳成下限，把星图压到几乎看不见 —— 而 null / 空串真实语义是「没给值」，
// 该走兜底。parseFloat 对这两者都给 NaN，正好落进兜底分支。
export function clampOpacity (value) {
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (!Number.isFinite(n)) return OPACITY_MAX
  return Math.min(OPACITY_MAX, Math.max(OPACITY_MIN, n))
}

// 计算大气层 / 地景开关的下一步动作。
//   saved  当前存档（进入 AR 前的原值），未进入 AR 时为 null
//   on     目标状态
//   live   引擎当前实时值
// 返回 { saved: 新存档, apply: 要下发给引擎的值（null 表示什么都不下发）}。
//
// 关键：重复 enable(true) 时不能拿实时值覆盖存档 —— 实时值这时已经被上一轮压成
// false，覆盖后退出 AR 就再也还原不回来了。
export function nextArState (saved, on, live) {
  if (on) {
    const kept = saved || { atmosphere: live.atmosphere, landscapes: live.landscapes }
    return { saved: kept, apply: { atmosphere: false, landscapes: false } }
  }
  if (!saved) return { saved: null, apply: null }
  return { saved: null, apply: { atmosphere: saved.atmosphere, landscapes: saved.landscapes } }
}
