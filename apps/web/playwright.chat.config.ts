import { defineConfig } from 'playwright/test'

function loopback(value: string): string {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
    throw new Error(`Chat proof requires loopback HTTP: ${value}`)
  }
  return url.origin
}

const baseURL = loopback(process.env.CHAT_E2E_BASE_URL || 'http://127.0.0.1:4174')
const apiURL = loopback(process.env.CHAT_E2E_API_URL || 'http://127.0.0.1:18230')
const upstreamURL = loopback(process.env.CHAT_E2E_UPSTREAM_URL || 'http://127.0.0.1:18930')
if (!process.env.CHAT_E2E_API_URL &&
    (upstreamURL !== 'http://127.0.0.1:18930' ||
     (process.env.CHAT_E2E_REDIS_PORT && process.env.CHAT_E2E_REDIS_PORT !== '19382'))) {
  throw new Error('Custom upstream or Redis requires an externally managed CHAT_E2E_API_URL')
}

export default defineConfig({
  testDir: './e2e',
  testMatch: ['chat-rehaul.spec.ts', 'chat-recovery.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  outputDir: '../../.audit/season-chat-rehaul/proof/playwright-results',
  reporter: [['list'], ['html', { outputFolder: '../../.audit/season-chat-rehaul/proof/playwright-report', open: 'never' }]],
  use: { baseURL, browserName: 'chromium', extraHTTPHeaders: { 'X-Forwarded-Proto': 'https' }, trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'retain-on-failure' },
  webServer: [
    ...(!process.env.CHAT_E2E_API_URL ? [{
      command: 'cd ../api && ../../.venv/bin/python -m app.tests.support.conversation_runtime --api-port 18230 --redis-port 19382 --upstream-port 18930',
      port: Number(new URL(apiURL).port),
      reuseExistingServer: false,
      timeout: 60_000,
    }] : []),
    ...(!process.env.CHAT_E2E_BASE_URL ? [{
      command: 'node e2e/chat-preview.mjs',
      url: baseURL,
      reuseExistingServer: false,
      timeout: 30_000,
    }] : []),
  ],
})
