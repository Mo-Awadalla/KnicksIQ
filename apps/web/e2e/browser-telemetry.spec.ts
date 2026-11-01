import { expect, test } from 'playwright/test'

const enabled = process.env.KNICKSIQ_TELEMETRY_E2E === '1'
const marker = 'KIQ_FRONTEND_PRIVATE_20261030'
const probeType = 'KnicksPrivacyProbe'
const sink = 'http://127.0.0.1:19499/'

test('browser error telemetry removes question text before transport', async ({ page, baseURL }, testInfo) => {
  test.skip(!enabled, 'Requires a build with the loopback-only telemetry probe DSN.')
  expect(['127.0.0.1', 'localhost']).toContain(new URL(String(baseURL)).hostname)
  const forbiddenPosts: string[] = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.url().startsWith(sink)) {
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'POST, OPTIONS',
          'access-control-allow-headers': '*',
          'access-control-allow-private-network': 'true',
        },
        contentType: 'application/json',
        body: '{}',
      })
      return
    }
    if (request.method() !== 'GET' && !['127.0.0.1', 'localhost'].includes(url.hostname)) {
      forbiddenPosts.push(url.origin)
      await route.abort()
      return
    }
    await route.continue()
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const delivered = page.waitForRequest((request) =>
    request.url().startsWith(sink) && (request.postData() || '').includes(probeType)
  )
  await page.addScriptTag({
    content: `setTimeout(() => { const error = new Error('${marker}'); error.name = '${probeType}'; throw error; }, 0);`,
  })
  const raw = (await delivered).postData() || ''
  const event = raw.trim().split('\n').map((line) => JSON.parse(line)).find((item) =>
    item.exception?.values?.some((exception: { type?: string }) => exception.type === probeType)
  )
  expect(event.exception.values).toEqual(expect.arrayContaining([
    expect.objectContaining({ type: probeType, value: '<redacted>' }),
  ]))
  expect(raw).not.toContain(marker)
  expect(forbiddenPosts).toEqual([])
  await testInfo.attach('browser-telemetry-result', {
    body: JSON.stringify({
      sdk: event.sdk,
      eventType: probeType,
      rawMarkerRetained: raw.includes(marker),
      externalPosts: forbiddenPosts,
    }),
    contentType: 'application/json',
  })
})
