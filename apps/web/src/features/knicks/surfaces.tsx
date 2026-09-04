import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import {
  fetchArchiveStatus,
  fetchGame,
  fetchGames,
  fetchPlayByPlay,
  fetchReport,
  fetchReports,
  fetchRuns,
} from '@/api'
import type { GameEvent, GameSummary, Report, ScoringRun } from '@/types'
import {
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  ChevronRight,
  CircleAlert,
  FileText,
  Loader2,
  MessageSquareText,
  RefreshCw,
  Search,
  TrendingUp,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { AnswerPanel } from './archive'
import './surfaces.css'
import { useAnalyst } from './use-analyst'

const SEASON = '2025-26'

interface ReportSummary {
  id: number
  game_id: number
  title: string
  summary: string
  created_at: string
}

const navItems = [
  { href: '/', label: 'Archive' },
  { href: '/games', label: 'Games' },
  { href: '/reports', label: 'Reports' },
  { href: '/analyst', label: 'Analyst' },
]

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value))
}

function teamLabel(id: string, fallback?: string | null) {
  if (fallback) return fallback
  if (id === 'NYK') return 'New York Knicks'
  return id
}

function shortTeamLabel(id: string, fallback?: string | null) {
  if (fallback) return fallback
  if (id === 'NYK') return 'NYK'
  return id
}

function resultForGame(game: GameSummary) {
  if (game.status !== 'final') return game.status
  return game.winner_team_id === 'NYK' ? 'W' : 'L'
}

