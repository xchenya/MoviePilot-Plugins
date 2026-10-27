import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'
import { readFileSync } from 'node:fs'

const version = readFileSync(new URL('./__init__.py', import.meta.url), 'utf8')
  .match(/plugin_version = "([0-9.]+)"/)[1]

export default defineConfig({
  plugins: [vue(), federation({
    name: 'HdskyCommunitySign',
    filename: 'remoteEntry.js',
    exposes: {
      './Config': './src/components/Config.vue',
      './Page': './src/components/Page.vue',
    },
    shared: {
      vue: { requiredVersion: false, generate: false },
      vuetify: { requiredVersion: false, generate: false, singleton: true },
      'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
    },
  })],
  css: {
    postcss: {
      plugins: [{
        postcssPlugin: 'vuetify-filter',
        Root(root) {
          const file = root.source?.input?.file?.replaceAll('\\', '/') || ''
          if (root.nodes.length && (file.includes('/node_modules/vuetify/') || file.includes('/node_modules/@mdi/'))) root.removeAll()
        },
      }],
    },
  },
  build: {
    target: 'esnext', minify: false, cssCodeSplit: false,
    outDir: 'dist', assetsDir: `assets-v${version}`, emptyOutDir: true,
  },
})
