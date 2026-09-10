// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

class StellariumBridge {
  // 发送消息给 App
  postMessage (action, data = {}) {
    const message = JSON.stringify({ action, data })
    if (window.webkit?.messageHandlers?.stellarium) {
      window.webkit.messageHandlers.stellarium.postMessage(message)
    } else if (window.stellarium) {
      window.stellarium.postMessage(message)
    }
  }

  // 注册供 App 调用的方法
  registerActions (actions) {
    window.StellariumActions = actions
  }
}

export default new StellariumBridge()
