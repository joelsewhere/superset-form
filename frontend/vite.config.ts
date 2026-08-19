import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Bind-mounted source inside Docker does not emit inotify events on all
    // hosts; polling keeps hot reload working.
    watch: { usePolling: true },
  },
})
