import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from '@tanstack/react-router'
import { fetchGame, fetchPlayByPlay, fetchRuns } from '@/api'
import type { GameEvent, ScoringRun } from '@/types'
import { ArrowLeft, TrendingUp } from 'lucide-react'
import { formatDate, shortTeamLabel, teamLabel } from './game-formatting'
import { AppShell, SurfaceState } from './surface-layout'

function Scoreboard({ game }: { game: Awaited<ReturnType<typeof fetchGame>> }) {
  const homeWon = game.winner_team_id === game.home_team_id
  const margin = game.home_team_id === 'NYK' ? game.margin : -game.margin
  return (
    <section className='scoreboard surface-panel' aria-label='Final score'>
      <div className='scoreboard-meta'>
        <span>{game.status === 'final' ? 'Final' : game.status}</span>
        <time dateTime={game.game_date}>{formatDate(game.game_date)}</time>
      </div>
      <div className='scoreboard-teams'>
        <div className={!homeWon ? 'team-score is-winner' : 'team-score'}>
          <span>
            {shortTeamLabel(game.away_team_id, game.away_team?.abbreviation)}
          </span>
          <strong>{game.away_score}</strong>
          <small>{teamLabel(game.away_team_id, game.away_team?.name)}</small>
        </div>
        <div className='scoreboard-divider' aria-hidden='true'>
          @
        </div>
        <div className={homeWon ? 'team-score is-winner' : 'team-score'}>
          <span>
            {shortTeamLabel(game.home_team_id, game.home_team?.abbreviation)}
          </span>
          <strong>{game.home_score}</strong>
          <small>{teamLabel(game.home_team_id, game.home_team?.name)}</small>
        </div>
      </div>
      <div className='scoreboard-foot'>
        <span>
          {game.game_label ??
            game.series_name ??
            game.season_type.replace('_', ' ')}
        </span>
        <strong>
          {margin > 0 ? '+' : ''}
          {margin} Knicks margin
        </strong>
      </div>
    </section>
  )
}

