import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => {
  // Load .env from the project root (two levels up from dashboard/ui/)
  const rootEnv = loadEnv(mode, path.resolve(__dirname, '../..'), '')
  const apiPort = rootEnv.DASHBOARD_API_PORT || process.env.DASHBOARD_API_PORT || '8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/api': {
          target: `http://localhost:${apiPort}`,
          changeOrigin: true,
        },
      },
    },
  }
})
