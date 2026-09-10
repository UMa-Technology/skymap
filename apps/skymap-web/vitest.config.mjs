import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 组件测试（*.vue）需要 SFC 编译与 `@` 别名；默认环境仍是 node，
// 需要 DOM 的测试文件自己在文件头写 `// @vitest-environment happy-dom`。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
    extensions: ['.mjs', '.js', '.json', '.vue']
  },
  test: {
    include: ['src/**/*.test.js'],
    environment: 'node'
  }
})
