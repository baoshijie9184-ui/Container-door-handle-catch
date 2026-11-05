import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export default defineConfig(({ command }) => {
  if (command === 'serve') {
    if (!process.env.DOORHANDLE_API_TARGET) throw new Error('Set DOORHANDLE_API_TARGET to the ECS gateway');
    execFileSync(process.env.PYTHON_EXE || 'python3', ['-B', fileURLToPath(new URL('../scripts/ecs_execution.py', import.meta.url))], { stdio: 'inherit' });
  }
  return { plugins: [react()], server: { port: 5174, fs: { strict: true, allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('../frontend/src/utils', import.meta.url)), fileURLToPath(new URL('../frontend/src/assets', import.meta.url))] }, proxy: {
  '/agui': { target: process.env.DOORHANDLE_API_TARGET || '', changeOrigin: true },
  '/api': { target: process.env.DOORHANDLE_API_TARGET || '', changeOrigin: true },
} } };
});
