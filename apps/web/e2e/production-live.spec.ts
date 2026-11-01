import { execFileSync } from 'node:child_process'
import { expect, test } from 'playwright/test'

const live = process.env.KNICKSIQ_LIVE_E2E === '1'
const apiUrl = process.env.KNICKSIQ_LIVE_API_URL || 'http://127.0.0.1:18432'
const redisContainer = process.env.KNICKSIQ_LIVE_REDIS_CONTAINER || 'kiq-complete-redis'

test.describe('approved archive through the actual production-profile API', () => {
  test.skip(!live, 'Requires the isolated approved 2025-26.20260928.1 archive and unsampled shadow profile.')

  test.beforeEach(async ({ baseURL }) => {
    expect(['127.0.0.1', 'localhost']).toContain(new URL(String(baseURL)).hostname)
    expect(['127.0.0.1', 'localhost']).toContain(new URL(apiUrl).hostname)
  })

  const cases = [
    {
      question: 'Who beat the Knicks by the most points?',
      expected: [/Detroit|DET/i, /38/, /118/, /80/, /2026-02-06|Feb(?:ruary)?\s+6/i],
    },
    {
      question: 'What was their best win?',
      expected: [/Brooklyn|BKN/i, /54/, /120/, /66/],
    },
    {
      question: 'When was the longest losing streak?',
      expected: [/4(?:-game|\s+(?:consecutive\s+)?(?:games|losses))/, /2025-12-31|Dec(?:ember)?\s+31/i, /2026-01-05|Jan(?:uary)?\s+5/i, /2026-01-14|Jan(?:uary)?\s+14/i, /2026-01-19|Jan(?:uary)?\s+19/i],
    },
  ]

  for (const scenario of cases) {
    test(scenario.question, async ({ page }, testInfo) => {
      await page.goto('/')
      const entry = page.getByRole('textbox', { name: 'Ask the archive' })
      await expect(entry).toBeEnabled()
      const delivered = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/analysis/query')
      await entry.fill(scenario.question)
      await entry.press('Enter')
      const response = await delivered
      expect(response.status()).toBe(200)
      const body = await response.json()
      expect(body.data_version).toBe('2025-26.20260928.1')
      for (const expected of scenario.expected) {
        await expect(page.locator('.archive-answer-copy').last()).toContainText(expected)
      }
      await testInfo.attach('delivered-answer', { body: JSON.stringify({ question: scenario.question, answer: body.answer, citations: body.citations }), contentType: 'application/json' })
      await testInfo.attach('actual-browser', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
    })
  }

  test('intentional unsampled shadow delivery is not a service failure', async ({ page }, testInfo) => {
    await page.goto('/')
    const entry = page.getByRole('textbox', { name: 'Ask the archive' })
    await expect(entry).toBeEnabled()
    const delivered = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/analysis/query')
    await entry.fill('What was the Knicks record this season?')
    await entry.press('Enter')
    const response = await delivered
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.llm_validated).toBe(false)
    expect(body.degraded).toBe(false)
    expect(body.warnings).toEqual([])
    expect(body.citations).toEqual(expect.arrayContaining([expect.objectContaining({ metadata: expect.objectContaining({ claim: expect.objectContaining({ metric_id: 'wins', value: 69 }) }) })]))
    await testInfo.attach('delivery-outcome', { body: JSON.stringify({ degraded: body.degraded, warnings: body.warnings, answer: body.answer }), contentType: 'application/json' })
    await testInfo.attach('actual-browser', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
  })

  test('an evicted session recovers through the retry control', async ({ page }, testInfo) => {
    expect(['127.0.0.1', 'localhost']).toContain(new URL(String(testInfo.project.use.baseURL)).hostname)
    await page.goto('/')
    const entry = page.getByRole('textbox', { name: 'Ask the archive' })
    await expect(entry).toBeEnabled()
    const first = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/analysis/query')
    await entry.fill('What was the Knicks record this season?')
    await entry.press('Enter')
    const session = await (await first).json()
    expect(session.session_token).toMatch(/^[a-f0-9]{64}$/)
    execFileSync('docker', ['exec', redisContainer, 'redis-cli', 'DEL', `analyst:{${session.session_token}}`])
    const expired = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/analysis/query')
    await entry.fill('What was the Knicks record this season?')
    await entry.press('Enter')
    const conflict = await expired
    expect(conflict.status()).toBe(409)
    expect((await conflict.json()).error.code).toBe('session_expired')
    const retried = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/analysis/query')
    await page.getByRole('button', { name: 'Retry question' }).click()
    const recovered = await retried
    expect(recovered.status()).toBe(200)
    const body = await recovered.json()
    expect(body.revision).toBe(1)
    expect(body.session_token).not.toBe(session.session_token)
    expect(body.citations).toEqual(expect.arrayContaining([expect.objectContaining({ metadata: expect.objectContaining({ claim: expect.objectContaining({ metric_id: 'wins', value: 69 }) }) })]))
    await testInfo.attach('actual-browser', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
  })

  test('oversized public requests are rejected before analysis', async ({ request }, testInfo) => {
    const response = await request.post(`${apiUrl}/analysis/query`, {
      headers: { 'X-Forwarded-Proto': 'https' },
      data: { question: 'What was the Knicks record this season?', ignored_extra: 'x'.repeat(1048576) },
    })
    expect(response.status()).toBe(413)
    await testInfo.attach('body-limit-response', { body: await response.body(), contentType: 'application/json' })
  })

  for (const invalid of [
    { season: '2025-26'.repeat(200) },
    { ignored_extra: 'not part of the public contract' },
    { context: Array.from({ length: 13 }, () => ({ role: 'user', content: 'A prior question.' })) },
  ]) {
    test(`rejects invalid auxiliary request fields ${Object.keys(invalid)[0]}`, async ({ request }) => {
      const response = await request.post(`${apiUrl}/analysis/query`, {
        headers: { 'X-Forwarded-Proto': 'https' },
        data: { question: 'What was the Knicks record this season?', ...invalid },
      })
      expect(response.status()).toBe(422)
    })
  }

  for (const supplied of ['bad id', 'x'.repeat(129)]) {
    test(`correlates a rejected request with an invalid identifier of length ${supplied.length}`, async ({ request }) => {
      const response = await request.post(`${apiUrl}/analysis/query`, {
        headers: { 'X-Forwarded-Proto': 'https', 'X-Request-ID': supplied },
        data: { question: 'What was the Knicks record this season?', ignored_extra: 'x'.repeat(1048576) },
      })
      expect(response.status()).toBe(413)
      const body = await response.json()
      expect(body.error.code).toBe('request_too_large')
      expect(body.request_id).toMatch(/^[A-Za-z0-9._:-]{1,128}$/)
      expect(response.headers()['x-request-id']).toBe(body.request_id)
    })
  }
})
