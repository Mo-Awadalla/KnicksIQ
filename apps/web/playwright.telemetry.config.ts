import { defineConfig } from 'playwright/test'

const baseURL = new URL(process.env.CHAT_E2E_BASE_URL || 'http://127.0.0.1:4174')
if (baseURL.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(baseURL.hostname)) {
  throw new Error('Telemetry proof requires HTTP loopback')
}
export default defineConfig({
  testDir: './e2e',
  testMatch: 'browser-telemetry.spec.ts',
  workers: 1,
  retries: 0,
  use: { baseURL: baseURL.origin, browserName: 'chromium' },
  webServer: !process.env.CHAT_E2E_BASE_URL ? {
    command: 'node e2e/chat-preview.mjs',
    url: baseURL.origin,
    reuseExistingServer: false,
  } : undefined,
})