function RunsPanel({ runs }: { runs: ScoringRun[] }) {
  return (
    <section
      className='surface-panel detail-panel'
      aria-labelledby='runs-title'
    >
      <div className='surface-panel-header'>
        <div>
          <p className='surface-kicker'>Momentum</p>
          <h2 id='runs-title'>Scoring runs</h2>
        </div>
        <TrendingUp
          aria-hidden='true'
          className='panel-icon panel-icon-orange'
        />
      </div>
      {runs.length === 0 ? (
        <p className='panel-empty'>
          No scoring runs were returned for this game.
        </p>
      ) : (
        <div className='run-list'>
          {runs.map((run) => (
            <div
              className={`run-row ${run.team_id === 'NYK' ? 'is-knicks' : ''}`}
              key={`${run.id}-${run.start_sequence ?? run.start_clock}-${run.team_id}`}
            >
              <span className='run-period'>
                Q{run.period}
                {run.end_period && run.end_period !== run.period
                  ? `–Q${run.end_period}`
                  : ''}
                <small>
                  {run.start_clock}–{run.end_clock}
                </small>
              </span>
              <strong>
                {run.points_for}—{run.points_against}
              </strong>
              <span>{run.summary}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function PlayByPlayPanel({
  events,
  homeTeamId,
}: {
  events: GameEvent[]
  homeTeamId: string
}) {
  return (
    <section className='surface-panel detail-panel' aria-labelledby='pbp-title'>
      <div className='surface-panel-header'>
        <div>
          <p className='surface-kicker'>Sequence log</p>
          <h2 id='pbp-title'>Play by play</h2>
        </div>
        <span className='panel-count'>{events.length} events</span>
      </div>
      {events.length === 0 ? (
        <p className='panel-empty'>
          No play-by-play events were returned for this game.
        </p>
      ) : (
        <div
          className='table-scroll'
          role='region'
          aria-label='Play-by-play events'
          tabIndex={0}
        >
          <table className='data-table'>
            <caption className='sr-only'>Play-by-play events</caption>
            <thead>
              <tr>
                <th scope='col'>Clock</th>
                <th scope='col'>Event</th>
                <th scope='col'>Score</th>
                <th scope='col'>Knicks margin</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const margin =
                  homeTeamId === 'NYK'
                    ? event.score_margin
                    : -event.score_margin
                return (
                  <tr
                    key={event.id}
                    id={`event-${event.sequence}`}
                    tabIndex={-1}
                  >
                    <td className='font-stats'>
                      Q{event.period} {event.clock}
                    </td>
                    <td>
                      <strong>{event.event_type}</strong>
                      <span>{event.description}</span>
                    </td>
                    <td className='font-stats'>
                      {event.away_score}—{event.home_score}
                    </td>
                    <td
                      className={`font-stats ${margin > 0 ? 'positive' : margin < 0 ? 'negative' : ''}`}
                    >
                      {margin > 0 ? '+' : ''}
                      {margin}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function GameDetailPage({ gameId }: { gameId: string }) {
  const id = Number(gameId)
  const location = useLocation()
  const game = useQuery({
    queryKey: ['game', id],
    queryFn: () => fetchGame(id),
    enabled: Number.isSafeInteger(id) && id > 0,
  })
  const events = useQuery({
    queryKey: ['game', id, 'play-by-play'],
    queryFn: () => fetchPlayByPlay(id),
    enabled:
      Number.isSafeInteger(id) &&
      id > 0 &&
      game.isSuccess &&
      game.data.data_status !== 'summary_only',
  })
  const runs = useQuery({
    queryKey: ['game', id, 'runs'],
    queryFn: () => fetchRuns(id),
    enabled:
      Number.isSafeInteger(id) &&
      id > 0 &&
      game.isSuccess &&
      game.data.data_status !== 'summary_only',
  })

  useEffect(() => {
    if (!events.isSuccess || !/^event-\d+$/.test(location.hash)) return
    const frame = requestAnimationFrame(() => {
      const row = document.getElementById(location.hash)
      row?.scrollIntoView({ block: 'center' })
      row?.focus({ preventScroll: true })
    })
    return () => cancelAnimationFrame(frame)
  }, [events.isSuccess, events.data, location.hash])

  if (game.isPending && Number.isSafeInteger(id) && id > 0)
    return (
      <AppShell
        eyebrow='Game detail'
        title='Loading game tape.'
        description='Pulling the scoreline and evidence for this night.'
      >
        <SurfaceState kind='loading' message='Loading game detail…' />
      </AppShell>
    )
  if (game.isError || !game.data)
    return (
      <AppShell
        eyebrow='Game detail'
        title='Game unavailable.'
        description='This game could not be found in the archive.'
      >
        <SurfaceState
          kind='error'
          message='The game detail could not be loaded.'
          onRetry={() => void game.refetch()}
        />
      </AppShell>
    )

  return (
    <AppShell
      eyebrow='Game detail'
      title={
        game.data.game_label ??
        `${shortTeamLabel(game.data.away_team_id)} at ${shortTeamLabel(game.data.home_team_id)}`
      }
      description='A compact box score, then the sequence evidence that explains how the night moved.'
      actions={
        <Link
          className='surface-back-link'
          to='/games'
          search={(previous) => previous}
        >
          <ArrowLeft aria-hidden='true' /> Back to games
        </Link>
      }
    >
      <Scoreboard game={game.data} />
      <div className='detail-grid'>
        {game.data.data_status === 'summary_only' ? (
          <SurfaceState
            kind='empty'
            message='Sequence evidence is unavailable for this game.'
          />
        ) : runs.isError ? (
          <SurfaceState
            kind='error'
            message='Runs could not be loaded.'
            onRetry={() => void runs.refetch()}
          />
        ) : runs.isPending ? (
          <SurfaceState kind='loading' message='Loading runs…' />
        ) : (
          <RunsPanel runs={runs.data} />
        )}
      </div>
      {events.isError ? (
        <SurfaceState
          kind='error'
          message='Play-by-play is unavailable for this game.'
          onRetry={() => void events.refetch()}
        />
      ) : null}
      {events.isPending && game.data.data_status !== 'summary_only' ? (
        <SurfaceState kind='loading' message='Loading the sequence log…' />
      ) : null}
      {events.isSuccess ? (
        <PlayByPlayPanel
          events={events.data}
          homeTeamId={game.data.home_team_id}
        />
      ) : null}
    </AppShell>
  )
}
