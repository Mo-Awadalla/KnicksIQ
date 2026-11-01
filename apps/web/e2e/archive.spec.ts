import { expect, test, type Page } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function mockReadyArchive(page: Page) {
  await page.route('**/api/archive/status', (route) =>
    route.fulfill({
      json: {
        season: '2025-26',
        data_version: 'test.1',
        games: 1,
        regular_season_games: 1,
        postseason_games: 0,
        reports: 0,
        activated_at: '2026-07-01T00:00:00Z',
        capabilities: [],
      },
    })
  )
  await page.route('**/api/games**', (route) =>
    route.fulfill({ json: [{ id: 1 }] })
  )
}

test('public archive loads and exposes policy links', async ({ page }) => {
  const dataRequests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/')) dataRequests.push(path)
  })
  await mockReadyArchive(page)

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('2025-26')
  await expect(page.getByRole('link', { name: 'Privacy' })).toBeVisible()
  await expect(page.getByText('Archive current')).toHaveCount(0)
  await expect(page.getByText('Record', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Ask the archive' })).toBeEnabled()
  expect(dataRequests.sort()).toEqual(['/api/archive/status', '/api/games'])
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    accessibility.violations.filter((violation) =>
      ['serious', 'critical'].includes(violation.impact ?? '')
    )
  ).toEqual([])
})

test('chat stays locked until archive checks finish', async ({ page }) => {
  let releaseGames: () => void = () => undefined
  const gamesReady = new Promise<void>((resolve) => {
    releaseGames = resolve
  })
  await page.route('**/api/archive/status', (route) =>
    route.fulfill({ json: { season: '2025-26', games: 1 } })
  )
  await page.route('**/api/games**', async (route) => {
    await gamesReady
    await route.fulfill({ json: [{ id: 1 }] })
  })

  await page.goto('/')
  const chat = page.getByRole('textbox', { name: 'Ask the archive' })
  await expect(chat).toBeDisabled()
  await expect(page.getByText('Preparing archive')).toBeVisible()
  releaseGames()
  await expect(chat).toBeEnabled()
  await expect(page.getByText('Preparing archive')).toHaveCount(0)
})

test('an archive question makes only the analysis request', async ({ page }) => {
  const dataRequests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/')) dataRequests.push(path)
  })
  await mockReadyArchive(page)
  await page.route('**/api/analysis/query', (route) =>
    route.fulfill({
      json: {
        answer: 'The archive answer.',
        warnings: [],
        citations: [],
        refused: false,
        degraded: false,
        data_version: 'test.1',
        request_id: 'request-1',
        analytics: null,
      },
    })
  )

  await page.goto('/')
  await page
    .getByRole('button', { name: 'What was their best win?' })
    .first()
    .click()
  await expect(page.getByText('The archive answer.')).toBeVisible()
  expect(dataRequests.slice(0, 2).sort()).toEqual([
    '/api/archive/status',
    '/api/games',
  ])
  expect(dataRequests.at(-1)).toBe('/api/analysis/query')
})

test('feedback form posts to the configured Formspree endpoint', async ({ page }) => {
  await page.goto('/feedback.html')

  const form = page.getByRole('button', { name: 'Send feedback' }).locator('..')
  await expect(form).toHaveAttribute('method', 'post')
  await expect(form).toHaveAttribute('action', 'https://formspree.io/f/xaqrndvp')
  await expect(page.getByRole('textbox', { name: 'Message' })).toHaveAttribute('required', '')
  await expect(page.getByRole('combobox', { name: 'Category' })).toHaveAttribute('required', '')
})
