import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({ plugins: [react()], server: { port: 5174, fs: { strict: true, allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('../frontend/src/utils', import.meta.url)), fileURLToPath(new URL('../frontend/src/assets', import.meta.url))] }, proxy: {
  '/agui': { target: process.env.DOORHANDLE_API_TARGET || 'http://127.0.0.1:8080', changeOrigin: true },
  '/api': { target: process.env.DOORHANDLE_API_TARGET || 'http://127.0.0.1:8080', changeOrigin: true },
} } });
