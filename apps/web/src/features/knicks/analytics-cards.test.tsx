import type { AnalyticsPayload } from '@/types'
import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { AnalyticsCards } from './analytics-cards'

const analytics: AnalyticsPayload = {
  status: 'limited',
  resolved_question: 'What did Brunson average?',
  plan: null,
  clarification: null,
  coverage: {
    expected_game_count: 3,
    covered_game_count: 2,
    missing_game_ids: [3],
    completeness: 2 / 3,
    data_through: '2026-04-12',
  },
  results: [
    {
      id: 'result-1',
      type: 'aggregate',
      title: 'Jalen Brunson — regular season',
      raw_values: { points: 25 },
      display_values: { points: '25.0' },
      sample_size: 2,
      timeframe: { kind: 'regular_season', label: '2025-26 regular season' },
      warnings: ['Small sample.'],
      source_game_ids: [1, 2],
    },
  ],
}

describe('AnalyticsCards', () => {
  it('shows typed values, coverage, warnings, and expandable receipts', async () => {
    const { getByText } = await render(
      <AnalyticsCards analytics={analytics} games={[]} />
    )
    await expect.element(getByText('25.0')).toBeInTheDocument()
    await expect.element(getByText('Small sample.')).toBeInTheDocument()
    await expect
      .element(getByText(/Partial coverage: 2 of 3/))
      .toBeInTheDocument()
    const receipts = getByText('2 supporting game receipts')
    await userEvent.click(receipts)
    await expect
      .element(getByText(/All source IDs are retained/))
      .toBeInTheDocument()
  })

  it('labels totals separately from per-appearance values and archive coverage', async () => {
    const both: AnalyticsPayload = {
      ...analytics,
      status: 'complete',
      coverage: {
        expected_game_count: 82,
        covered_game_count: 82,
        missing_game_ids: [],
        completeness: 1,
        data_through: '2026-04-12',
      },
      results: [
        {
          ...analytics.results[0],
          aggregation_mode: 'both',
          per_appearance_values: { points: 25 },
          per_appearance_display_values: { points: '25.0' },
          totals: { points: 1850 },
          total_display_values: { points: '1850.0' },
        },
      ],
    }
    const { getByText } = await render(
      <AnalyticsCards analytics={both} games={[]} />
    )
    await expect.element(getByText('points per appearance')).toBeInTheDocument()
    await expect.element(getByText('points total')).toBeInTheDocument()
    await expect
      .element(getByText(/82 of 82 archive games covered/))
      .toBeInTheDocument()
  })

  it('distinguishes appearances from requested team games for availability', async () => {
    const availability: AnalyticsPayload = {
      ...analytics,
      results: [
        {
          ...analytics.results[0],
          availability: true,
          appearances: 74,
          requested_team_games: 82,
        },
      ],
    }
    const { getByText } = await render(
      <AnalyticsCards analytics={availability} games={[]} />
    )
    await expect.element(getByText('Player appearances')).toBeInTheDocument()
    await expect
      .element(getByText('Requested Knicks games'))
      .toBeInTheDocument()
    await expect.element(getByText('74')).toBeInTheDocument()
    await expect.element(getByText('82')).toBeInTheDocument()
  })
})
