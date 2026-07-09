import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  fetchBadStretches,
  fetchGame,
  fetchPlayByPlay,
  fetchRuns,
  generatePostgameReport,
  triggerDetectRuns,
} from '../api'
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

export default function GameDetail() {
  const { id } = useParams<{ id: string }>()
  const gameId = Number(id)
  const qc = useQueryClient()

  const game = useQuery({
    queryKey: ['game', gameId],
    queryFn: () => fetchGame(gameId),
  })
  const pbp = useQuery({
    queryKey: ['pbp', gameId],
    queryFn: () => fetchPlayByPlay(gameId),
    enabled: game.data?.data_status !== 'summary_only',
  })
  const runs = useQuery({
    queryKey: ['runs', gameId],
    queryFn: () => fetchRuns(gameId),
    enabled: game.data?.data_status !== 'summary_only',
  })
  const stretches = useQuery({
    queryKey: ['bad-stretches', gameId],
    queryFn: () => fetchBadStretches(gameId),
    enabled: game.data?.data_status !== 'summary_only',
  })

  const detect = useMutation({
    mutationFn: () => triggerDetectRuns(gameId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs', gameId] })
      qc.invalidateQueries({ queryKey: ['bad-stretches', gameId] })
    },
  })

  const generateReport = useMutation({
    mutationFn: () => generatePostgameReport(gameId),
    onSuccess: (report) => {
      window.location.href = `/reports/${report.id}`
    },
  })

  if (game.isLoading) return <p>Loading…</p>
  if (game.error || !game.data) return <p className="text-red-400">Game not found</p>

  const g = game.data
  const isHome = g.home_team_id === 'NYK'
  const knicksScore = isHome ? g.home_score : g.away_score
  const oppScore = isHome ? g.away_score : g.home_score
  const knicksWon = g.winner_team_id === 'NYK'
  const hasEvents = g.data_status !== 'summary_only'
  const adminMode = window.localStorage.getItem('knicksiq_admin_mode') === 'true'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-knicks-silver">{g.game_date} · {g.season}</div>
          <h1 className="text-3xl font-bold mt-1">
            {g.away_team_id} @ {g.home_team_id}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <DataStatusBadge status={g.data_status} />
            {g.source_name && (
              <span className="text-xs text-knicks-silver">Source: {g.source_name}</span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-5xl font-bold ${knicksWon ? 'text-knicks-orange' : 'text-knicks-silver'}`}>
            {knicksScore} – {oppScore}
          </div>
          <div className="text-sm text-knicks-silver mt-1">
            {knicksWon ? 'WIN' : 'LOSS'} · margin {Math.abs(g.margin)}
          </div>
        </div>
      </div>

      {adminMode && (
        <div className="flex gap-3">
          <button
            onClick={() => detect.mutate()}
            disabled={detect.isPending || !hasEvents}
            className="px-4 py-2 bg-knicks-blue hover:bg-blue-700 disabled:opacity-50 rounded font-semibold"
          >
            {detect.isPending ? 'Detecting…' : 'Detect Runs'}
          </button>
          <button
            onClick={() => generateReport.mutate()}
            disabled={generateReport.isPending || !hasEvents}
            className="px-4 py-2 bg-knicks-orange hover:bg-orange-600 disabled:opacity-50 text-knicks-dark rounded font-semibold"
          >
            {generateReport.isPending ? 'Generating…' : 'Generate Postgame Autopsy'}
          </button>
        </div>
      )}

      {!hasEvents && (
        <section className="rounded border border-yellow-800 bg-yellow-950 p-4 text-sm text-yellow-100">
          This game has cached score and schedule metadata only. Event-level runs,
          stretches, and play-by-play will appear after play-by-play is cached.
        </section>
      )}

      {hasEvents && <section>
        <h2 className="text-2xl font-bold mb-3">Scoring Runs</h2>
        {runs.data && runs.data.length > 0 ? (
          <div className="space-y-2">
            {runs.data.map((r) => (
              <div
                key={r.id}
                className={`p-3 rounded border ${
                  r.team_id === 'NYK'
                    ? 'bg-blue-950 border-knicks-blue'
                    : 'bg-red-950 border-red-800'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-bold">{r.team_id}</span> {r.points_for}-{r.points_against} run
                    · Q{r.period} {r.start_clock} → {r.end_clock}
                  </div>
                  <div className="text-sm text-knicks-silver">Δ {r.score_delta > 0 ? '+' : ''}{r.score_delta}</div>
                </div>
                {r.summary && <div className="text-sm text-knicks-silver mt-1">{r.summary}</div>}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-knicks-silver text-sm">
            No scoring runs detected yet.
          </p>
        )}
      </section>}

      {hasEvents && <section>
        <h2 className="text-2xl font-bold mb-3">Bad Stretches</h2>
        {stretches.data && stretches.data.length > 0 ? (
          <div className="space-y-2">
            {stretches.data.map((s) => (
              <div
                key={s.id}
                className="p-3 rounded border bg-red-950 border-red-800"
              >
                <div className="font-bold">
                  Q{s.period} {s.start_clock} – {s.end_clock} (Δ {s.score_delta})
                </div>
                <div className="text-sm text-knicks-silver mt-1">{s.summary}</div>
                {s.likely_causes.length > 0 && (
                  <div className="text-xs text-knicks-silver mt-1">
                    Causes: {s.likely_causes.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-knicks-silver text-sm">No bad stretches detected.</p>
        )}
      </section>}

      {hasEvents && <section>
        <h2 className="text-2xl font-bold mb-3">Play-by-Play</h2>
        <div className="bg-gray-900 border border-gray-800 rounded max-h-96 overflow-y-auto">
          {pbp.data?.map((e) => (
            <div
              key={e.id}
              className="px-4 py-2 text-sm border-b border-gray-800 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <span className="text-knicks-silver text-xs w-12">Q{e.period}</span>
                <span className="text-knicks-silver text-xs w-12">{e.clock}</span>
                <span className="text-knicks-silver text-xs w-8">{e.team_id ?? '-'}</span>
                <span>{e.description}</span>
              </div>
              <span className="text-xs text-knicks-silver">
                {e.away_score}-{e.home_score}
              </span>
            </div>
          ))}
        </div>
      </section>}

      <div>
        <Link to="/games" className="text-knicks-orange hover:underline text-sm">
          ← Back to games
        </Link>
      </div>
    </div>
  )
}
