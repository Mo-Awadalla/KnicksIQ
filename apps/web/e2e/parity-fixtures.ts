import { test as base } from 'playwright/test'

export const api = (path: string) =>
  (process.env.PLAYWRIGHT_API_URL ||
    (process.env.PLAYWRIGHT_BASE_URL ? 'https://api.knicksiq.win' : '**/api')) +
  path

export const games = Array.from({ length: 101 }, (_, index) => ({
  id: index + 1,
  nba_game_id: `nba-${index + 1}`,
  season: '2025-26',
  game_date: '2026-01-01',
  home_team_id: 'NYK',
  away_team_id: 'BOS',
  home_score: 100,
  away_score: 90,
  winner_team_id: 'NYK',
  status: 'final',
  season_type: 'regular',
  data_status: 'analysis_ready',
  margin: 10,
}))

export const test = base.extend({
  page: async ({ page }, run) => {
    // Remote artifact checks use fixtures too: never spend provider budget.
    if (process.env.PLAYWRIGHT_BASE_URL || process.env.PLAYWRIGHT_API_URL) {
      await page.route('https://api.knicksiq.win/**', (route) => route.abort())
    }
    await page.route(api('/archive/status*'), (route) =>
      route.fulfill({
        json: {
          season: '2025-26',
          data_version: 'parity.1',
          games: 101,
          matching_games: 101,
          regular_season_games: 101,
          postseason_games: 0,
          reports: 101,
          capabilities: [],
        },
      })
    )
    await page.route(api('/games?*'), (route) => {
      const url = new URL(route.request().url())
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 50)
      return route.fulfill({ json: games.slice(offset, offset + limit) })
    })
    await page.route(api('/reports?*'), (route) => {
      const url = new URL(route.request().url())
      const offset = Number(url.searchParams.get('offset') || 0)
      return route.fulfill({
        json: games.slice(offset, offset + 50).map((game) => ({
          id: game.id,
          game_id: game.id,
          title: `Report ${game.id}`,
          summary: 'Verified game.',
          created_at: '2026-01-01',
        })),
      })
    })
    await run(page)
  },
})
