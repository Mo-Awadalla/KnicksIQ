import { test as base, expect } from 'playwright/test'

type NetworkEvidence = {
  destinations: Array<{ method: string; url: string }>
  blocked: string[]
  expectedBlocked: number
}

export const test = base.extend<{ networkEvidence: NetworkEvidence }>({
  networkEvidence: [async ({ page, baseURL }, use, testInfo) => {
    const context = page.context()
    const evidence: NetworkEvidence = { destinations: [], blocked: [], expectedBlocked: 0 }
    const allowed = new Set([new URL(baseURL!).origin])
    const assetOrigins = new Set(['https://fonts.googleapis.com', 'https://fonts.gstatic.com'])
    if (process.env.PLAYWRIGHT_STAGING_API_ORIGIN) {
      allowed.add(new URL(process.env.PLAYWRIGHT_STAGING_API_ORIGIN).origin)
    }
    context.on('request', request => {
      const url = new URL(request.url())
      evidence.destinations.push({ method: request.method(), url: url.origin + url.pathname })
    })
    // Page-level fixtures may fulfill synthetic requests. Unmatched requests must
    // pass this context-level guard before any actual HTTP request is dispatched.
    await context.route('**/*', async route => {
      const url = new URL(route.request().url())
      const permittedAsset = assetOrigins.has(url.origin) && route.request().method() === 'GET'
      if (allowed.has(url.origin) || permittedAsset) {
        const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 })
        const location = response.headers()['location']
        if (location && !allowed.has(new URL(location, url).origin)) {
          evidence.blocked.push(new URL(location, url).origin + new URL(location, url).pathname)
          return route.abort('blockedbyclient')
        }
        // Reject network redirects rather than permit an uninspected follow-on hop.
        if (response.status() >= 300 && response.status() < 400 && location) {
          evidence.blocked.push(new URL(location, url).origin + new URL(location, url).pathname)
          return route.abort('blockedbyclient')
        }
        return route.fulfill({ response })
      }
      evidence.blocked.push(url.origin + url.pathname)
      await route.abort('blockedbyclient')
    })
    await use(evidence)
    // Font requests can outlive the assertion that ends a fast navigation test.
    // Settle the browser's font loading before removing its interception handlers.
    if (!page.isClosed()) await page.evaluate(() => document.fonts.ready.then(() => undefined))
    // Drain interception before Playwright tears down the page and its context.
    await context.unrouteAll({ behavior: 'wait' })
    await testInfo.attach('network-destinations', {
      body: JSON.stringify({ allowedOrigins: [...allowed], assetOrigins: [...assetOrigins], ...evidence }, null, 2),
      contentType: 'application/json',
    })
    expect(evidence.blocked.length, 'Unexpected off-origin request; see network-destinations').toBe(evidence.expectedBlocked)
  }, { auto: true }],
})
export { expect }
