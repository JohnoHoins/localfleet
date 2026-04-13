import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/monitor': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        monitor: 'monitor.html',
      },
    },
  },
})
