import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { fileURLToPath, URL } from 'node:url'
import { execSync } from 'node:child_process'
import { PROTOCOL } from './src/protocol.js'

// Build version baked into the page (window.SkymapBase) and into
// dist/skymap-base.json. CI sets SKYMAP_VERSION to the tag being released;
// local builds fall back to `git describe`, then to '0.0.0-local'.
function resolveVersion () {
  if (process.env.SKYMAP_VERSION) return process.env.SKYMAP_VERSION
  try {
    const out = execSync('git describe --tags --always --dirty', { stdio: ['ignore', 'pipe', 'ignore'] })
    return out.toString().trim() || '0.0.0-local'
  } catch {
    return '0.0.0-local'
  }
}

// Emits dist/skymap-base.json so the packaging script (and any host that can
// fetch from the served directory) sees the same identity as the page.
function skymapBasePlugin (version) {
  return {
    name: 'skymap-base-json',
    generateBundle () {
      this.emitFile({
        type: 'asset',
        fileName: 'skymap-base.json',
        source: JSON.stringify({ version, protocol: PROTOCOL }) + '\n'
      })
    }
  }
}

// Vite config for the SkyMap web layer (Vue 3 + Vuetify 3).
// 离线专用嵌入构建：无任何在线 API，天体信息/搜索/名称全走本地引擎数据。
export default defineConfig(() => {
  // App 嵌入变体默认相对路径（'./'）：页面由宿主起的本地 http server 提供，
  // 挂载路径（端口 / 子目录）由宿主决定，自定义 scheme 同理——写死绝对路径的
  // /assets、/skydata 一换挂载点就 404。
  // ⚠️ file:// 不是可选加载方式（走不通的原因见 USAGE.md），相对 base 与它无关。
  // CDN_ENV 保留旧 vue.config.js 的 CDN 覆盖语义。base 与 BASE_URL 必须一致。
  const base = process.env.CDN_ENV || './'
  const version = resolveVersion()
  return {
    base,
    plugins: [
      vue(),
      // Auto-import Vuetify 3 components/directives + treeshake their styles.
      vuetify({ autoImport: true }),
      skymapBasePlugin(version)
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      },
      // vue-cli/webpack auto-resolved extensionless .vue imports; Vite needs this.
      extensions: ['.mjs', '.js', '.json', '.vue']
    },
    // vue-cli exposed BASE_URL as process.env.*; shim it for the app code.
    define: {
      'process.env.BASE_URL': JSON.stringify(base),
      __SKYMAP_VERSION__: JSON.stringify(version)
    },
    server: {
      port: 8080,
      host: true,
      strictPort: true
    },
    build: {
      // the generated emscripten glue + big deps push past the default warning
      chunkSizeWarningLimit: 4000,
      rollupOptions: {
        output: {
          // Split rarely-changing heavy vendors into their own cacheable chunks.
          manualChunks (id) {
            if (id.includes('node_modules/vuetify')) return 'vuetify'
            if (id.includes('node_modules/@mdi')) return 'mdi'
          }
        }
      }
    }
  }
})
