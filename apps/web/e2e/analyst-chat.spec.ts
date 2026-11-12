import { expect, type Route } from 'playwright/test'
import { api, test } from './parity-fixtures'

// Consumer risks: an offscreen phone composer, losing an in-progress draft,
// pulling a reader away from history, or reopening a saved thread at the wrong turn.
const longAnswer = Array.from({ length: 30 }, (_, index) =>
  `Possession ${index + 1}: the archive records the score and the players involved. These observed events do not establish why the result happened.`
).join('\n\n')

function answer(text: string, revision: number) {
  return {
    answer: text,
    citations: [{
      claim: 'New York 100, Boston 90.', type: 'archive', title: 'Game record',
      game_id: 1, source_name: 'NBA', metadata: {},
    }],
    warnings: [], refused: false, degraded: false, data_version: 'parity.1',
    session_status: 'committed', state_committed: true,
    session_token: 'e'.repeat(64), revision,
  }
}

test.afterEach(async ({ page }, info) => {
  await info.attach('chat-surface', {
    body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
  })
})

for (const viewport of [{ width: 320, height: 740 }, { width: 390, height: 844 }]) {
  test(`phone chat keeps the composer visible at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/analyst')
    const input = page.getByRole('textbox', { name: 'Ask a season question' })
    await expect(input).toBeEnabled()
    await expect(page.getByRole('heading', { level: 2 })).toBeInViewport({ ratio: 1 })
    await expect(page.getByRole('button', { name: 'Jump to latest' })).not.toBeVisible()
    await input.fill('What was the final score?')
    await expect(input).toBeInViewport({ ratio: 1 })
    await expect(page.getByRole('button', { name: 'Ask archive', exact: true }))
      .toBeInViewport({ ratio: 1 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    expect(overflow).toBe(false)
  })
}

test('reply arrival preserves the reader and their next draft, then restores the latest turn', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  let requests = 0
  let pending: Route | undefined
  await page.route(api('/analysis/query'), (route) => {
    requests += 1
    if (requests === 1) return route.fulfill({ json: answer(longAnswer, 1) })
    pending = route
  })
  await page.goto('/analyst')
  const input = page.getByRole('textbox', { name: 'Ask a season question' })
  await expect(input).toBeEnabled()
  await input.fill('Describe the game from the archived possessions.')
  await input.press('Enter')
  await expect(input).toBeFocused()
  await expect(page.getByText(longAnswer, { exact: true })).toBeAttached()
  await input.fill('How did the fourth quarter finish?')
  await input.press('Enter')
  await expect.poll(() => Boolean(pending)).toBe(true)

  // Drafting the next question is independent of the in-flight turn.
  await expect(input).toBeEditable()
  await input.fill('My next question is still a draft')
  const viewport = page.locator('[data-slot="message-scroller-viewport"]')
  await viewport.hover()
  await page.mouse.wheel(0, -900)
  const jump = page.getByRole('button', { name: 'Jump to latest' })
  await expect(jump).toBeVisible()
  const before = await viewport.evaluate((element) => element.scrollTop)
  await input.focus()
  await pending!.fulfill({ json: answer('The Knicks finished the fourth quarter with the lead.', 2) })
  await expect(page.getByText('The Knicks finished the fourth quarter with the lead.', { exact: true }))
    .toBeAttached()
  await expect(input).toHaveValue('My next question is still a draft')
  await expect(input).toBeFocused()
  await expect.poll(async () => Math.abs(await viewport.evaluate((element) => element.scrollTop) - before))
    .toBeLessThan(4)
  await jump.click()
  const sources = page.getByText('Sources (1)', { exact: true }).last()
  await expect(sources).toBeInViewport()
  await sources.click()
  await expect(page.getByText('New York 100, Boston 90.', { exact: true }).last()).toBeVisible()

  await page.reload()
  await expect(input).toHaveValue('My next question is still a draft')
  await expect(page.getByText('How did the fourth quarter finish?', { exact: true })).toBeInViewport()
  await expect(page.getByRole('button', { name: 'Ask archive', exact: true })).toBeInViewport()
})
