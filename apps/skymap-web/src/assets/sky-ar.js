// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// Engine glue for AR mode — 相机垫底 + 星图半透明。结构上克隆自 sky-photos.js。
//
// 宿主（Flutter）在 AR 开启时把手机相机预览垫在 webview 之后，本模块负责页面这一侧：
//
//   1) 透明链：给 <html> 挂 .sky-ar 类，index.html 的规则把 html/body/Vuetify 容器
//      全部转透明，露出底下的相机。任一层不透明都会把相机彻底挡死。
//   2) 星图整体透明度：改 #stel-canvas 的 CSS opacity。引擎画布是 alpha:false 的
//      不透明黑（pre.js 建 WebGL 上下文时写死），改不了画布内部 alpha，只能靠 CSS
//      opacity 整体合成 —— 效果是 α·黑 + (1-α)·相机，即所谓「黑纱」。
//   3) 关大气层 + 关地景，退出时还原原值（白天的大气层会把整个天区糊成蓝白，
//      地景则会挡住地平线以下，两者在 AR 下都没有意义）。
//
// 纯状态逻辑在 sky-ar-state.js（有单测），这里只做 DOM 与引擎的读写。

import { clampOpacity, nextArState } from './sky-ar-state.js'

const AR_CLASS = 'sky-ar'
const CANVAS_ID = 'stel-canvas'

let stel = null
// 进入 AR 前的大气/地景原值，未进入时为 null。语义见 sky-ar-state.js 的 nextArState。
let saved = null

function skyCanvas () {
  return document.getElementById(CANVAS_ID)
}

// 设置星图整体透明度。宿主滑块实时调用，越界值由 clampOpacity 兜住。
function setSkyOpacity (alpha) {
  const canvas = skyCanvas()
  if (!canvas) return false
  canvas.style.opacity = String(clampOpacity(alpha))
  return true
}

// 进入 / 退出 AR。退出时把这里改过的三样东西全部还原：大气层、地景、canvas opacity，
// 外加 <html> 上的类。
function enable (on) {
  if (!stel) return false
  const live = {
    atmosphere: stel.core.atmosphere.visible,
    landscapes: stel.core.landscapes.visible
  }
  const next = nextArState(saved, on, live)
  saved = next.saved
  if (next.apply) {
    stel.core.atmosphere.visible = next.apply.atmosphere
    stel.core.landscapes.visible = next.apply.landscapes
  }
  const root = document.documentElement
  if (on) {
    root.classList.add(AR_CLASS)
  } else {
    root.classList.remove(AR_CLASS)
    const canvas = skyCanvas()
    if (canvas) canvas.style.opacity = ''
  }
  return true
}

export function installSkyAr (stelInstance) {
  stel = stelInstance
  if (typeof window !== 'undefined') {
    window.SkyAR = { enable, setSkyOpacity }
  }
}
