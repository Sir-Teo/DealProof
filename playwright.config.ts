import { defineConfig, devices } from "@playwright/test";

const E2E_API_BASE_URL = "http://127.0.0.1:8200";
const E2E_APP_BASE_URL = "http://127.0.0.1:3200";

process.env.NEXT_PUBLIC_API_BASE_URL = E2E_API_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: E2E_APP_BASE_URL,
    trace: "on-first-retry"
  },
  workers: 1,
  webServer: [
    {
      command: "rm -rf .tmp/e2e-backend-data && mkdir -p .tmp/e2e-backend-data && cd backend && DEALPROOF_DATA_DIR=../.tmp/e2e-backend-data DEEPSEEK_API_KEY= DEALPROOF_DETERMINISTIC_ANALYSIS=1 DEALPROOF_WEB_SEARCH_ENABLED=0 uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8200",
      url: `${E2E_API_BASE_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000
    },
    {
      command: `NEXT_PUBLIC_API_BASE_URL=${E2E_API_BASE_URL} npm run build && NEXT_PUBLIC_API_BASE_URL=${E2E_API_BASE_URL} npx next start --hostname 127.0.0.1 --port 3200`,
      url: E2E_APP_BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000
    }
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } }
  ]
});
