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
    const turn = contexts.length
    const firstTurn = Math.max(1, turn - 5)
    expect(body.context).toEqual(
      Array.from({ length: turn - firstTurn }, (_, index) => [
        { role: 'user', content: `Question ${firstTurn + index}` },
        { role: 'assistant', content: `Answer ${firstTurn + index}` },
      ]).flat()
    )
    return route.fulfill({ json: {
      answer: `Answer ${contexts.length}`, warnings: [], citations: [], analytics: null,
      refused: false, degraded: false, request_id: `q${contexts.length}`, data_version: 'parity.1',
      conversation_state: { data_version: 'parity.1' },
    } })
  })
  await page.goto('/analyst')
  for (let i = 1; i <= 8; i++) {
    const box = page.getByRole('textbox', { name: 'Ask a season question' })
    await expect(box).toBeEnabled()
    await box.fill(`Question ${i}`)
    await box.press('Enter')
    await expect(page.getByText(`Answer ${i}`, { exact: true })).toBeVisible()
  }
  expect(contexts).toEqual([0, 2, 4, 6, 8, 10, 10, 10])
  const { default: AxeBuilder } = await import('@axe-core/playwright')
  const populated = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(populated.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Archive', exact: true }).click()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await expect(page.getByText('Answer 8', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await expect(page.getByText('Answer 8', { exact: true })).toBeVisible()
})

test('follow-up submits immediately and New chat clears both surfaces', async ({ page }) => {
  const questions: string[] = []
  await page.route('**/api/analysis/query', (route) => {
    const body = route.request().postDataJSON()
    questions.push(body.question)
    return route.fulfill({ json: {
      answer: `Answer ${questions.length}`, warnings: [], citations: [],
      refused: false, degraded: false, data_version: 'parity.1',
      session_token: 'a'.repeat(64), revision: questions.length,
      state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
      follow_up_questions: questions.length === 1 ? ['How did Boston respond?'] : [],
    } })
  })
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Ask the archive' }).fill('How did New York score?')
  await page.getByRole('button', { name: 'Search archive' }).click()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'How did Boston respond?' }).click()
  await expect(page.getByText('Answer 2', { exact: true })).toBeVisible()
  expect(questions).toEqual(['How did New York score?', 'How did Boston respond?'])
  await page.getByRole('link', { name: /Analyst/ }).click()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'New chat' }).click()
  await expect(page.getByRole('textbox', { name: 'Ask a season question' })).toBeFocused()
  await expect(page.getByText('Answer 1', { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByText('Answer 2', { exact: true })).toHaveCount(0)
})

