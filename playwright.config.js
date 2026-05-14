const { defineConfig } = require("@playwright/test");

const port = Number(process.env.PAPER_NOTES_E2E_PORT || 4183);
const baseURL = process.env.PAPER_NOTES_E2E_BASE_URL || `http://127.0.0.1:${port}`;

module.exports = defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: process.env.PAPER_NOTES_E2E_BASE_URL
    ? undefined
    : {
        command: `PORT=${port} uv run python main.py`,
        url: `${baseURL}/index.html`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
