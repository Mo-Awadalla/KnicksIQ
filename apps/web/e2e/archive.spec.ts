import { expect, test } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('public archive loads and exposes policy links', async ({ page }) => {
  await page.route('**/api/archive/status', (route) =>
    route.fulfill({
      json: {
        season: '2025-26', data_version: 'test.1', games: 1,
        regular_season_games: 1, postseason_games: 0, reports: 1,
        activated_at: '2026-07-01T00:00:00Z', capabilities: ['records'],
      },
    })
  )
  await page.route('**/api/games**', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('2025-26')
  await expect(page.getByRole('link', { name: 'Privacy' })).toBeVisible()
  await expect(page.getByText('Data test.1')).toBeVisible()
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    accessibility.violations.filter((violation) =>
      ['serious', 'critical'].includes(violation.impact ?? '')
    )
  ).toEqual([])
})

test('feedback form posts to the configured Formspree endpoint', async ({ page }) => {
  await page.goto('/feedback.html')

  const form = page.getByRole('button', { name: 'Send feedback' }).locator('..')
  await expect(form).toHaveAttribute('method', 'post')
  await expect(form).toHaveAttribute('action', 'https://formspree.io/f/xaqrndvp')
  await expect(page.getByRole('textbox', { name: 'Message' })).toHaveAttribute('required', '')
  await expect(page.getByRole('combobox', { name: 'Category' })).toHaveAttribute('required', '')
})
