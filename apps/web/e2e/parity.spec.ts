import AxeBuilder from '@axe-core/playwright'
import { expect, test } from './network-fixture'
import { api, games } from './parity-fixtures'

test.beforeEach(async ({ page }) => {
  // Remote artifact checks use fixtures too: never spend provider budget.
  if (process.env.PLAYWRIGHT_BASE_URL || process.env.PLAYWRIGHT_API_URL) {
    await page.route('https://api.knicksiq.win/**', (route) => route.abort())
  }
  await page.route(api('/archive/status*'), (route) => route.fulfill({ json: {
    season: '2025-26', data_version: 'parity.1', games: 101, matching_games: 101,
    regular_season_games: 101, postseason_games: 0, reports: 101, capabilities: [],
  } }))
  await page.route(api('/games?*'), (route) => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') || 0)
    const limit = Number(url.searchParams.get('limit') || 50)
    return route.fulfill({ json: games.slice(offset, offset + limit) })
  })
  await page.route(api('/reports?*'), (route) => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') || 0)
    return route.fulfill({ json: games.slice(offset, offset + 50).map((game) => ({
      id: game.id, game_id: game.id, title: `Report ${game.id}`, summary: 'Verified game.', created_at: '2026-01-01',
    })) })
  })
})

for (const path of ['games', 'reports']) {
  test(`${path}: extreme page URLs do not crash pagination`, async ({ page }) => {
    await page.route(api('/archive/status*'), async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.fulfill({ json: { games: 101, reports: 101, matching_games: 101 } })
    })
    await page.goto(`/${path}?page=100000000`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Pagination' }).getByRole('button', { name: '1', exact: true })).toBeVisible()
  })
  test(`${path}: server errors stay on the page and can be retried`, async ({ page }) => {
    let fail = true
    await page.route(api(`/${path}?*`), (route) => route.fulfill(fail
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
    const requests: Record<string, string>[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname === `/api/${path}`) {
        requests.push(Object.fromEntries(url.searchParams))
      }
    })
    await page.goto(`/${path}?page=3&seasonType=regular&dataStatus=analysis_ready`)
    const rows = page.locator(path === 'games' ? '.game-row' : '.report-row')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toHaveAttribute('href', new RegExp(`/${path}/101`))
    await page.getByRole('button', { name: '1', exact: true }).click()
    await expect(rows).toHaveCount(50)
    await expect(page).toHaveURL(/page=1/)
    await page.getByRole('button', { name: '2', exact: true }).click()
    await expect(rows).toHaveCount(50)
    await expect(rows.first()).toHaveAttribute('href', new RegExp(`/${path}/51`))
    await expect(page).toHaveURL(/seasonType=regular/)
    await expect(page).toHaveURL(/dataStatus=analysis_ready/)
    expect(requests.map(({ limit, offset }) => ({ limit, offset }))).toEqual([
      { limit: '50', offset: '100' },
      { limit: '50', offset: path === 'games' ? undefined : '0' },
      { limit: '50', offset: '50' },
    ])
    if (path === 'games') {
      expect(requests.every((request) => request.season_type === 'regular' && request.data_status === 'analysis_ready')).toBe(true)
    }
    await test.info().attach('pagination-requests', {
      body: JSON.stringify(requests, null, 2), contentType: 'application/json',
    })
    await test.info().attach('pagination-page-two', {
      body: await page.screenshot(), contentType: 'image/png',
    })
  })
  test(`${path}: invalid page URLs request the first page`, async ({ page }) => {
    const requests: Record<string, string>[] = []
    for (const value of ['0', '-1', '1.5', 'not-a-number', 'Infinity', '9007199254740991']) {
      const request = page.waitForRequest((request) => new URL(request.url()).pathname === `/api/${path}`)
      await page.goto(`/${path}?page=${value}`)
      const url = new URL((await request).url())
      requests.push({ page: value, ...Object.fromEntries(url.searchParams) })
      expect(url.searchParams.get('limit')).toBe('50')
      expect(url.searchParams.get('offset')).toBe(path === 'games' ? null : '0')
      await expect(page.locator(path === 'games' ? '.game-row' : '.report-row')).toHaveCount(50)
      await expect(page.getByRole('navigation', { name: 'Pagination' }).getByRole('button', { name: '1', exact: true })).toHaveAttribute('aria-current', 'page')
    }
    await test.info().attach('invalid-page-requests', {
      body: JSON.stringify(requests, null, 2), contentType: 'application/json',
    })
  })
  test(`${path}: invalid ID stops loading`, async ({ page }) => {
    await page.goto(`/${path}/invalid`)
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText(/Loading (game detail|report)…/)).toHaveCount(0)
  })
}

test('game evidence failure stays distinct from empty and never requests bad stretches', async ({ page }) => {
  const requested: string[] = []
  page.on('request', (request) => requested.push(request.url()))
  await page.route(api('/games/101'), (route) => route.fulfill({ json: games[100] }))
  await page.route(api('/games/101/runs'), (route) => route.fulfill({ status: 503, json: {} }))
  await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [] }))
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
  await page.route(api('/games?*'), (route) => route.fulfill({ json: [game] }))
  await page.route(api('/games/101'), (route) => route.fulfill({ json: game }))
  await page.route(api('/games/101/runs'), (route) => route.fulfill({ json: [] }))
  await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [{ id: 1, period: 4, clock: '00:07', event_type: 'free_throw', description: 'Made free throw', away_score: 94, home_score: 90, score_margin: -4 }] }))
  await page.goto('/games')
  await expect(page.locator('.game-margin')).toHaveText('+4')
  await page.locator('.game-row').click()
  await expect(page.locator('.scoreboard-foot')).toContainText('+4 Knicks margin')
  await expect(page.getByRole('cell', { name: '+4', exact: true })).toBeVisible()
})

test('mobile play-by-play can be reached and scrolled with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await page.route(api('/games/101'), (route) => route.fulfill({ json: games[100] }))
  await page.route(api('/games/101/runs'), (route) => route.fulfill({ json: [] }))
  await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [
    { id: 1, sequence: 1, period: 4, clock: '00:07', event_type: 'free_throw',
      description: 'Made free throw', away_score: 90, home_score: 100, score_margin: 10 },
  ] }))
  await page.goto('/games/101')
  await expect(page.getByRole('table', { name: 'Play-by-play events' })).toBeVisible()

  await page.getByRole('link', { name: 'Back to games' }).focus()
  await page.keyboard.press('Tab')
  const events = page.getByRole('region', { name: 'Play-by-play events', exact: true })
  await expect(events).toBeFocused()
  await expect(events.getByRole('table', { name: 'Play-by-play events' })).toBeVisible()
  const initialScroll = await events.evaluate((element) => element.scrollLeft)
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => events.evaluate((element) => element.scrollLeft)).toBeGreaterThan(initialScroll)
  const focus = await events.evaluate((element) => {
    const style = getComputedStyle(element)
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), offset: parseFloat(style.outlineOffset) }
  })
  expect(focus.style).not.toBe('none')
  expect(focus.width).toBeGreaterThan(0)
  expect(focus.offset).toBeLessThan(0)
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()
  expect(accessibility.violations.filter((violation) =>
    ['serious', 'critical'].includes(violation.impact ?? '')
  )).toEqual([])
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
