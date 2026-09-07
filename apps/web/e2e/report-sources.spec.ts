import { readFileSync } from 'node:fs'
import { expect, test } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'

// Corrected proposal serialized by the real API using an in-memory session.
// These fixtures do not approve or publish any candidate report.
const fixture = JSON.parse(readFileSync(new URL('./fixtures/corrected-report.json', import.meta.url), 'utf8'))

test('corrected report sources expose exact intervals and use internal game IDs', async ({ page }) => {
  expect(fixture.candidate_reviewed).toBe(false)
  await page.route(`**/api/reports/${fixture.report.id}`, (route) => route.fulfill({ json: fixture.report }))
  await page.route(`**/api/games/${fixture.game.id}`, (route) => route.fulfill({ json: fixture.game }))
  await page.route(`**/api/games/${fixture.game.id}/runs`, (route) => route.fulfill({ json: [] }))
  await page.route(`**/api/games/${fixture.game.id}/play-by-play`, (route) => route.fulfill({ json: fixture.events }))
  await page.goto(`/reports/${fixture.report.id}`)
  await expect(page.locator('.report-source')).toHaveCount(7)
  await expect(page.locator('.report-sources')).toContainText('Events 365–385, inclusive')
  await expect(page.getByRole('link', { name: 'Donovan Mitchell box score source' })).toHaveAttribute('href', 'https://www.nba.com/game/0022500003/box-score')
  await expect(page.getByRole('link', { name: 'Selected scoring interval source', exact: false })).toHaveAttribute('href', /playbyplayv3\?GameID=0022500003/)
  await expect(page.getByText('No adjustments are included in this report.')).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(accessibility.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''))).toEqual([])
  await page.getByRole('link', { name: 'View selected scoring interval in game', exact: true }).click()
  await expect(page).toHaveURL(/\/games\/10001#event-365$/)
  await expect(page.locator('#event-365')).toBeFocused()
  await expect(page.locator('#event-365')).toContainText(fixture.events.find((event: { sequence: number }) => event.sequence === 365).description)
})

test('legacy source notes and absent optional source types do not break a report', async ({ page }) => {
  await page.route(`**/api/reports/${fixture.report.id}`, (route) => route.fulfill({ json: {
    ...fixture.report, sources: ['Legacy source note', { url: 'javascript:alert(1)' }, null],
  } }))
  await page.goto(`/reports/${fixture.report.id}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(fixture.report.title)
  await expect(page.getByText('Legacy source note', { exact: true })).toBeVisible()
  await expect(page.locator('.report-sources a')).toHaveCount(0)
})
