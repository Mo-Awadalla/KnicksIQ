import { expect } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { api, games, test } from './parity-fixtures'

const stats = {
  team_id: 'NYK', points: 100, rebounds: 45, assists: 22,
  steals: 6, blocks: 4, turnovers: 10, personal_fouls: 15,
  offensive_rebounds: 10, defensive_rebounds: 35,
  field_goals_made: 40, field_goals_attempted: 80,
  three_pointers_made: 10, three_pointers_attempted: 25,
  free_throws_made: 10, free_throws_attempted: 12, plus_minus: 10,
}
const boxScore = {
  game_id: 101, periods: [], teams: [stats],
  players: [{ ...stats, player_id: 1, player_name: 'Synthetic Player',
    points: 24, rebounds: 5, assists: 8, minutes: 34.5, starter: true, position: 'G' }],
}

for (const width of [390, 1440]) {
  test(`game box score shows team and player statistics at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route(api('/games/101'), (route) => route.fulfill({ json: games[100] }))
    await page.route(api('/games/101/box-score'), (route) => route.fulfill({ json: boxScore }))
    await page.route(api('/games/101/runs'), (route) => route.fulfill({ json: [] }))
    await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [] }))
    await page.goto('/games/101')
    const teams = page.getByRole('table', { name: 'Team box score' })
    await expect(teams.getByRole('row', { name: /NYK/ })).toContainText('100')
    const player = page.getByRole('table', { name: 'Player box score' })
      .getByRole('row', { name: /Synthetic Player/ })
    await expect(player).toContainText('24')
    await expect(player).toContainText('34.5')
    await expect(player).toContainText('40/80')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    expect(accessibility.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath(`box-score-${width}.png`), fullPage: true })
  })
}

test('box score failures can retry without hiding sequence evidence', async ({ page }) => {
  await page.route(api('/games/101'), (route) => route.fulfill({ json: games[100] }))
  let failing = true
  await page.route(api('/games/101/box-score'), (route) => failing
    ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: boxScore }))
  await page.route(api('/games/101/runs'), (route) => route.fulfill({ json: [] }))
  await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [] }))
  await page.goto('/games/101')
  const failure = page.getByRole('alert').filter({ hasText: 'Box score could not be loaded.' })
  await expect(failure).toBeVisible({ timeout: 15000 })
  await expect(page.getByRole('heading', { name: 'Scoring runs' })).toBeVisible()
  failing = false
  await failure.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('table', { name: 'Player box score' })).toContainText('Synthetic Player')
})

test('missing box score data is distinct from a failed request', async ({ page }) => {
  await page.route(api('/games/101'), (route) => route.fulfill({ json: games[100] }))
  await page.route(api('/games/101/box-score'), (route) => route.fulfill({ json: {
    game_id: 101, periods: [], teams: [], players: [],
  } }))
  await page.route(api('/games/101/runs'), (route) => route.fulfill({ json: [] }))
  await page.route(api('/games/101/play-by-play'), (route) => route.fulfill({ json: [] }))
  await page.goto('/games/101')
  await expect(page.getByText('No box score statistics are available for this game.')).toBeVisible()
  await expect(page.getByText('Box score could not be loaded.')).toHaveCount(0)
})
