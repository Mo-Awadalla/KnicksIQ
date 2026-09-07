import { expect, test } from 'playwright/test'

const games = Array.from({ length: 101 }, (_, index) => ({
  id: index + 1, nba_game_id: `nba-${index + 1}`, season: '2025-26',
  game_date: '2026-01-01', home_team_id: 'NYK', away_team_id: 'BOS',
  home_score: 100, away_score: 90, winner_team_id: 'NYK', status: 'final',
  season_type: 'regular', data_status: 'analysis_ready', margin: 10,
}))

test.beforeEach(async ({ page }) => {
  await page.route('**/api/archive/status*', (route) => route.fulfill({ json: {
    season: '2025-26', data_version: 'parity.1', games: 101, matching_games: 101,
    regular_season_games: 101, postseason_games: 0, reports: 101, capabilities: [],
  } }))
  await page.route('**/api/games?*', (route) => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') || 0)
    const limit = Number(url.searchParams.get('limit') || 50)
    return route.fulfill({ json: games.slice(offset, offset + limit) })
  })
  await page.route('**/api/reports?*', (route) => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') || 0)
    return route.fulfill({ json: games.slice(offset, offset + 50).map((game) => ({
      id: game.id, game_id: game.id, title: `Report ${game.id}`, summary: 'Verified game.', created_at: '2026-01-01',
    })) })
  })
})

for (const path of ['games', 'reports']) {
  test(`${path}: extreme page URLs do not crash pagination`, async ({ page }) => {
    await page.route('**/api/archive/status*', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.fulfill({ json: { games: 101, reports: 101, matching_games: 101 } })
    })
    await page.goto(`/${path}?page=100000000`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Pagination' }).getByRole('button', { name: '1', exact: true })).toBeVisible()
  })
  test(`${path}: server errors stay on the page and can be retried`, async ({ page }) => {
    let fail = true
    await page.route(`**/api/${path}?*`, (route) => route.fulfill(fail
      ? { status: 500, json: { detail: 'Temporary failure' } }
      : { json: [] }))
    await page.goto(`/${path}`)
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(new RegExp(`/${path}$`))
    fail = false
    await page.getByRole('button', { name: 'Try again', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('status')).toContainText(path === 'games' ? 'No games match' : 'No reviewed reports')
  })
  test(`${path}: item 101 and URL pagination`, async ({ page }) => {
    await page.goto(`/${path}?page=3`)
    const rows = page.locator(path === 'games' ? '.game-row' : '.report-row')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toHaveAttribute('href', new RegExp(`/${path}/101`))
    await page.getByRole('button', { name: '1', exact: true }).click()
    await expect(rows).toHaveCount(50)
    await expect(page).toHaveURL(/page=1/)
    await page.getByRole('button', { name: '2', exact: true }).click()
    await expect(rows.first()).toHaveAttribute('href', new RegExp(`/${path}/51`))
  })
  test(`${path}: invalid ID stops loading`, async ({ page }) => {
    await page.goto(`/${path}/invalid`)
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText(/Loading (game detail|report)…/)).toHaveCount(0)
  })
}

test('analyst retains full conversation across client navigation with bounded context', async ({ page }) => {
  const contexts: number[] = []
  await page.route('**/api/analysis/query', (route) => {
    const body = route.request().postDataJSON()
    contexts.push(body.context.length)
    return route.fulfill({ json: {
      answer: `Answer ${contexts.length}`, warnings: [], citations: [], analytics: null,
      refused: false, degraded: false, request_id: `q${contexts.length}`, data_version: 'parity.1',
      conversation_state: { data_version: 'parity.1' },
    } })
  })
  await page.goto('/analyst')
  for (let i = 1; i <= 5; i++) {
    const box = page.getByRole('textbox', { name: 'Ask a season question' })
    await expect(box).toBeEnabled()
    await box.fill(`Question ${i}`)
    await box.press('Enter')
    await expect(page.getByText(`Answer ${i}`, { exact: true })).toBeVisible()
  }
  expect(contexts).toEqual([0, 2, 4, 4, 4])
  const { default: AxeBuilder } = await import('@axe-core/playwright')
  const populated = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(populated.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Archive', exact: true }).click()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await expect(page.getByText('Answer 5', { exact: true })).toBeVisible()
})

test('readiness has a slow-start message, deadline and explicit retry', async ({ page }) => {
  await page.clock.install()
  await page.route('**/api/archive/status*', () => new Promise(() => {}))
  await page.goto('/analyst')
  await expect(page.getByText('Preparing archive')).toBeVisible()
  await page.clock.runFor(5001)
  await expect(page.getByText('The archive is starting slowly. Please wait…')).toBeVisible()
  await page.clock.runFor(55001)
  await expect(page.getByText('Archive unavailable', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox')).toBeDisabled()
  await page.route('**/api/archive/status*', (route) => route.fulfill({ json: {
    games: 101, data_version: 'parity.1',
  } }))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('textbox')).toBeEnabled()
})

test('game evidence failure stays distinct from empty and never requests bad stretches', async ({ page }) => {
  const requested: string[] = []
  page.on('request', (request) => requested.push(request.url()))
  await page.route('**/api/games/101', (route) => route.fulfill({ json: games[100] }))
  await page.route('**/api/games/101/runs', (route) => route.fulfill({ status: 503, json: {} }))
  await page.route('**/api/games/101/play-by-play', (route) => route.fulfill({ json: [] }))
  await page.goto('/games/101?page=3')
  await expect(page.getByText('Runs could not be loaded.')).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('No play-by-play events were returned for this game.')).toBeVisible()
  expect(requested.some((url) => url.includes('bad-stretches'))).toBe(false)
  await page.getByRole('link', { name: 'Back to games' }).click()
  await expect(page).toHaveURL(/page=3/)
  await expect(page.locator('.game-row')).toHaveCount(1)
})

test('away wins show the Knicks margin in the ledger and game evidence', async ({ page }) => {
  const game = { ...games[100], home_team_id: 'SAS', away_team_id: 'NYK', home_score: 90, away_score: 94, margin: -4 }
  await page.route('**/api/games?*', (route) => route.fulfill({ json: [game] }))
  await page.route('**/api/games/101', (route) => route.fulfill({ json: game }))
  await page.route('**/api/games/101/runs', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/games/101/play-by-play', (route) => route.fulfill({ json: [{ id: 1, period: 4, clock: '00:07', event_type: 'free_throw', description: 'Made free throw', away_score: 94, home_score: 90, score_margin: -4 }] }))
  await page.goto('/games')
  await expect(page.locator('.game-margin')).toHaveText('+4')
  await page.locator('.game-row').click()
  await expect(page.locator('.scoreboard-foot')).toContainText('+4 Knicks margin')
  await expect(page.getByRole('cell', { name: '+4', exact: true })).toBeVisible()
})

for (const width of [390, 1440]) {
  test(`archive routes have no serious accessibility findings at ${width}px`, async ({ page }) => {
    const { default: AxeBuilder } = await import('@axe-core/playwright')
    await page.setViewportSize({ width, height: 900 })
    for (const path of ['/games', '/reports', '/analyst']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
      expect(results.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
  })
}
