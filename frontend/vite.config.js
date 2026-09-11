import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import https from 'https'

// OSS 代理专用 Agent，复用连接避免每次 TCP/TLS 握手
const ossAgent = new https.Agent({
  keepAlive: true,
  keepAliveMsecs: 30000,
  maxSockets: 20,
  maxFreeSockets: 10,
  timeout: 60000
})

export default defineConfig({
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
    open: true,
    watch: {
      ignored: ['**/dist/**']
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        secure: false,
        ws: true,
        rewrite: (path) => path,
        configure: (proxy) => {
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
})
