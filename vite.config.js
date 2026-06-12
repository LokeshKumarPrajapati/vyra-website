import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ['pixi.js', 'pixi-live2d-display/cubism4'],
    exclude: [],
  },
  resolve: {
    alias: {},
  },
})
