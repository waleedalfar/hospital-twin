import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const BACKEND = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000';

// The browser always talks to /api and /ws on its own origin. In development Vite forwards them to the
// backend; in production Caddy does the same (PROMPT.md §12).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
});
