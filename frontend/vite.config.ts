import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/static/app/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:7860',
      '/audio': 'http://127.0.0.1:7860',
    },
  },
})
