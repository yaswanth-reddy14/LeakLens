import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'LEAKLENS_')
  const proxy = { '/api': env.LEAKLENS_API_TARGET || 'http://127.0.0.1:8000' }
  return {
    plugins: [react()],
    // Concurrent local, recording and hosted-test frontends must not replace
    // one another's optimized dependencies when their environment differs.
    cacheDir: env.LEAKLENS_VITE_CACHE || 'node_modules/.vite',
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, strictPort: true, proxy },
  }
})
