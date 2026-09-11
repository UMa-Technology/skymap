// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// Development GUI mounted by App.vue when the page is opened with ?webgui=1 (see utils/webgui.js).

<template>

<div class="click-through" style="position:absolute; width: 100%; height: 100%; display:flex; align-items: flex-end;">
  <toolbar v-if="$store.state.showMainToolBar" class="get-click"></toolbar>
  <!-- Time readout + picker entry: transparent, below the toolbar, top-right.
       Wrapped in a positioned div because <top-time>'s root is a v-menu, which
       does not take inline-style fallthrough for positioning. -->
  <div v-if="$store.state.showTimeButtons && !$store.state.topRightPopupOpen" class="get-click" style="position:absolute; top:50px; right:8px;">
    <top-time></top-time>
  </div>
  <template v-for="(item, i) in pluginsGuiComponents" :key="'g' + i">
    <component :is="item"></component>
  </template>
  <template v-for="(item, i) in dialogs" :key="'d' + i">
    <component :is="item"></component>
  </template>
  <selected-object-info style="position: absolute; top: 48px; left: 0px; width: 380px; max-width: calc(100vw - 12px); margin: 6px" class="get-click"></selected-object-info>
  <bottom-bar style="position:absolute; width: 100%; justify-content: center; bottom: 0; display:flex; margin-bottom: 0px" class="get-click"></bottom-bar>
  <js-bridge></js-bridge>
</div>

</template>

<script>
import Toolbar from '@/components/toolbar.vue'
import BottomBar from '@/components/bottom-bar.vue'
import TopTime from '@/components/top-time.vue'
import SelectedObjectInfo from '@/components/selected-object-info.vue'
import JsBridge from '@/components/jsbridge.vue'

export default {
  computed: {
    pluginsGuiComponents: function () {
      let res = []
      for (const i in this.$stellariumWebPlugins()) {
        const plugin = this.$stellariumWebPlugins()[i]
        if (plugin.guiComponents) {
          res = res.concat(plugin.guiComponents)
        }
      }
      return res
    },
    dialogs: function () {
      let res = []
      for (const i in this.$stellariumWebPlugins()) {
        const plugin = this.$stellariumWebPlugins()[i]
        if (plugin.dialogs) {
          res = res.concat(plugin.dialogs.map(d => d.name))
        }
      }
      return res
    }
  },
  components: { Toolbar, BottomBar, TopTime, SelectedObjectInfo, JsBridge }
}
</script>

<style>
</style>
