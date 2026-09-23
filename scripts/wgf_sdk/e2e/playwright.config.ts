// Playwright configuration for the sdk module's browser e2e.
//
// Copied into a scratch copy of web-game-template by scripts/wgf_sdk/e2e.py. Runs against
// the production bundle from a preview server, never the dev server, on a port of its own
// so it never reuses a server another worktree started.

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env["WGF_E2E_PORT"] ?? 4461);

export default defineConfig({
  testDir: "tests/wgf-sdk-e2e",
  fullyParallel: true,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: process.env["WGF_E2E_REPORT"] ?? "e2e.json" }]],
  outputDir: "test-results/wgf-sdk-e2e",
  use: { baseURL: `http://localhost:${PORT}` },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
  webServer: {
    command: `pnpm exec vite preview --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
