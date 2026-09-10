// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// The Vue 3 application singleton, in its own module so both main.js (which
// configures + mounts it) and sw_helpers.js (which sets $stel and the engine
// layers on app.config.globalProperties once the WASM engine is ready) can
// import it without a circular dependency on the entry module.
import { createApp, h } from 'vue'
import { RouterView } from 'vue-router'

export const app = createApp({ name: 'Root', render: () => h(RouterView) })
