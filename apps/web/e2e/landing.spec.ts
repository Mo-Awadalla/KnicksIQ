import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test, type Page } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function readyArchive(page: Page) {
  await page.route('**/api/archive/status*', (route) => route.fulfill({ json: {
    season: '2025-26', data_version: 'landing.test', games: 1,
  } }))
  await page.route('**/api/games?*', (route) => route.fulfill({ json: [{ id: 1 }] }))
}

for (const width of [390, 735, 768, 1024, 1440]) {
  test(`landing reflows and stays accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await readyArchive(page)
    await page.goto('/')
    await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeEnabled()
    await page.evaluate(() => document.fonts.ready)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const audit = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()
    expect(audit.violations.filter((v) => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([])
    const dir = path.resolve('../../.impeccable/review')
    await mkdir(dir, { recursive: true })
    await page.screenshot({ path: path.join(dir, `${width === 1440 ? 'desktop' : width === 390 ? 'mobile' : `width-${width}`}.png`), fullPage: true, animations: 'disabled' })
    await page.getByRole('link', { name: 'Ask the archive', exact: true }).click()
    await expect(page).toHaveURL(/#archive-desk$/)
    await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeInViewport()
  })
}

test('landing keyboard submission preserves newlines and recovers from a failed answer', async ({ page }) => {
  await readyArchive(page)
  let fail = true
  let submitted = ''
  await page.route('**/api/analysis/query', (route) => {
    submitted = route.request().postDataJSON().question
    return route.fulfill(fail ? { status: 503, json: { detail: 'Temporarily unavailable' } } : { json: {
      answer: 'A test answer with game evidence.', warnings: [], citations: [], analytics: null,
      refused: false, degraded: false, request_id: 'landing-1', data_version: 'landing.test',
    } })
  })
  await page.goto('/')
  await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeEnabled()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to archive search' })).toBeFocused()
  await page.keyboard.press('Enter')
  const question = page.getByRole('textbox', { name: 'Ask the archive' })
  await question.fill('How did the Knicks play')
  await question.press('Shift+Enter')
  await expect(question).toHaveValue('How did the Knicks play\n')
  await question.press('Enter')
  await expect(page.getByRole('alert')).toContainText('That question couldn’t be answered.')
  expect(submitted).toBe('How did the Knicks play')
  fail = false
  await page.getByRole('button', { name: 'Retry question' }).click()
  await expect(page.getByText('A test answer with game evidence.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Answer', exact: true })).toBeFocused()
})

test('landing readiness error locks questions and offers recovery', async ({ page }) => {
  await page.route('**/api/archive/status*', (route) => route.fulfill({ status: 503, json: {} }))
  await page.goto('/')
  await expect(page.getByText('Archive unavailable', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeDisabled()
  await readyArchive(page)
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeEnabled()
})
