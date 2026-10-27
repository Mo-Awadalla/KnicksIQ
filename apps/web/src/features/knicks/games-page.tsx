import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { fetchArchiveStatus, fetchGames } from '@/api'
import type { GameSummary } from '@/types'
import { CalendarDays, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Pagination } from './archive-pagination'
import {
  ARCHIVE_PAGE_SIZE,
  archivePagination,
  useArchivePosition,
} from './archive-position'
import {
  formatDate,
  resultForGame,
  shortTeamLabel,
  teamLabel,
} from './game-formatting'
import { AppShell, MetricStrip, SurfaceState } from './surface-layout'

const SEASON = '2025-26'

function GameRow({ game }: { game: GameSummary }) {
  const result = resultForGame(game)
  const isWin = result === 'W'
  const margin = game.home_team_id === 'NYK' ? game.margin : -game.margin
  return (
    <Link
      className='game-row'
      to='/games/$gameId'
      params={{ gameId: String(game.id) }}
      search={(previous) => previous}
    >
      <span
        className={`game-result game-result-${isWin ? 'win' : result === 'L' ? 'loss' : 'neutral'}`}
      >
        {result}
      </span>
      <span className='game-date'>
        <time dateTime={game.game_date}>{formatDate(game.game_date)}</time>
        <small>{game.season_type.replace('_', ' ')}</small>
      </span>
      <span className='game-matchup'>
        <strong>
          {game.game_label ??
            `${shortTeamLabel(game.away_team_id)} at ${shortTeamLabel(game.home_team_id)}`}
        </strong>
        <small>
          {teamLabel(game.away_team_id)} at {teamLabel(game.home_team_id)}
        </small>
      </span>
      <span className='game-score font-stats'>
        {game.away_score}—{game.home_score}
      </span>
      <span
        className={`game-margin ${margin >= 0 ? 'positive' : 'negative'}`}
        aria-label={`Knicks margin: ${margin > 0 ? '+' : ''}${margin}`}
      >
        {margin > 0 ? '+' : ''}
        {margin}
      </span>
      <ChevronRight className='game-row-arrow' aria-hidden='true' />
    </Link>
  )
}

export function GamesPage() {
  const { page, params, set } = useArchivePosition()
  const seasonType = params.get('seasonType') || ''
  const dataStatus = params.get('dataStatus') || ''
  const status = useQuery({
    queryKey: ['archive-status', seasonType, dataStatus],
    queryFn: () =>
      fetchArchiveStatus({
        season_type: seasonType || undefined,
        data_status: dataStatus || undefined,
      }),
  })
  const games = useQuery({
    queryKey: ['games', SEASON, seasonType, dataStatus, page],
    queryFn: () =>
      fetchGames({
        ...archivePagination(page),
        teamId: 'NYK',
        season: SEASON,
        seasonType: seasonType || undefined,
        dataStatus: dataStatus || undefined,
      }),
  })
  const finalGames = games.data?.filter((game) => game.status === 'final') ?? []
  const wins = finalGames.filter((game) => resultForGame(game) === 'W').length
  const losses = finalGames.filter((game) => resultForGame(game) === 'L').length

  return (
    <AppShell
      eyebrow='Game index'
      title='Every night, logged.'
      description='A filterable ledger of the Knicks season. Open a game to move from the final score into the swing-by-swing evidence.'
      actions={
        <Badge variant='outline'>
          <CalendarDays aria-hidden='true' /> {SEASON}
        </Badge>
      }
    >
      <p>
        {status.data
          ? `${status.data.games} archived games`
          : 'Archive total unavailable'}
      </p>
      <MetricStrip
        items={[
          {
            label: 'Games returned',
            value: games.data ? String(games.data.length) : '—',
            tone: 'blue',
          },
          {
            label: 'Record on this page',
            value: games.data ? `${wins}–${losses}` : '—',
            tone: 'orange',
          },
          {
            label: 'Event-ready',
            value: games.data
              ? String(
                  games.data.filter(
                    (game) => game.data_status !== 'summary_only'
                  ).length
                )
              : '—',
          },
        ]}
      />
      <section
        className='surface-panel game-index-panel'
        aria-labelledby='game-index-title'
      >
        <div className='surface-panel-header'>
          <div>
            <p className='surface-kicker'>The ledger</p>
            <h2 id='game-index-title'>Season games</h2>
          </div>
          <div className='filter-row' aria-label='Game filters'>
            <label>
              Type
              <select
                value={seasonType}
                onChange={(event) =>
                  set({ seasonType: event.target.value, page: 1 })
                }
              >
                <option value=''>All games</option>
                <option value='regular'>Regular season</option>
                <option value='play_in'>Play-in</option>
                <option value='playoffs'>Playoffs</option>
              </select>
            </label>
            <label>
              Data
              <select
                value={dataStatus}
                onChange={(event) =>
                  set({ dataStatus: event.target.value, page: 1 })
                }
              >
                <option value=''>Any coverage</option>
                <option value='summary_only'>Summary only</option>
                <option value='events_ready'>Events ready</option>
                <option value='analysis_ready'>Analysis ready</option>
              </select>
            </label>
          </div>
        </div>
        {games.isPending ? (
          <SurfaceState kind='loading' message='Loading the season ledger…' />
        ) : null}
        {games.isError ? (
          <SurfaceState
            kind='error'
            message='The game ledger could not be loaded.'
            onRetry={() => void games.refetch()}
          />
        ) : null}
        {games.isSuccess && games.data.length === 0 ? (
          <SurfaceState
            kind='empty'
            message='No games match those filters. Try a wider season view.'
          />
        ) : null}
        <Pagination
          page={page}
          total={
            status.data?.matching_games ??
            status.data?.games ??
            page * ARCHIVE_PAGE_SIZE
          }
          onPage={(value) => set({ page: value })}
        />
        {games.isSuccess && games.data.length > 0 ? (
          <div className='game-list'>
            {games.data.map((game) => (
              <GameRow key={game.id} game={game} />
            ))}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
