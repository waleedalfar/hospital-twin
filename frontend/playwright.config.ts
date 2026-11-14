import { defineConfig, devices } from '@playwright/test';

const FRONTEND_URL = 'http://127.0.0.1:5173';
const BACKEND_URL = 'http://127.0.0.1:8000';
const reuse = !process.env.CI;

// Drives the real app: backend + database + frontend (CLAUDE.md §3). `make e2e` starts the database and
// runs migrations first; the servers below are started here unless they are already running.
export default defineConfig({
  testDir: './e2e',
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'test-results/e2e-report.json' }]],
  use: {
    baseURL: FRONTEND_URL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-swiftshader',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          // WebGL in headless Chrome through SwiftShader (CLAUDE.md §3).
          args: [
            '--use-gl=angle',
            '--use-angle=swiftshader',
            '--enable-unsafe-swiftshader',
            '--ignore-gpu-blocklist',
          ],
        },
      },
    },
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run uvicorn twin.api.main:app --host 127.0.0.1 --port 8000',
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: FRONTEND_URL,
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
  ],
});