function SurfaceState({
  kind,
  message,
  onRetry,
}: {
  kind: 'loading' | 'error' | 'empty'
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      className={`surface-state surface-state-${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      {kind === 'loading' ? (
        <Loader2 className='animate-spin' aria-hidden='true' />
      ) : null}
      {kind === 'error' ? <CircleAlert aria-hidden='true' /> : null}
      <span>{message}</span>
      {onRetry ? (
        <Button type='button' variant='outline' size='sm' onClick={onRetry}>
          <RefreshCw aria-hidden='true' /> Try again
        </Button>
      ) : null}
    </div>
  )
}

export function AppShell({
  eyebrow,
  title,
  description,
  children,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  const location = useLocation()

  return (
    <div className='surface-app'>
      <header className='surface-topbar'>
        <div className='surface-container surface-topbar-inner'>
          <Link
            className='surface-brand'
            to='/'
            aria-label='KnicksIQ archive home'
          >
            <span className='surface-brand-mark' aria-hidden='true'>
              <img
                src='/images/knicksiq-mark-v2.png'
                alt=''
                width='256'
                height='256'
              />
            </span>
            <span>
              <strong>KnicksIQ</strong>
              <small>Season intelligence desk</small>
            </span>
          </Link>
          <nav className='surface-nav' aria-label='Primary navigation'>
            {navItems.map((item) => {
              const active =
                item.href === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  className={active ? 'is-active' : ''}
                  to={item.href}
                  aria-current={active ? 'page' : undefined}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
          <span className='surface-season'>
            2025–26 <span aria-hidden='true'>/</span> archive
          </span>
        </div>
      </header>
      <main className='surface-container surface-main'>
        <header className='surface-page-heading'>
          <div>
            <p className='surface-kicker'>{eyebrow}</p>
            <h1>{title}</h1>
            <p className='surface-description'>{description}</p>
          </div>
          {actions ? (
            <div className='surface-heading-actions'>{actions}</div>
          ) : null}
        </header>
        {children}
      </main>
      <footer className='surface-footer'>
        <div className='surface-container surface-footer-inner'>
          <span>Unofficial fan archive · data-led, source-conscious.</span>
          <nav aria-label='Footer navigation'>
            <Link to='/'>Archive</Link>
            <a href='/sources.html'>Sources</a>
            <a href='/feedback.html'>Feedback</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}

function MetricStrip({
  items,
}: {
  items: Array<{
    label: string
    value: string
    tone?: 'blue' | 'orange' | 'neutral'
  }>
}) {
  return (
    <div className='metric-strip'>
      {items.map((item) => (
        <div
          className={`metric-cell metric-cell-${item.tone ?? 'neutral'}`}
          key={item.label}
        >
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}

function GameRow({ game }: { game: GameSummary }) {
  const result = resultForGame(game)
  const isWin = result === 'W'
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
        className={`game-margin ${game.margin >= 0 ? 'positive' : 'negative'}`}
      >
        {game.margin > 0 ? '+' : ''}
        {game.margin}
      </span>
      <ChevronRight className='game-row-arrow' aria-hidden='true' />
    </Link>
  )
}

function useArchivePosition() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.searchStr)
  const rawPage = Number(params.get('page') || 1)
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const set = (values: Record<string, string | number>) => {
    const next: Record<string, string | number> = Object.fromEntries(params)
    Object.entries(values).forEach(([key, value]) => {
      next[key] = value
    })
    void navigate({ to: location.pathname, search: () => next })
  }
  return { page, params, set }
}

function Pagination({
  page,
  total,
  onPage,
}: {
  page: number
  total: number
  onPage: (page: number) => void
}) {
  return (
    <nav aria-label='Pagination' className='filter-row'>
      {Array.from(
        { length: Math.ceil(total / 50) },
        (_, index) => index + 1
      ).map((value) => (
        <Button
          key={value}
          variant={page === value ? 'default' : 'outline'}
          aria-current={page === value ? 'page' : undefined}
          onClick={() => onPage(value)}
        >
          {value}
        </Button>
      ))}
    </nav>
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
        limit: 50,
        offset: (page - 1) * 50,
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
          total={status.data?.matching_games ?? status.data?.games ?? page * 50}
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

function Scoreboard({ game }: { game: Awaited<ReturnType<typeof fetchGame>> }) {
  const homeWon = game.winner_team_id === game.home_team_id
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
          {game.margin > 0 ? '+' : ''}
          {game.margin} margin
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
              key={run.id}
            >
              <span className='run-period'>
                Q{run.period}
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

function PlayByPlayPanel({ events }: { events: GameEvent[] }) {
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
        <div className='table-scroll'>
          <table className='data-table'>
            <caption className='sr-only'>Play-by-play events</caption>
            <thead>
              <tr>
                <th scope='col'>Clock</th>
                <th scope='col'>Event</th>
                <th scope='col'>Score</th>
                <th scope='col'>Margin</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
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
                    className={`font-stats ${event.score_margin > 0 ? 'positive' : event.score_margin < 0 ? 'negative' : ''}`}
                  >
                    {event.score_margin > 0 ? '+' : ''}
                    {event.score_margin}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function GameDetailPage({ gameId }: { gameId: string }) {
  const id = Number(gameId)
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
      {events.isSuccess ? <PlayByPlayPanel events={events.data} /> : null}
    </AppShell>
  )
}

function ReportRow({ report }: { report: ReportSummary }) {
  return (
    <Link
      className='report-row'
      to='/reports/$reportId'
      params={{ reportId: String(report.id) }}
      search={(previous) => previous}
    >
      <span className='report-index'>
        R{String(report.id).padStart(2, '0')}
      </span>
      <span>
        <strong>{report.title}</strong>
        <small>
          {formatDate(report.created_at)} · Game {report.game_id}
        </small>
      </span>
      <p>{report.summary}</p>
      <ArrowUpRight aria-hidden='true' />
    </Link>
  )
}

export function ReportsPage() {
  const { page, set } = useArchivePosition()
  const status = useQuery({
    queryKey: ['archive-status'],
    queryFn: () => fetchArchiveStatus(),
  })
  const reports = useQuery({
    queryKey: ['reports', page],
    queryFn: () => fetchReports({ limit: 50, offset: (page - 1) * 50 }),
  })
  return (
    <AppShell
      eyebrow='Reviewed output'
      title='Reports with a point of view.'
      description='Game reports turn archive evidence into a readable account of the turning point, the response, and the next adjustment.'
      actions={
        <Badge variant='outline'>
          <FileText aria-hidden='true' /> Reports
        </Badge>
      }
    >
      <section
        className='surface-panel report-index-panel'
        aria-labelledby='report-index-title'
      >
        <div className='surface-panel-header'>
          <div>
            <p className='surface-kicker'>The notebook</p>
            <h2 id='report-index-title'>Game reports</h2>
          </div>
          <span className='panel-count'>
            {status.data?.reports ?? '—'} reports
          </span>
        </div>
        <Pagination
          page={page}
          total={status.data?.reports ?? page * 50}
          onPage={(value) => set({ page: value })}
        />
        {reports.isPending ? (
          <SurfaceState kind='loading' message='Loading reviewed reports…' />
        ) : null}
        {reports.isError ? (
          <SurfaceState
            kind='error'
            message='Reports could not be loaded.'
            onRetry={() => void reports.refetch()}
          />
        ) : null}
        {reports.isSuccess && reports.data.length === 0 ? (
          <SurfaceState
            kind='empty'
            message='No reviewed reports are in the archive yet.'
          />
        ) : null}
        {reports.isSuccess && reports.data.length > 0 ? (
          <div className='report-list'>
            {reports.data.map((report) => (
              <ReportRow key={report.id} report={report} />
            ))}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}

function ReportSection({
  title,
  children,
  tone,
}: {
  title: string
  children: React.ReactNode
  tone?: 'orange' | 'blue'
}) {
  return (
    <section className={`report-section report-section-${tone ?? 'neutral'}`}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export function ReportDetailPage({ reportId }: { reportId: string }) {
  const id = Number(reportId)
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: () => fetchReport(id),
    enabled: Number.isSafeInteger(id) && id > 0,
  })
  if (report.isPending && Number.isSafeInteger(id) && id > 0)
    return (
      <AppShell
        eyebrow='Report detail'
        title='Loading report.'
        description='Opening the reviewed game notebook.'
      >
        <SurfaceState kind='loading' message='Loading report…' />
      </AppShell>
    )
  if (report.isError || !report.data)
    return (
      <AppShell
        eyebrow='Report detail'
        title='Report unavailable.'
        description='This report could not be found in the archive.'
      >
        <SurfaceState
          kind='error'
          message='The report could not be loaded.'
          onRetry={() => void report.refetch()}
        />
      </AppShell>
    )
  const item: Report = report.data
  return (
    <AppShell
      eyebrow='Reviewed report'
      title={item.title}
      description={item.summary}
      actions={
        <Link
          className='surface-back-link'
          to='/reports'
          search={(previous) => previous}
        >
          <ArrowLeft aria-hidden='true' /> Back to reports
        </Link>
      }
    >
      <div className='report-meta'>
        <Link to='/games/$gameId' params={{ gameId: String(item.game_id) }}>
          Open game {item.game_id}
        </Link>
        <span>
          Published{' '}
          <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
        </span>
      </div>
      <article className='surface-panel report-detail-panel'>
        <ReportSection title='Selected scoring run' tone='orange'>
          <p>{item.turning_point}</p>
        </ReportSection>
        <div className='report-two-up'>
          <ReportSection title='Best stretch' tone='blue'>
            <p>{item.best_stretch}</p>
          </ReportSection>
          <ReportSection title='Worst stretch'>
            <p>{item.worst_stretch}</p>
          </ReportSection>
        </div>
        <div className='report-two-up'>
          <ReportSection title='Player notes'>
            <ul>
              {item.player_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </ReportSection>
          <ReportSection title='Suggested adjustments'>
            <ul>
              {item.suggested_adjustments.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </ReportSection>
        </div>
        {item.sources.length > 0 ? (
          <div className='report-sources'>
            <p className='surface-kicker'>Sources used</p>
            <div>
              {item.sources.map((source, index) => (
                <Badge variant='outline' key={`${source.type}-${index}`}>
                  {typeof source.source_url === 'string' &&
                  /^https?:\/\//.test(source.source_url) ? (
                    <a
                      href={source.source_url}
                      target='_blank'
                      rel='noreferrer'
                    >
                      {source.type}
                      <span className='sr-only'> (opens in a new tab)</span>
                    </a>
                  ) : typeof source.url === 'string' &&
                    /^https?:\/\//.test(source.url) ? (
                    <a href={source.url} target='_blank' rel='noreferrer'>
                      {source.type}
                      <span className='sr-only'> (opens in a new tab)</span>
                    </a>
                  ) : (
                    source.type
                  )}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </article>
    </AppShell>
  )
}

export function AnalystPage() {
  const {
    question,
    setQuestion,
    messages,
    analyst,
    submit,
    archiveReady,
    archiveFailed,
    slow,
    retryReadiness,
  } = useAnalyst()
  const quick = useMemo(
    () => [
      'How did the Knicks perform against Boston?',
      'Which games had the wildest swings?',
      'When was the longest losing streak?',
    ],
    []
  )
  return (
    <AppShell
      eyebrow='Focused analysis'
      title='Talk through the tape.'
      description='A dedicated analyst view for follow-up questions, clarifications, and answers with their receipts.'
      actions={
        <Badge variant='outline'>
          <MessageSquareText aria-hidden='true' /> {SEASON}
        </Badge>
      }
    >
      <section className='analyst-layout'>
        <div className='surface-panel analyst-console'>
          <div className='surface-panel-header'>
            <div>
              <p className='surface-kicker'>The analyst desk</p>
              <h2>What are you trying to prove?</h2>
            </div>
            <BarChart3
              className='panel-icon panel-icon-orange'
              aria-hidden='true'
            />
          </div>
          {!archiveReady && (
            <SurfaceState
              kind={archiveFailed ? 'error' : 'loading'}
              message={
                archiveFailed
                  ? 'Archive unavailable'
                  : slow
                    ? 'The archive is starting slowly. Please wait…'
                    : 'Preparing archive'
              }
              onRetry={archiveFailed ? retryReadiness : undefined}
            />
          )}
          <div className='analyst-form'>
            <label htmlFor='analyst-question'>Ask a season question</label>
            <Textarea
              id='analyst-question'
              disabled={!archiveReady || analyst.isPending}
              maxLength={1200}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === 'Enter' &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault()
                  submit()
                }
              }}
              placeholder='Ask about a game, streak, opponent, player, or turning point…'
              rows={5}
            />
            <div className='analyst-form-footer'>
              <span>Enter to send · Shift + Enter for a new line</span>
              <Button
                type='button'
                onClick={() => submit()}
                disabled={
                  !archiveReady || !question.trim() || analyst.isPending
                }
              >
                {analyst.isPending ? (
                  <Loader2 className='animate-spin' />
                ) : (
                  <Search />
                )}{' '}
                Ask archive
              </Button>
            </div>
          </div>
          <div
            className='analyst-quick'
            aria-label='Suggested analyst questions'
          >
            {quick.map((item) => (
              <button
                key={item}
                type='button'
                disabled={!archiveReady || analyst.isPending}
                onClick={() => {
                  setQuestion(item)
                  requestAnimationFrame(() =>
                    document.getElementById('analyst-question')?.focus()
                  )
                }}
              >
                {item}
                <ArrowUpRight aria-hidden='true' />
              </button>
            ))}
          </div>
        </div>
        <div className='analyst-thread' aria-live='polite'>
          {analyst.error ? (
            <SurfaceState
              kind='error'
              message={
                navigator.onLine
                  ? 'The analyst could not answer that request. Retry shortly if it timed out or reached a rate limit.'
                  : 'You are offline. Reconnect to search the archive.'
              }
              onRetry={() =>
                analyst.variables && analyst.mutate(analyst.variables)
              }
            />
          ) : null}
          {analyst.isPending ? (
            <SurfaceState kind='loading' message='Reading the season tape…' />
          ) : null}
          {messages.length === 0 && !analyst.isPending ? (
            <div className='analyst-empty'>
              <MessageSquareText aria-hidden='true' />
              <h2>Start a line of inquiry.</h2>
              <p>
                The thread will keep the question, the response, and the
                limitations together.
              </p>
            </div>
          ) : null}
          {messages.map((message) => (
            <div key={message.id}>
              {message.response ? (
                <AnswerPanel
                  answer={message.response}
                  onClarification={submit}
                  disabled={!archiveReady || analyst.isPending}
                />
              ) : (
                <p className='archive-question'>{message.content}</p>
              )}
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  )
}
