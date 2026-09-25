/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API (and the AI key) live server-side; the dev server proxies /api to FastAPI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': `${import.meta.dirname}/src` } },
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
