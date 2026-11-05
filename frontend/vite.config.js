import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import https from 'https'
import { execFileSync } from 'node:child_process'

// Development runtime executes on the admitted ECS; local production builds remain supported.
// This is a Vite-only setting and is never included in the production bundle.
const developmentApiTarget = process.env.DOORHANDLE_DEV_API_TARGET || ''
const previewOrigin = process.env.DOORHANDLE_DEV_API_TARGET ? new URL(developmentApiTarget).origin : null
const forwardPreviewOrigin = (proxy) => {
  if (previewOrigin) proxy.on('proxyReq', (request) => request.setHeader('Origin', previewOrigin))
}

// OSS 代理专用 Agent，复用连接避免每次 TCP/TLS 握手
const ossAgent = new https.Agent({
  keepAlive: true,
  keepAliveMsecs: 30000,
  maxSockets: 20,
  maxFreeSockets: 10,
  timeout: 60000
})

export default defineConfig(({ command }) => {
  if (command === 'serve') {
    if (!process.env.DOORHANDLE_DEV_API_TARGET) throw new Error('Set DOORHANDLE_DEV_API_TARGET to the ECS gateway')
    execFileSync(process.env.PYTHON_EXE || 'python3', ['-B', path.resolve(__dirname, '../scripts/ecs_execution.py')], { stdio: 'inherit' })
  }
  return {
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3001,
    host: '0.0.0.0',
    strictPort: false,
    open: process.env.DOORHANDLE_DEV_OPEN_BROWSER === 'false' ? false : '/#/login',
    fs: { strict: true, allow: [path.resolve(__dirname)] },
    watch: {
      ignored: ['**/dist/**']
    },
    proxy: {
      '/api': {
        target: developmentApiTarget,
        changeOrigin: true,
        secure: false,
        ws: true,
        rewrite: (path) => path,
        configure: (proxy) => {
          forwardPreviewOrigin(proxy)
          proxy.on('error', (err) => {
            console.log('代理错误:', err)
          })
          proxy.on('proxyReq', (proxyReq) => {
            console.log('发送请求到:', proxyReq.path)
          })
          proxy.on('proxyRes', (proxyRes) => {
            console.log('收到响应:', proxyRes.statusCode)
          })
        }
      },
      '/agui': {
        target: developmentApiTarget,
        changeOrigin: true,
        configure: forwardPreviewOrigin,
      },
      '/oss-upload': {
        target: 'https://handlecatchs.oss-cn-beijing.aliyuncs.com',
        changeOrigin: true,
        secure: true,
        agent: ossAgent,
        rewrite: (path) => path.replace(/^\/oss-upload/, ''),
        configure: (proxy) => {
          proxy.on('error', (err) => {
            console.log('OSS 代理错误:', err.message)
          })
          proxy.on('proxyReq', (proxyReq) => {
            console.log('OSS 上传代理:', proxyReq.path)
          })
          proxy.on('proxyRes', (proxyRes) => {
            console.log('OSS 上传响应:', proxyRes.statusCode)
          })
        }
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        silenceDeprecations: ['legacy-js-api']
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true,
    minify: 'terser',
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
          if (id.includes('echarts')) return 'vendor-echarts'
          if (id.includes('vue') || id.includes('pinia')) return 'vendor-vue'
          return 'vendor'
        }
      }
    },
    terserOptions: {
      compress: {
        drop_console: false,
        drop_debugger: true
      }
    }
  }
}
})
