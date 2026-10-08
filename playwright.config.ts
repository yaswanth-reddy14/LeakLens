import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 15000 },
  use: { baseURL: 'http://127.0.0.1:5174', browserName: 'chromium', trace: 'retain-on-failure' },
  reporter: 'list',
  webServer: [
    {
      command:
        process.platform === 'win32'
          ? '.venv\\Scripts\\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001'
          : '.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001',
      // Wait for the persisted workspace, not only the liveness route.
      url: 'http://127.0.0.1:8001/api/workspace?scope=uploads',
      env: { LEAKLENS_DB_PATH: '.tools/e2e.sqlite3', LEAKLENS_STORAGE: 'sqlite' },
      reuseExistingServer: false,
    },
    {
      command:
        'npm run build -- --outDir .tools/e2e-dist && npm run preview -- --port 5174 --outDir .tools/e2e-dist',
      url: 'http://127.0.0.1:5174/api/health',
      env: {
        LEAKLENS_API_TARGET: 'http://127.0.0.1:8001',
        LEAKLENS_VITE_CACHE: '.tools/vite-e2e-local',
        VITE_HOSTED_DEMO: 'false',
        VITE_API_BASE_URL: '',
      },
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command:
        'npm run build -- --outDir .tools/e2e-hosted-dist && npm run preview -- --port 5175 --outDir .tools/e2e-hosted-dist',
      url: 'http://127.0.0.1:5175',
      env: {
        VITE_HOSTED_DEMO: 'true',
        VITE_API_BASE_URL: 'https://mock-api.example.com',
        LEAKLENS_VITE_CACHE: '.tools/vite-e2e-hosted',
      },
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
})
