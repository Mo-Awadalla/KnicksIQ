import { expect, test } from './network-fixture'

test('unmatched external requests are blocked before network I/O and recorded', async ({ page, baseURL, networkEvidence }) => {
  networkEvidence.expectedBlocked = 1
  // This probe tests routing, not app readiness or font loading. A same-origin
  // document avoids unrelated in-flight startup requests racing test teardown.
  await page.route(new URL('/', baseURL!).href, route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Network isolation probe</title>',
  }))
  await page.goto('/')
  const result = await page.evaluate(async () => {
    try {
      await fetch('https://production-probe.invalid/analysis/query', { method: 'POST', body: '{}' })
      return 'unexpected success'
    } catch {
      return 'blocked'
    }
  })
  expect(result).toBe('blocked')
  expect(networkEvidence.blocked).toEqual(['https://production-probe.invalid/analysis/query'])
})