test('interrupted request retries the exact turn after reload', async ({ page }) => {
  let firstTurn = ''
  let calls = 0
  await page.route('**/api/analysis/query', (route) => {
    calls++
    const body = route.request().postDataJSON()
    if (calls === 1) {
      firstTurn = body.turn_id
      return new Promise(() => {})
    }
    expect(body.turn_id).toBe(firstTurn)
    return route.fulfill({ json: {
      answer: 'Recovered answer.', warnings: [], citations: [],
      refused: false, degraded: false, data_version: 'parity.1',
    } })
  })
  await page.goto('/analyst')
  await page.getByRole('textbox', { name: 'Ask a season question' }).fill('What happened?')
  await page.getByRole('button', { name: 'Ask archive' }).click()
  await expect(page.getByText('What happened?', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('A question was interrupted. Retry it when ready.')).toBeVisible()
  await page.getByRole('button', { name: 'Retry question' }).click()
  await expect(page.getByText('Recovered answer.')).toBeVisible()
  await expect(page.getByText('What happened?', { exact: true })).toHaveCount(1)
})

test('session expiry keeps the question and retries with fresh context', async ({ page }) => {
  const requests: { turn_id: string }[] = []
  await page.route('**/api/analysis/query', (route) => {
    const body = route.request().postDataJSON()
    requests.push(body)
    if (requests.length === 1) return route.fulfill({ json: {
      answer: 'First answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1', session_token: 'a'.repeat(64),
      revision: 1, state_committed: true, session_expires_at: '2099-01-01T00:00:00Z',
    } })
    if (requests.length === 2) return route.fulfill({ status: 409,
      json: { detail: { reason: 'session_expired' } } })
    expect(body.session_token).toBeUndefined()
    expect(body.expected_revision).toBe(0)
    expect(body.context).toEqual([])
    expect(body.turn_id).toBe(requests[1].turn_id)
    return route.fulfill({ json: {
      answer: 'Fresh answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1',
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('First answer.')).toBeVisible()
  await box.fill('Second question')
  await box.press('Enter')
  await expect(page.getByText('Session expired. Previous messages remain readable.')).toBeVisible()
  await expect(box).toHaveValue('Second question')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Fresh answer.')).toBeVisible()
  await expect(page.getByText('Second question', { exact: true })).toHaveCount(1)
})

test('late response cannot restore a chat after New chat', async ({ page }) => {
  let finish: (() => void) | undefined
  await page.route('**/api/analysis/query', async (route) => {
    await new Promise<void>((resolve) => { finish = resolve })
    try { await route.fulfill({ json: {
      answer: 'Late answer.', warnings: [], citations: [], degraded: false,
      refused: false, data_version: 'parity.1',
    } }) } catch { /* Request was aborted by New chat. */ }
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('Pending question')
  await box.press('Enter')
  await expect(page.getByText('Reading the season tape…')).toBeVisible()
  await page.getByRole('button', { name: 'New chat' }).click()
  finish?.()
  await expect(page.getByText('Pending question', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Late answer.')).toHaveCount(0)
  await expect(box).toBeEnabled()
})

test('storage failure leaves chat usable and explains refresh recovery', async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => { throw new Error('Storage disabled') }
  })
  await page.route('**/api/analysis/query', (route) => route.fulfill({ json: {
    answer: 'In-memory answer.', warnings: [], citations: [], degraded: false,
    refused: false, data_version: 'parity.1',
  } }))
  await page.goto('/analyst')
  await expect(page.getByText('Refresh recovery is unavailable in this browser.')).toBeVisible()
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('What happened?')
  await box.press('Enter')
  await expect(page.getByText('In-memory answer.')).toBeVisible()
})

test('archive version change keeps history and starts fresh context', async ({ page }) => {
  let version = 'parity.1'
  await page.route('**/api/archive/status*', (route) => route.fulfill({ json: {
    season: '2025-26', data_version: version, games: 101,
  } }))
  const requests: { context: unknown[]; session_token?: string }[] = []
  await page.route('**/api/analysis/query', (route) => {
    const body = route.request().postDataJSON()
    requests.push(body)
    return route.fulfill({ json: {
      answer: `Answer ${requests.length}`, warnings: [], citations: [],
      refused: false, degraded: false, data_version: version,
      session_token: 'a'.repeat(64), revision: 1, state_committed: true,
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  version = 'parity.2'
  await page.reload()
  await expect(page.getByText('Archive updated. Previous messages are history; this is a new conversation.')).toBeVisible()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  await box.fill('New question')
  await box.press('Enter')
  await expect(page.getByText('Answer 2', { exact: true })).toBeVisible()
  expect(requests[1].context).toEqual([])
  expect(requests[1].session_token).toBeUndefined()
})

test('stateless reply remains readable without carrying its session context', async ({ page }) => {
  const contexts: unknown[][] = []
  await page.route('**/api/analysis/query', (route) => {
    const body = route.request().postDataJSON()
    contexts.push(body.context)
    return route.fulfill({ json: {
      answer: `Answer ${contexts.length}`, citations: [], refused: false,
      degraded: true, data_version: 'parity.1',
      warnings: contexts.length === 1
        ? ['Stateless factual fallback: conversation storage unavailable.'] : [],
    } })
  })
  await page.goto('/analyst')
  const box = page.getByRole('textbox', { name: 'Ask a season question' })
  await box.fill('First question')
  await box.press('Enter')
  await expect(page.getByText('Conversation state was unavailable. Start a new conversation from here.')).toBeVisible()
  await box.fill('Second question')
  await box.press('Enter')
  await expect(page.getByText('Answer 2', { exact: true })).toBeVisible()
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible()
  expect(contexts).toEqual([[], []])
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
