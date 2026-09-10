// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { createStore } from 'vuex'
import set from 'lodash/set'
import get from 'lodash/get'

// Vuex 4. state.stel holds the WASM engine tree snapshot (lstel.getTree());
// it is deeply reactive under Vue 3, and sw_helpers.js mutates it per-frame via
// lodash.set (see the reactivity-bridge spike in the internal design notes).
export default createStore({
  state: {
    stel: null,
    initComplete: false,

    showNavigationDrawer: false,
    showDataCreditsDialog: false,
    showPlanetsVisibilityDialog: false,
    showLocationDialog: false,
    selectedObject: undefined,

    showSidePanel: false,

    showMainToolBar: true,
    showLocationButton: true,
    showTimeButtons: true,
    topRightPopupOpen: false,
    showObservingPanelTabsButtons: true,
    showSelectedInfoButtons: true,
    // Whether the selected-object details card pops up on selection.
    // (Was hidden for a while; restored 2026-07-16 per product review.)
    showSelectedInfo: true,
    showFPS: false,
    showEquatorialJ2000GridButton: false,

    fullscreen: false,
    nightmode: false,
    wasmSupport: true,
    // AR 模式（App 嵌入）：appEnableARMode 由宿主 App 开启总开关，
    // arMode 为当前是否处于 AR 跟随；拖动星图会退出（见 App.vue）。
    arMode: false,
    appEnableARMode: false,

    autoDetectedLocation: {
      short_name: 'Unknown',
      country: 'Unknown',
      street_address: '',
      lat: 0,
      lng: 0,
      alt: 0,
      accuracy: 5000
    },

    currentLocation: {
      short_name: 'Unknown',
      country: 'Unknown',
      street_address: '',
      lat: 0,
      lng: 0,
      alt: 0,
      accuracy: 5000
    },

    // App 嵌入形态：位置由宿主 App 喂入（$stel.core.observer.*），不自动定位
    useAutoLocation: false
  },
  mutations: {
    replaceStelWebEngine (state, newTree) {
      // mutate StelWebEngine state
      state.stel = newTree
    },
    setAppEnableARMode (state, newValue) {
      state.appEnableARMode = newValue
    },
    setARMode (state, newValue) {
      state.arMode = newValue
    },
    toggleBool (state, varName) {
      set(state, varName, !get(state, varName))
    },
    setValue (state, { varName, newValue }) {
      set(state, varName, newValue)
    },
    setAutoDetectedLocation (state, newValue) {
      state.autoDetectedLocation = { ...newValue }
      if (state.useAutoLocation) {
        state.currentLocation = { ...newValue }
      }
    },
    setUseAutoLocation (state, newValue) {
      state.useAutoLocation = newValue
      if (newValue) {
        state.currentLocation = { ...state.autoDetectedLocation }
      }
    },
    setCurrentLocation (state, newValue) {
      state.useAutoLocation = false
      state.currentLocation = { ...newValue }
    },
    setSelectedObject (state, newValue) {
      state.selectedObject = newValue
    }
  }
})
