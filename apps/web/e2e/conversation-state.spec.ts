import { expect, type Route } from 'playwright/test'
import { api, test } from './parity-fixtures'

test('an abandoned readiness request cannot reset a newer conversation', async ({ page }, info) => {
  let phase = 'unavailable'
  let abandoned: Route | undefined
  await page.route(api('/archive/status*'), async (route) => {
    if (phase === 'unavailable') return route.fulfill({ status: 503, json: {} })
    if (phase === 'abandoned') {
      abandoned = route
      return
    }
    return route.fulfill({ json: { games: 101, data_version: 'new-release' } })
  })
  await page.route(api('/analysis/query'), (route) => route.fulfill({ json: {
    answer: 'Answer from the new release.', citations: [], warnings: [],
    refused: false, degraded: false, data_version: 'new-release',
  } }))
  await page.goto('/analyst')
  await expect(page.getByText('Archive unavailable', { exact: true })).toBeVisible()
  phase = 'abandoned'
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect.poll(() => abandoned !== undefined).toBe(true)
  const navigation = page.getByRole('navigation', { name: 'Primary navigation' })
  phase = 'current'
  await navigation.getByRole('link', { name: 'Games', exact: true }).click()
  await navigation.getByRole('link', { name: 'Analyst', exact: true }).click()
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await expect(box).toBeEnabled()
  await box.fill('How did the Knicks play?')
  await box.press('Enter')
  await expect(page.getByText('Answer from the new release.', { exact: true })).toBeVisible()
  await abandoned!.fulfill({ json: { games: 101, data_version: 'old-release' } }).catch(() => {})
  await page.waitForTimeout(100)
  await expect(page.getByText('Archive updated. Previous messages are history; this is a new conversation.')).toHaveCount(0)
  await info.attach('new-release-conversation', { body: await page.screenshot(), contentType: 'image/png' })
})

test('refresh preserves an edited draft after a failed turn', async ({ page }, info) => {
  await page.route(api('/analysis/query'), (route) => route.abort('failed'))
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await expect(box).toBeEnabled()
  await box.fill('Original failed question')
  await box.press('Enter')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  await box.fill('My revised question')
  await page.reload()
  await expect(box).toHaveValue('My revised question')
  await expect(page.getByRole('button', { name: 'Retry question' })).toBeVisible()
  await info.attach('recovered-edited-draft', { body: await page.screenshot(), contentType: 'image/png' })
})

test('a retryable response preserves the exact turn independently of warning text', async ({ page }, info) => {
  const requests: unknown[] = []
  await page.route(api('/analysis/query'), (route) => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: {
      answer: requests.length === 1 ? 'Turn deadline reached.' : 'Recovered answer.',
      citations: [], warnings: [], refused: false, degraded: requests.length === 1,
      data_version: 'parity.1',
      session_status: requests.length === 1 ? 'retryable' : 'committed',
      state_committed: requests.length > 1,
      session_token: requests.length > 1 ? 'a'.repeat(64) : null,
      revision: requests.length > 1 ? 1 : null,
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await expect(box).toBeEnabled()
  await box.fill('Question to recover')
  await box.press('Enter')
  await expect(page.getByText('Turn deadline reached.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Recovered answer.', { exact: true })).toBeVisible()
  expect(requests[1]).toEqual(requests[0])
  await info.attach('replayed-turn', { body: JSON.stringify(requests), contentType: 'application/json' })
})
