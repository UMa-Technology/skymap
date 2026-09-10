// Stellarium Web - Copyright (c) 2022 - Stellarium Labs SRL
//
// This program is licensed under the terms of the GNU AGPL v3, or
// alternatively under a commercial licence.
//
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

<template>

<div class="click-through" style="position:absolute; width: 100%; height: 100%; display:flex; align-items: flex-end;">
  <js-bridge-selected-object></js-bridge-selected-object>
  <js-bridge></js-bridge>
</div>

</template>

<script>
// App 嵌入形态：标准 GUI（toolbar/bottom-bar/选中面板等）整体替换为
// jsbridge 产品 UI + postMessage 桥（见 dev_docs/app-embedding-handoff.md §7）
import JsBridge from '@/components/jsbridge.vue'
import JsBridgeSelectedObject from '@/components/jsbridge-selected-object.vue'

export default {
  components: {
    JsBridge,
    JsBridgeSelectedObject
  }
}
</script>

<style>
</style>
