import { defineConfig } from "@playwright/test"
import { fileURLToPath } from "node:url"

const apiPort = 18080
const webPort = 14173
const frontend = fileURLToPath(new URL("./", import.meta.url))
const backend = fileURLToPath(new URL("../backend/", import.meta.url))
const database = fileURLToPath(new URL("./test-results/fixture.sqlite3", import.meta.url))

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 850 },
    launchOptions: { executablePath: process.env.SMARTDOC_TEST_CHROMIUM },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run --frozen python -m smartdoc",
      cwd: backend,
      url: `http://127.0.0.1:${apiPort}/api/v1/health/live`,
      env: {
        SMARTDOC_PORT: String(apiPort),
        SMARTDOC_HOST: "127.0.0.1",
        SMARTDOC_DATABASE_PATH: database,
      },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npm run preview -- --port ${webPort}`,
      cwd: frontend,
      url: `http://127.0.0.1:${webPort}`,
      env: { SMARTDOC_API_ORIGIN: `http://127.0.0.1:${apiPort}` },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
})
