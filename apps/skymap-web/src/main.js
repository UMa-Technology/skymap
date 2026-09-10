// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { app } from './app'
import App from './App.vue'
import vuetify from './plugins/vuetify'
import 'roboto-fontface/css/roboto/roboto-fontface.css'
import store from './store'
import { createRouter, createWebHistory } from 'vue-router'
import { createI18n } from 'vue-i18n'
import merge from 'lodash/merge'
import Moment from 'moment'

// Load all plugins JS modules found in the plugins directory
var plugins = []
const pluginModules = import.meta.glob('./plugins/*/index.js', { eager: true })
for (const key in pluginModules) {
  console.log('Loading plugin: ' + key)
  plugins.push(pluginModules[key].default)
}

// Loads all GUI translations found in the src/locales/ directory
var messages = {}
const guiLocales = import.meta.glob('./locales/*.json', { eager: true })
for (const key in guiLocales) {
  const matched = key.match(/([A-Za-z0-9-_]+)\.json$/i)
  if (matched && matched.length > 1) {
    messages[matched[1]] = guiLocales[key].default || guiLocales[key]
  }
}

// Loads all GUI translations found in the src/plugins/xxx/locales directories
const pluginsLocales = import.meta.glob('./plugins/*/locales/*.json', { eager: true })
for (const key in pluginsLocales) {
  const matched = key.match(/\/locales\/([A-Za-z0-9-_]+)\.json$/i)
  if (matched && matched.length > 1) {
    const locale = matched[1]
    const data = pluginsLocales[key].default || pluginsLocales[key]
    if (messages[locale] === undefined) {
      messages[locale] = data
    } else {
      merge(messages[locale], data)
    }
  }
}

const loc = 'en'
Moment.locale(loc)
// vue-i18n 9 in Legacy mode keeps the Vue-2 `$t` API (globalInjection preserves
// this.$t on every component).
const i18n = createI18n({
  legacy: true,
  globalInjection: true,
  locale: loc,
  fallbackLocale: 'en',
  messages,
  formatFallbackMessages: true,
  silentTranslationWarn: true,
  silentFallbackWarn: true,
  missingWarn: false,
  fallbackWarn: false
})

// Base routes
let routes = [
  {
    path: '/',
    name: 'App',
    component: App,
    children: []
  },
  {
    // Main page, but centered on the passed sky source name
    path: '/skysource/:name',
    component: App
  }
]
// Routes exposed by plugins (observing-panel routes removed in the simplified UI)
for (const i in plugins) {
  const plugin = plugins[i]
  if (plugin.routes) {
    routes = routes.concat(plugin.routes)
  }
}
const router = createRouter({
  history: createWebHistory('/'),
  routes
})

// Expose the plugins singleton to all components (was Vue.prototype in Vue 2).
app.config.globalProperties.$stellariumWebPlugins = function () {
  return plugins
}

app.use(store)
app.use(router)
app.use(i18n)
app.use(vuetify)
app.mount('#app')
