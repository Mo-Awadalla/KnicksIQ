import type { AnalyticsPayload, AnalyticsResult, GameSummary } from '@/types'
import { AlertTriangle, ChevronDown } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function statLabel(value: string) {
  return value.replace(/_/g, ' ')
}

function Values({
  values,
  qualifier,
}: {
  values: Record<string, string>
  qualifier?: string
}) {
  return (
    <div className='grid gap-2 sm:grid-cols-3'>
      {Object.entries(values).map(([key, value]) => (
        <div key={key} className='rounded-md bg-[#f4f7fb] p-3'>
          <p className='text-xs text-muted-foreground capitalize'>
            {statLabel(key)} {qualifier}
          </p>
          <p className='mt-1 text-xl font-semibold text-[#0d2238]'>{value}</p>
        </div>
      ))}
    </div>
  )
}

function ResultBody({ result }: { result: AnalyticsResult }) {
  if (result.availability) {
    return (
      <div className='grid gap-3 sm:grid-cols-2'>
        <div className='rounded-md bg-[#f4f7fb] p-3'>
          <p className='text-xs text-muted-foreground'>Player appearances</p>
          <p className='mt-1 text-xl font-semibold text-[#0d2238]'>
            {result.appearances}
          </p>
        </div>
        <div className='rounded-md bg-[#f4f7fb] p-3'>
          <p className='text-xs text-muted-foreground'>
            Requested Knicks games
          </p>
          <p className='mt-1 text-xl font-semibold text-[#0d2238]'>
            {result.requested_team_games}
          </p>
        </div>
      </div>
    )
  }

  if (result.type === 'trend' && result.series) {
    return (
      <div className='h-64' aria-label={`${result.title} chart`}>
        <ResponsiveContainer width='100%' height='100%'>
          <LineChart data={result.series}>
            <CartesianGrid strokeDasharray='3 3' />
            <XAxis dataKey='date' tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            <Line dataKey='value' stroke='#BEC0C2' dot={false} />
            <Line
              dataKey='rolling_mean'
              name='5-game rolling mean'
              stroke='#006BB6'
              strokeWidth={3}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (result.groups) {
    const stats = Object.keys(result.groups[0]?.raw_values ?? {})
    const chart = result.groups.map((group) => ({
      name: group.label,
      ...group.raw_values,
    }))
    return (
      <div className='space-y-4'>
        <div className='grid gap-3 sm:grid-cols-2'>
          {result.groups.map((group) => (
            <div key={group.key} className='rounded-md border p-3'>
              <p className='mb-2 font-semibold'>{group.label}</p>
              <Values values={group.display_values} />
              <p className='mt-2 text-xs text-muted-foreground'>
                {group.sample_size} appearances
              </p>
            </div>
          ))}
        </div>
        {stats.length > 0 ? (
          <div className='h-52' aria-label={`${result.title} comparison chart`}>
            <ResponsiveContainer width='100%' height='100%'>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray='3 3' />
                <XAxis dataKey='name' />
                <YAxis />
                <Tooltip />
                {stats.slice(0, 3).map((stat, index) => (
                  <Bar
                    key={stat}
                    dataKey={stat}
                    fill={['#006BB6', '#F58426', '#BEC0C2'][index]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </div>
    )
  }

  if (result.facts) {
    return (
      <div className='space-y-3'>
        {result.facts.map((fact) => (
          <div key={fact.fingerprint} className='rounded-md border p-4'>
            <p className='leading-6'>{fact.statement}</p>
            <p className='mt-2 text-xs text-muted-foreground'>
              {fact.sample_size} appearances · discovery score{' '}
              {fact.score.toFixed(2)}
            </p>
          </div>
        ))}
      </div>
    )
  }

  if (result.entries) {
    return (
      <div className='overflow-x-auto'>
        <table className='w-full text-left text-sm'>
          <tbody>
            {result.entries.map((entry, index) => {
              const values = (entry.display_values ?? {}) as Record<
                string,
                string
              >
              return (
                <tr key={String(entry.game_id ?? entry.player_id ?? index)}>
                  <td className='border-b py-3 pr-3 font-medium'>
                    {String(
                      entry.player_name ??
                        entry.date ??
                        entry.opponent ??
                        `Result ${index + 1}`
                    )}
                  </td>
                  <td className='border-b py-3 text-right'>
                    {Object.values(values).join(' · ') ||
                      String(entry.display_value ?? '')}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  if (Object.keys(result.display_values).length > 0) {
    if (
      result.aggregation_mode === 'both' &&
      result.per_appearance_display_values &&
      result.total_display_values
    ) {
      return (
        <div className='space-y-4'>
          <Values
            values={result.per_appearance_display_values}
            qualifier='per appearance'
          />
          <Values values={result.total_display_values} qualifier='total' />
        </div>
      )
    }
    return (
      <Values
        values={result.display_values}
        qualifier={
          result.aggregation_mode === 'total' ? 'total' : 'per appearance'
        }
      />
    )
  }

  return (
    <p className='text-sm text-muted-foreground'>
      The resolved result is available in the summary above.
    </p>
  )
}

function Receipts({
  result,
  games,
}: {
  result: AnalyticsResult
  games: GameSummary[]
}) {
  const sourceGames = result.source_game_ids
    .map((id) => games.find((game) => game.id === id))
    .filter((game): game is GameSummary => Boolean(game))
  return (
    <details className='group rounded-md border border-[#BEC0C2]/70'>
      <summary className='flex cursor-pointer list-none items-center justify-between p-3 text-sm font-medium'>
        {result.source_game_ids.length} supporting game receipt
        {result.source_game_ids.length === 1 ? '' : 's'}
        <ChevronDown className='size-4 transition group-open:rotate-180' />
      </summary>
      <div className='grid gap-2 border-t p-3 sm:grid-cols-2'>
        {sourceGames.map((game) => (
          <div key={game.id} className='rounded bg-[#f4f7fb] p-2 text-xs'>
            {game.game_date} · {game.away_team_id} {game.away_score} @{' '}
            {game.home_team_id} {game.home_score}
          </div>
        ))}
        {sourceGames.length < result.source_game_ids.length ? (
          <p className='text-xs text-muted-foreground'>
            All source IDs are retained in the result; some games are outside
            the currently loaded receipt list.
          </p>
        ) : null}
      </div>
    </details>
  )
}

export function AnalyticsCards({
  analytics,
  games,
}: {
  analytics: AnalyticsPayload
  games: GameSummary[]
}) {
  return (
    <div className='space-y-4'>
      {analytics.results.map((result) => (
        <Card key={result.id} className='border-[#006BB6]/25 bg-white'>
          <CardHeader className='space-y-3'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <CardTitle className='text-lg'>{result.title}</CardTitle>
              <Badge variant='secondary'>{statLabel(result.type)}</Badge>
            </div>
            <div className='flex flex-wrap gap-2 text-xs text-muted-foreground'>
              <span>{result.sample_size} appearances</span>
              <span>·</span>
              <span>{result.timeframe.label}</span>
              {analytics.coverage?.data_through ? (
                <>
                  <span>·</span>
                  <span>through {analytics.coverage.data_through}</span>
                </>
              ) : null}
              {analytics.coverage ? (
                <>
                  <span>·</span>
                  <span>
                    {analytics.coverage.covered_game_count} of{' '}
                    {analytics.coverage.expected_game_count} archive games
                    covered
                  </span>
                </>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className='space-y-4'>
            {result.warnings.map((warning) => (
              <p
                key={warning}
                className='flex gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-950'
              >
                <AlertTriangle className='mt-0.5 size-4 shrink-0' />
                {warning}
              </p>
            ))}
            <ResultBody result={result} />
            <Receipts result={result} games={games} />
          </CardContent>
        </Card>
      ))}
      {analytics.coverage && analytics.coverage.completeness < 1 ? (
        <p className='rounded-md bg-amber-50 p-3 text-sm text-amber-950'>
          Partial coverage: {analytics.coverage.covered_game_count} of{' '}
          {analytics.coverage.expected_game_count} requested games are covered.
        </p>
      ) : null}
    </div>
  )
}
