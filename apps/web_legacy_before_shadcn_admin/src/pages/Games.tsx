import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchGames } from '../api'
import type { GameDataStatus } from '../types'

function DataStatusBadge({ status }: { status: GameDataStatus }) {
  const label =
    status === 'analysis_ready'
      ? 'Analysis ready'
      : status === 'events_ready'
        ? 'Play-by-play ready'
        : 'Summary only'
  const classes =
    status === 'summary_only'
      ? 'border-yellow-700 bg-yellow-950 text-yellow-200'
      : 'border-emerald-700 bg-emerald-950 text-emerald-200'
  return <span className={`rounded border px-2 py-0.5 text-xs ${classes}`}>{label}</span>
}

export default function Games() {
  const [seasonType, setSeasonType] = useState('')
  const [dataStatus, setDataStatus] = useState('')
  const { data, isLoading, error } = useQuery({
    queryKey: ['games', seasonType, dataStatus],
    queryFn: () =>
      fetchGames({
        teamId: 'NYK',
        season: '2025-26',
        seasonType: seasonType || undefined,
        dataStatus: dataStatus || undefined,
      }),
  })

  if (isLoading) return <p className="text-center py-12">Loading games…</p>
  if (error) return <p className="text-red-400">Failed to load games.</p>

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold">Knicks 2025-26 Archive</h1>
          <p className="mt-1 text-sm text-knicks-silver">
            Regular season and playoff games appear as soon as summaries are cached.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <select
            value={seasonType}
            onChange={(e) => setSeasonType(e.target.value)}
            className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm"
          >
            <option value="">All season types</option>
            <option value="regular">Regular season</option>
            <option value="play_in">Play-in</option>
            <option value="playoffs">Playoffs</option>
          </select>
          <select
            value={dataStatus}
            onChange={(e) => setDataStatus(e.target.value)}
            className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm"
          >
            <option value="">All data statuses</option>
            <option value="summary_only">Summary only</option>
            <option value="events_ready">Play-by-play ready</option>
            <option value="analysis_ready">Analysis ready</option>
          </select>
        </div>
      </div>
      <div className="space-y-3">
        {data?.map((g) => (
          <Link
            key={g.id}
            to={`/games/${g.id}`}
            className="block p-4 bg-gray-900 border border-gray-800 rounded-lg hover:border-knicks-orange transition"
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-knicks-silver mb-1">
                  {g.game_date} · {g.season} · {g.season_type.replace('_', '-')}
                </div>
                <div className="text-lg font-semibold">
                  {g.away_team_id} @ {g.home_team_id}
                </div>
                <div className="mt-2">
                  <DataStatusBadge status={g.data_status} />
                </div>
              </div>
              <div className="text-right">
                <div
                  className={`text-2xl font-bold ${
                    g.winner_team_id === 'NYK' ? 'text-knicks-orange' : 'text-knicks-silver'
                  }`}
                >
                  {g.away_score} – {g.home_score}
                </div>
                <div className="text-xs text-knicks-silver">
                  {g.winner_team_id === 'NYK' ? 'W' : 'L'} · {g.status}
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
