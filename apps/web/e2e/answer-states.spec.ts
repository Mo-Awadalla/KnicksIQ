import { expect } from 'playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { api, test } from './parity-fixtures'

const disclosure =
  'KnicksIQ is an unofficial fan project and is not affiliated with, endorsed by, or sponsored by the New York Knicks or the NBA.'

function committedAnswer(answer: string, extra: Record<string, unknown> = {}) {
  return {
    answer,
    follow_up_questions: [],
    warnings: [],
    citations: [],
    refused: false,
    degraded: false,
    data_version: 'parity.1',
    request_id: 'answer-states-fixture',
    session_token: 'a'.repeat(64),
    session_expires_at: '2099-01-01T00:00:00Z',
    revision: 1,
    state_committed: true,
    llm_validated: true,
    analytics: null,
    ...extra,
  }
}

for (const { surface, width } of [
  { surface: '/', width: 390 },
  { surface: '/analyst', width: 1440 },
]) {
  test(`slow answer can be stopped with keyboard focus restored on ${surface}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const { promise: held, resolve: releaseRequest } =
      Promise.withResolvers<void>()
    const { promise: started, resolve: requestStarted } =
      Promise.withResolvers<void>()
    await page.route(api('/analysis/query'), async (route) => {
      requestStarted()
      await held
      try {
        await route.fulfill({
          json: committedAnswer('A delayed archive answer.'),
        })
      } catch {
        // The cancelled browser request no longer accepts a response.
      }
    })
    await page.goto(surface)
    const question = page.getByRole('textbox', {
      name: surface === '/' ? 'Ask the archive' : 'Ask a season question',
    })
    await expect(question).toBeEnabled()
    await question.fill('How did the Knicks perform against Boston?')
    await page.evaluate(() => {
      const target = window as Window & { __layoutShifts?: number[] }
      target.__layoutShifts = []
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const shift = entry as PerformanceEntry & {
            value: number
            hadRecentInput: boolean
          }
          if (!shift.hadRecentInput) target.__layoutShifts?.push(shift.value)
        }
      }).observe({ type: 'layout-shift', buffered: false })
    })
    await question.press('Enter')
    await started
    await expect(
      page.getByRole('status').filter({ hasText: 'Checking the season archive' })
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Stop waiting' })).toBeVisible()
    await page.waitForTimeout(5_500)
    await expect(page.getByRole('status')).toContainText(
      'This is taking a little longer'
    )
    const layoutShift = await page.evaluate(() => {
      const target = window as Window & { __layoutShifts?: number[] }
      return target.__layoutShifts?.reduce((sum, value) => sum + value, 0) ?? 0
    })
    expect(layoutShift).toBeLessThan(0.05)
    await page.getByRole('button', { name: 'Stop waiting' }).click()
    await expect(question).toHaveValue(
      'How did the Knicks perform against Boston?'
    )
    await expect(question).toBeFocused()
    await expect(page.getByRole('status')).toContainText(
      'Question stopped. Your question is ready to try again.'
    )
    await expect(page.getByRole('button', { name: 'Retry question' })).toBeVisible()
    releaseRequest()
  })
}

for (const width of [390, 1440]) {
  test(`analyst remains accessible and discloses its affiliation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/analyst')
    await expect(
      page.getByRole('textbox', { name: 'Ask a season question' })
    ).toBeEnabled()
    await expect(page.getByText(disclosure)).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
    ).toBe(true)
    const audit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze()
    expect(
      audit.violations.filter((violation) =>
        ['serious', 'critical'].includes(violation.impact ?? '')
      )
    ).toEqual([])
    await page.goto('/')
    await expect(page.getByText(disclosure)).toBeVisible()
  })
}

