// @vitest-environment happy-dom
// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import WebGui from './webgui.vue'

function mountWith (state) {
  return mount(WebGui, {
    global: {
      stubs: { Toolbar: true, TopTime: true, SelectedObjectInfo: true, BottomBar: true, JsBridge: true },
      mocks: {
        $store: { state: { showMainToolBar: true, showTimeButtons: true, topRightPopupOpen: false, ...state } },
        $stellariumWebPlugins: () => ({})
      }
    }
  })
}

describe('webgui.vue', () => {
  it('mounts the full GUI plus the JS bridge', () => {
    const w = mountWith({})
    for (const tag of ['toolbar-stub', 'top-time-stub', 'selected-object-info-stub', 'bottom-bar-stub', 'js-bridge-stub']) {
      expect(w.find(tag).exists(), tag).toBe(true)
    }
  })
  it('hides the toolbar and the time readout when the store says so', () => {
    const w = mountWith({ showMainToolBar: false, showTimeButtons: false })
    expect(w.find('toolbar-stub').exists()).toBe(false)
    expect(w.find('top-time-stub').exists()).toBe(false)
    expect(w.find('js-bridge-stub').exists()).toBe(true)
  })
})
