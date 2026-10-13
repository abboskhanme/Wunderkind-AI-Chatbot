import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// Brand (src/lib/brand.ts, <title>). Build args override these — see
// docker-compose.brand2.yml; set here so they are never undefined.
process.env.VITE_BRAND_NAME ||= 'Wunderkind'
process.env.VITE_BRAND_APP_NAME ||= `${process.env.VITE_BRAND_NAME} AI Agent`

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'],
          charts: ['recharts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/connect': backend,
      '/webhook': backend,
      // Public pages served by the backend: /go/<token>, /f/<form slug>
      '^/(go|f)/': backend,
    },
  },
})