test('declines explain archive coverage and offer supported alternatives', async ({
  page,
}) => {
  const questions: string[] = []
  await page.route(api('/analysis/query'), (route) => {
    const body = route.request().postDataJSON() as { question: string }
    questions.push(body.question)
    return route.fulfill({
      json:
        questions.length === 1
          ? committedAnswer(
              "The archive has game results to review. I don't have live injury or current-status updates.",
              {
                refused: false,
                llm_validated: false,
                warnings: [
                  'Question asks outside the available Knicks season data or live/current coverage.',
                ],
              }
            )
          : committedAnswer('A supported archive answer.'),
    })
  })
  await page.goto('/analyst')
  const question = page.getByRole('textbox', { name: 'Ask a season question' })
  await question.fill('What is the Knicks injury report tonight?')
  await question.press('Enter')
  await expect(
    page.getByRole('heading', { name: "The archive can't answer that one" })
  ).toBeVisible()
  await expect(
    page.getByText("I don't have live injury or current-status updates.", {
      exact: true,
    })
  ).toBeVisible()
  await expect(
    page.getByText('The archive has game results to review.')
  ).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'What this archive covers' })).toBeVisible()
  await expect(page.getByText(/live scores, injury updates, trades, or future events/)).toBeVisible()
  const alternatives = page.getByRole('group', { name: 'Supported questions' })
  await expect(alternatives.getByRole('button')).toHaveCount(3)
  await alternatives
    .getByRole('button', { name: 'How did the Knicks perform against Boston?' })
    .click()
  await expect(page.getByText('A supported archive answer.')).toBeVisible()
  expect(questions).toEqual([
    'What is the Knicks injury report tonight?',
    'How did the Knicks perform against Boston?',
  ])
})

test('fallback answer shows plain-language limits and readable mobile citations', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route(api('/analysis/query'), (route) =>
    route.fulfill({
      json: committedAnswer('The Knicks won 10 of the 11 available games.', {
        degraded: true,
        llm_validated: false,
        warnings: ['Proposed wording did not pass evidence review.'],
        analytics: {
          status: 'limited',
          resolved_question: 'How many games did the Knicks win?',
          clarification: null,
          results: [],
          coverage: {
            expected_game_count: 11,
            covered_game_count: 10,
            missing_game_ids: [11],
            completeness: 10 / 11,
            data_through: '2026-03-30',
          },
        },
        citations: [
          {
            type: 'verified_claim',
            title: 'Knicks vs Boston · 2026-03-30 regular-season game at Madison Square Garden',
            claim: 'The Knicks scored 120 points in the game.',
            game_id: 1,
            source_name: 'NBA.com box score',
            source_url: 'https://www.nba.com/game/0022500001/box-score',
            metadata: {},
          },
        ],
      }),
    })
  )
  await page.goto('/analyst')
  const question = page.getByRole('textbox', { name: 'Ask a season question' })
  await question.fill('How many games did the Knicks win?')
  await question.press('Enter')
  await expect(page.getByText('The Knicks won 10 of the 11 available games.')).toBeVisible()
  await expect(page.getByText(/This answer is built from archived game facts/)).toBeVisible()
  await expect(
    page.getByText(/Available records cover 10 of 11 games through 2026-03-30/)
  ).toBeVisible()
  const thread = page.locator('.analyst-thread')
  await expect(thread).not.toContainText(/Redis|RAG|deterministic|provider|evidence review/i)
  await page.getByText('Sources (1)', { exact: true }).click()
  await expect(
    page.getByText('The Knicks scored 120 points in the game.')
  ).toBeVisible()
  const claimFont = await page
    .locator('.archive-receipt .archive-ink-soft-text')
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize))
  expect(claimFont).toBeGreaterThanOrEqual(14)
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  ).toBe(true)
  const audit = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze()
  expect(
    audit.violations.filter((violation) =>
      ['serious', 'critical'].includes(violation.impact ?? '')
    )
  ).toEqual([])
})

test('expired session keeps the question and retries with a fresh conversation', async ({
  page,
}) => {
  const requests: Array<Record<string, unknown>> = []
  await page.route(api('/analysis/query'), (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    requests.push(body)
    if (requests.length === 2) {
      return route.fulfill({
        status: 409,
        json: { detail: { reason: 'session_expired' } },
      })
    }
    const answer =
      requests.length === 1 ? 'First answer.' : 'Fresh answer after expiry.'
    return route.fulfill({
      json: committedAnswer(answer, {
        revision: 1,
        session_token: 'b'.repeat(64),
      }),
    })
  })
  await page.goto('/analyst')
  const question = page.getByRole('textbox', { name: 'Ask a season question' })
  await question.fill('First question')
  await question.press('Enter')
  await expect(page.getByText('First answer.')).toBeVisible()
  await question.fill('Second question')
  await question.press('Enter')
  await expect(
    page.getByText('Session expired. Previous messages remain readable.')
  ).toBeVisible()
  await expect(question).toHaveValue('Second question')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Fresh answer after expiry.')).toBeVisible()
  expect(requests).toHaveLength(3)
  expect(requests[2]?.expected_revision).toBe(0)
  expect(requests[2]?.session_token).toBeUndefined()
  expect(requests[2]?.context).toEqual([])
  expect(requests[2]?.turn_id).toBe(requests[1]?.turn_id)
})
