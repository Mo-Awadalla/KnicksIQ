import { defineConfig } from 'playwright/test'

const productionHosts = new Set([
  'api.knicksiq.win', 'www.knicksiq.win', 'knicksiq.win',
  'knicksiq-api.onrender.com', 'knicksiq-web.onrender.com',
])
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173'
const staging = process.env.PLAYWRIGHT_STAGING_ORIGIN
for (const value of [baseURL, process.env.PLAYWRIGHT_API_URL, process.env.PLAYWRIGHT_STAGING_API_ORIGIN].filter(Boolean)) {
  const url = new URL(value!, baseURL)
  if (productionHosts.has(url.hostname)) throw new Error('Production browser verification is forbidden by this suite')
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (!local && url.origin !== staging && url.origin !== process.env.PLAYWRIGHT_STAGING_API_ORIGIN) {
    throw new Error('Remote browser target needs an explicit isolated staging origin')
  }
}

export default defineConfig({
  testDir: './e2e',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL, serviceWorkers: 'block', trace: 'retain-on-failure' },
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : {
    command: 'pnpm build && pnpm preview --host 127.0.0.1 --port 4173',
    env: { VITE_API_URL: '/api' },
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
  },
})
