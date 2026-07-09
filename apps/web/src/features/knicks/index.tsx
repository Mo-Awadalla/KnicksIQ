import {
  type ElementType,
  Fragment,
  type KeyboardEvent,
  type ReactNode,
  useMemo,
  useState,
} from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Bot,
  CalendarDays,
  DatabaseZap,
  FileText,
  Loader2,
  MessageSquareText,
  RadioTower,
  RefreshCw,
  Search as SearchIcon,
  Trophy,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  askAnalyst,
  fetchBadStretches,
  fetchGame,
  fetchGames,
  fetchPlayByPlay,
  fetchPlayers,
  fetchReport,
  fetchReports,
  fetchRuns,
  generatePostgameReport,
  triggerDetectRuns,
  triggerIngestGames,
} from '@/api'
import type { AnalysisContextMessage, GameDataStatus, GameSummary, Player } from '@/types'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const KNICKS_SEASON = '2025-26'
const GAMES_PAGE_LIMIT = 200

function Shell({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <>
      <Header fixed>
        <Search placeholder='Search pages and commands' />
      </Header>
      <Main className='space-y-6'>
        <div className='flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between'>
          <div>
            <h1 className='text-3xl font-semibold tracking-normal'>{title}</h1>
            <p className='text-sm text-muted-foreground'>{description}</p>
          </div>
        </div>
        {children}
      </Main>
    </>
  )
}

function DataStatusBadge({ status }: { status: GameDataStatus }) {
  if (status === 'analysis_ready') {
    return <Badge className='bg-[#0072ce] text-white'>Analysis ready</Badge>
  }
  if (status === 'events_ready') {
    return <Badge className='bg-emerald-600 text-white'>Play-by-play ready</Badge>
  }
  return <Badge variant='outline'>Summary only</Badge>
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatMonth(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  })
}

function knicksScore(game: GameSummary) {
  const isHome = game.home_team_id === 'NYK'
  return {
    points: isHome ? game.home_score : game.away_score,
    opponentPoints: isHome ? game.away_score : game.home_score,
    won: game.winner_team_id === 'NYK',
  }
}

function GamesTable({
  games,
  groupByMonth = false,
}: {
  games: GameSummary[]
  groupByMonth?: boolean
}) {
  const monthGroups = useMemo(() => {
    if (!groupByMonth) return [{ label: null, games }]
    const sorted = [...games].sort(
      (a, b) =>
        new Date(a.game_date).getTime() - new Date(b.game_date).getTime() ||
        a.id - b.id
    )
    const groups: { label: string | null; games: GameSummary[] }[] = []
    for (const game of sorted) {
      const label = formatMonth(game.game_date)
      const current = groups[groups.length - 1]
      if (!current || current.label !== label) {
        groups.push({ label, games: [game] })
      } else {
        current.games.push(game)
      }
    }
    return groups
  }, [games, groupByMonth])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Games</CardTitle>
        <CardDescription>
          Knicks schedule, data completeness, and analysis entry points.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Game</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Data</TableHead>
                <TableHead className='text-right'>Knicks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {monthGroups.map((group) => (
                <Fragment key={group.label ?? 'all-games'}>
                  {group.label && (
                    <TableRow className='bg-muted/40 hover:bg-muted/40'>
                      <TableCell
                        colSpan={4}
                        className='py-2 text-xs font-semibold uppercase text-muted-foreground'
                      >
                        {group.label}
                      </TableCell>
                    </TableRow>
                  )}
                  {group.games.map((game) => {
                    const score = knicksScore(game)
                    return (
                      <TableRow key={game.id}>
                        <TableCell>
                          <Link
                            to='/games/$gameId'
                            params={{ gameId: String(game.id) }}
                            className='font-medium hover:text-primary'
                          >
                            {game.away_team_id} @ {game.home_team_id}
                          </Link>
                          <div className='mt-1 text-xs text-muted-foreground'>
                            {formatDate(game.game_date)} -{' '}
                            {game.season_type.replace('_', '-')}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={score.won ? 'default' : 'secondary'}>
                            {score.won ? 'W' : 'L'} - {game.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <DataStatusBadge status={game.data_status} />
                        </TableCell>
                        <TableCell className='text-right font-semibold'>
                          {score.points}-{score.opponentPoints}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export function GamesCommandCenter() {
  const queryClient = useQueryClient()
  const games = useQuery({
    queryKey: ['games', 'command-center'],
    queryFn: () =>
      fetchGames({ teamId: 'NYK', season: KNICKS_SEASON, limit: GAMES_PAGE_LIMIT }),
  })
  const reports = useQuery({
    queryKey: ['reports'],
    queryFn: fetchReports,
  })
  const ingest = useMutation({
    mutationFn: () => triggerIngestGames(KNICKS_SEASON),
    onSuccess: (job) => {
      toast.success(`Ingestion queued: ${job.job_id}`)
      queryClient.invalidateQueries({ queryKey: ['games'] })
    },
  })

  const data = games.data ?? []
  const wins = data.filter((game) => game.winner_team_id === 'NYK').length
  const ready = data.filter((game) => game.data_status === 'analysis_ready').length
  const events = data.filter((game) => game.data_status !== 'summary_only').length
  const recent = data.slice(0, 8)

  return (
    <Shell
      title='Games Command Center'
      description='Operational view of the Knicks season archive, analysis readiness, and admin actions.'
    >
      <div className='grid gap-4 md:grid-cols-4'>
        <MetricCard icon={CalendarDays} label='Cached games' value={data.length} />
        <MetricCard icon={Trophy} label='Knicks wins' value={wins} />
        <MetricCard icon={Activity} label='Event-ready' value={events} />
        <MetricCard icon={FileText} label='Reports' value={reports.data?.length ?? 0} />
      </div>

      <Card className='border-primary/30 bg-primary text-primary-foreground'>
        <CardHeader>
          <CardTitle>Data Pipeline</CardTitle>
          <CardDescription className='text-primary-foreground/75'>
            Queue a season ingest, then use game detail pages to detect runs and generate reports.
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-wrap gap-3'>
          <Button
            variant='secondary'
            disabled={ingest.isPending}
            onClick={() => ingest.mutate()}
          >
            {ingest.isPending ? <Loader2 className='animate-spin' /> : <DatabaseZap />}
            Ingest {KNICKS_SEASON}
          </Button>
          <Button variant='outline' className='bg-white/10 text-white' asChild>
            <Link to='/games'>Open Games</Link>
          </Button>
          <div className='flex items-center gap-2 text-sm text-primary-foreground/75'>
            <RadioTower className='size-4' />
            {ready} games analysis-ready
          </div>
        </CardContent>
      </Card>

      {games.isLoading ? (
        <LoadingState label='Loading games' />
      ) : games.error ? (
        <ErrorState label='Failed to load games.' />
      ) : (
        <GamesTable games={recent} />
      )}
    </Shell>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: ElementType
  label: string
  value: number
}) {
  return (
    <Card>
      <CardContent className='flex items-center justify-between pt-6'>
        <div>
          <p className='text-sm text-muted-foreground'>{label}</p>
          <p className='mt-1 text-3xl font-semibold'>{value}</p>
        </div>
        <div className='rounded-md bg-accent p-3 text-accent-foreground'>
          <Icon className='size-5' />
        </div>
      </CardContent>
    </Card>
  )
}

export function GamesPage() {
  const [seasonType, setSeasonType] = useState('')
  const [dataStatus, setDataStatus] = useState('')
  const [search, setSearch] = useState('')
  const games = useQuery({
    queryKey: ['games', seasonType, dataStatus],
    queryFn: () =>
      fetchGames({
        teamId: 'NYK',
        season: KNICKS_SEASON,
        seasonType: seasonType || undefined,
        dataStatus: dataStatus || undefined,
        limit: GAMES_PAGE_LIMIT,
      }),
  })
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return games.data ?? []
    return (games.data ?? []).filter((game) =>
      `${game.away_team_id} ${game.home_team_id} ${game.game_label ?? ''}`
        .toLowerCase()
        .includes(needle)
    )
  }, [games.data, search])

  return (
    <Shell
      title='Games'
      description='Browse Knicks games by season type, data completeness, and opponent.'
    >
      <Card>
        <CardContent className='grid gap-3 pt-6 md:grid-cols-[1fr_180px_200px]'>
          <div className='relative'>
            <SearchIcon className='absolute left-3 top-2.5 size-4 text-muted-foreground' />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className='pl-9'
              placeholder='Filter by matchup'
            />
          </div>
          <select
            value={seasonType}
            onChange={(event) => setSeasonType(event.target.value)}
            className='h-9 rounded-md border bg-background px-3 text-sm'
          >
            <option value=''>All season types</option>
            <option value='regular'>Regular season</option>
            <option value='play_in'>Play-in</option>
            <option value='playoffs'>Playoffs</option>
          </select>
          <select
            value={dataStatus}
            onChange={(event) => setDataStatus(event.target.value)}
            className='h-9 rounded-md border bg-background px-3 text-sm'
          >
            <option value=''>All data statuses</option>
            <option value='summary_only'>Summary only</option>
            <option value='events_ready'>Play-by-play ready</option>
            <option value='analysis_ready'>Analysis ready</option>
          </select>
        </CardContent>
      </Card>
      {games.isLoading ? (
        <LoadingState label='Loading games' />
      ) : games.error ? (
        <ErrorState label='Failed to load games.' />
      ) : (
        <GamesTable games={filtered} groupByMonth />
      )}
    </Shell>
  )
}

export function GameDetailPage({ gameId }: { gameId: number }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const game = useQuery({
    queryKey: ['game', gameId],
    queryFn: () => fetchGame(gameId),
  })
  const hasEvents = game.data?.data_status !== 'summary_only'
  const runs = useQuery({
    queryKey: ['runs', gameId],
    queryFn: () => fetchRuns(gameId),
    enabled: !!game.data && hasEvents,
  })
  const stretches = useQuery({
    queryKey: ['bad-stretches', gameId],
    queryFn: () => fetchBadStretches(gameId),
    enabled: !!game.data && hasEvents,
  })
  const pbp = useQuery({
    queryKey: ['pbp', gameId],
    queryFn: () => fetchPlayByPlay(gameId),
    enabled: !!game.data && hasEvents,
  })
  const homeRoster = useQuery({
    queryKey: ['players', game.data?.home_team_id],
    queryFn: () => fetchPlayers({ teamId: game.data?.home_team_id, limit: 200 }),
    enabled: !!game.data?.home_team_id,
  })
  const awayRoster = useQuery({
    queryKey: ['players', game.data?.away_team_id],
    queryFn: () => fetchPlayers({ teamId: game.data?.away_team_id, limit: 200 }),
    enabled: !!game.data?.away_team_id,
  })
  const detect = useMutation({
    mutationFn: () => triggerDetectRuns(gameId),
    onSuccess: (job) => {
      toast.success(`Run detection queued: ${job.job_id}`)
      queryClient.invalidateQueries({ queryKey: ['runs', gameId] })
      queryClient.invalidateQueries({ queryKey: ['bad-stretches', gameId] })
    },
  })
  const report = useMutation({
    mutationFn: () => generatePostgameReport(gameId),
    onSuccess: (created) => {
      navigate({
        to: '/reports/$reportId',
        params: { reportId: String(created.id) },
      })
    },
  })

  if (game.isLoading) return <Shell title='Game' description='Loading game detail.'><LoadingState label='Loading game' /></Shell>
  if (game.error || !game.data) return <Shell title='Game' description='Game not found.'><ErrorState label='Game not found.' /></Shell>

  const score = knicksScore(game.data)

  return (
    <Shell
      title={`${game.data.away_team_id} @ ${game.data.home_team_id}`}
      description={`${formatDate(game.data.game_date)} - ${game.data.season} - ${game.data.season_type.replace('_', '-')}`}
    >
      <div className='grid gap-4 xl:grid-cols-[1fr_360px]'>
        <div className='space-y-4'>
          <Card>
            <CardContent className='flex flex-col gap-4 pt-6 md:flex-row md:items-center md:justify-between'>
              <div>
                <DataStatusBadge status={game.data.data_status} />
                <div className='mt-3 text-5xl font-semibold'>
                  {score.points}-{score.opponentPoints}
                </div>
                <p className='mt-1 text-sm text-muted-foreground'>
                  Knicks {score.won ? 'win' : 'loss'} - margin {Math.abs(game.data.margin)}
                </p>
              </div>
              <div className='flex flex-wrap gap-2'>
                <Button
                  disabled={detect.isPending || !hasEvents}
                  onClick={() => detect.mutate()}
                >
                  {detect.isPending ? <Loader2 className='animate-spin' /> : <RefreshCw />}
                  Detect Runs
                </Button>
                <Button
                  className='bg-[#fe5000] text-white hover:bg-[#dc4600]'
                  disabled={report.isPending || !hasEvents}
                  onClick={() => report.mutate()}
                >
                  {report.isPending ? <Loader2 className='animate-spin' /> : <FileText />}
                  Generate Report
                </Button>
              </div>
            </CardContent>
          </Card>

          {!hasEvents && (
            <Card>
              <CardContent className='pt-6 text-sm text-muted-foreground'>
                This game has cached score and schedule metadata only. Event-level analysis will appear after play-by-play is cached.
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Scoring Runs</CardTitle>
              <CardDescription>Detected momentum swings from cached play-by-play.</CardDescription>
            </CardHeader>
            <CardContent className='space-y-3'>
              {runs.data?.length ? runs.data.map((run) => (
                <div key={run.id} className='rounded-md border p-3'>
                  <div className='flex items-center justify-between gap-3'>
                    <div className='font-medium'>
                      {run.team_id} {run.points_for}-{run.points_against} run
                    </div>
                    <Badge variant={run.team_id === 'NYK' ? 'default' : 'secondary'}>
                      Delta {run.score_delta > 0 ? '+' : ''}{run.score_delta}
                    </Badge>
                  </div>
                  <p className='mt-1 text-sm text-muted-foreground'>
                    Q{run.period} {run.start_clock} to {run.end_clock}
                  </p>
                  {run.summary && <p className='mt-2 text-sm'>{run.summary}</p>}
                </div>
              )) : <EmptyState label='No scoring runs detected yet.' />}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Play-by-Play</CardTitle>
              <CardDescription>Event stream used by reports and run detection.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className='max-h-96 overflow-auto rounded-md border'>
                <Table>
                  <TableBody>
                    {pbp.data?.map((event) => (
                      <TableRow key={event.id}>
                        <TableCell className='w-24 text-xs text-muted-foreground'>
                          Q{event.period} {event.clock}
                        </TableCell>
                        <TableCell className='w-16 text-xs text-muted-foreground'>
                          {event.team_id ?? '-'}
                        </TableCell>
                        <TableCell className='w-40 text-sm'>
                          {event.player_name ?? '-'}
                        </TableCell>
                        <TableCell>{event.description}</TableCell>
                        <TableCell className='text-right text-xs text-muted-foreground'>
                          {event.away_score}-{event.home_score}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue='stretches' className='min-w-0'>
          <TabsList className='grid w-full grid-cols-2'>
            <TabsTrigger value='stretches'>
              <Activity className='size-4' />
              Stretches
            </TabsTrigger>
            <TabsTrigger value='roster'>
              <UsersRound className='size-4' />
              Roster
            </TabsTrigger>
          </TabsList>
          <TabsContent value='stretches' className='mt-4'>
            <Card>
              <CardHeader>
                <CardTitle>Bad Stretches</CardTitle>
                <CardDescription>Knicks-negative segments and likely causes.</CardDescription>
              </CardHeader>
              <CardContent className='space-y-3'>
                {stretches.data?.length ? stretches.data.map((stretch) => (
                  <div key={stretch.id} className='rounded-md border border-destructive/40 p-3'>
                    <Badge variant='destructive'>
                      Q{stretch.period} {stretch.start_clock} to {stretch.end_clock}
                    </Badge>
                    <p className='mt-2 text-sm'>{stretch.summary}</p>
                    <p className='mt-2 text-xs text-muted-foreground'>
                      Causes: {stretch.likely_causes.join(', ') || 'Unclassified'}
                    </p>
                  </div>
                )) : <EmptyState label='No bad stretches detected.' />}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value='roster' className='mt-4'>
            <Card>
              <CardHeader>
                <CardTitle>Roster</CardTitle>
                <CardDescription>Game-side player list and championship photo slots.</CardDescription>
              </CardHeader>
              <CardContent className='space-y-5'>
                <RosterGroup
                  teamId={game.data.away_team_id}
                  players={awayRoster.data ?? []}
                  isLoading={awayRoster.isLoading}
                />
                <RosterGroup
                  teamId={game.data.home_team_id}
                  players={homeRoster.data ?? []}
                  isLoading={homeRoster.isLoading}
                />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </Shell>
  )
}

function RosterGroup({
  teamId,
  players,
  isLoading,
}: {
  teamId: string
  players: Player[]
  isLoading: boolean
}) {
  return (
    <section className='space-y-2'>
      <div className='flex items-center justify-between'>
        <div className='text-sm font-medium'>{teamId}</div>
        <Badge variant='outline'>{players.length}</Badge>
      </div>
      {isLoading ? <LoadingState label={`Loading ${teamId} roster`} /> : null}
      {!isLoading && players.length === 0 ? <EmptyState label='No roster players found.' /> : null}
      <div className='space-y-2'>
        {players.map((player) => (
          <RosterPlayerRow key={player.id} player={player} />
        ))}
      </div>
    </section>
  )
}

function RosterPlayerRow({ player }: { player: Player }) {
  return (
    <div className='grid grid-cols-[56px_1fr_auto] items-center gap-3 rounded-md border p-2'>
      <ChampionshipPhotoSlot player={player} />
      <div className='min-w-0'>
        <div className='truncate text-sm font-medium'>{player.full_name}</div>
        <div className='text-xs text-muted-foreground'>
          {player.position ?? 'Roster'}{player.jersey_number ? ` - #${player.jersey_number}` : ''}
        </div>
      </div>
      <Badge variant={player.team_id === 'NYK' ? 'default' : 'secondary'}>
        {player.team_id ?? '-'}
      </Badge>
    </div>
  )
}

function ChampionshipPhotoSlot({ player }: { player: Player }) {
  const [failed, setFailed] = useState(false)
  const initials = player.full_name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  if (!failed) {
    return (
      <img
        src={`/championship-pics/${player.nba_player_id}.jpg`}
        alt={player.full_name}
        onError={() => setFailed(true)}
        className='size-14 rounded-md border object-cover'
      />
    )
  }

  return (
    <div className='flex size-14 items-center justify-center rounded-md border bg-muted text-xs font-semibold text-muted-foreground'>
      {initials}
    </div>
  )
}

export function ReportsPage() {
  const reports = useQuery({
    queryKey: ['reports'],
    queryFn: fetchReports,
  })

  return (
    <Shell
      title='Reports'
      description='Saved postgame autopsies generated from game context, runs, and source traces.'
    >
      <Card>
        <CardContent className='pt-6'>
          {reports.isLoading ? <LoadingState label='Loading reports' /> : null}
          {reports.error ? <ErrorState label='Failed to load reports.' /> : null}
          {reports.data?.length === 0 ? <EmptyState label='No reports yet.' /> : null}
          <div className='space-y-3'>
            {reports.data?.map((report) => (
              <Link
                key={report.id}
                to='/reports/$reportId'
                params={{ reportId: String(report.id) }}
                className='block rounded-md border p-4 transition hover:border-primary'
              >
                <div className='text-xs text-muted-foreground'>
                  {new Date(report.created_at).toLocaleString()} - game {report.game_id}
                </div>
                <div className='mt-1 font-medium'>{report.title}</div>
                <p className='mt-1 line-clamp-2 text-sm text-muted-foreground'>
                  {report.summary}
                </p>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </Shell>
  )
}

export function ReportDetailPage({ reportId }: { reportId: number }) {
  const report = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => fetchReport(reportId),
  })

  if (report.isLoading) return <Shell title='Report' description='Loading report.'><LoadingState label='Loading report' /></Shell>
  if (report.error || !report.data) return <Shell title='Report' description='Report not found.'><ErrorState label='Report not found.' /></Shell>

  return (
    <Shell title={report.data.title} description={`Generated ${new Date(report.data.created_at).toLocaleString()}`}>
      <div className='grid gap-4 lg:grid-cols-[1fr_360px]'>
        <div className='space-y-4'>
          <ReportSection title='Summary' body={report.data.summary} />
          <ReportSection title='Turning Point' body={report.data.turning_point} />
          <div className='grid gap-4 md:grid-cols-2'>
            <ReportSection title='Best Stretch' body={report.data.best_stretch} />
            <ReportSection title='Worst Stretch' body={report.data.worst_stretch} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Suggested Adjustments</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className='list-inside list-disc space-y-1 text-sm'>
                {report.data.suggested_adjustments.map((adjustment) => (
                  <li key={adjustment}>{adjustment}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Sources</CardTitle>
            <CardDescription>Citations and tool calls saved with the report.</CardDescription>
          </CardHeader>
          <CardContent className='space-y-4'>
            {report.data.sources.map((source, index) => (
              <div key={`${source.type}-${index}`} className='rounded-md border p-3 text-xs'>
                <Badge variant='outline'>{source.type}</Badge>
                <p className='mt-2 break-words text-muted-foreground'>
                  {Object.entries(source)
                    .filter(([key]) => key !== 'type')
                    .map(([key, value]) => `${key}=${String(value)}`)
                    .join(' - ')}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}

function ReportSection({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className='text-sm leading-6 text-muted-foreground'>
        {body}
      </CardContent>
    </Card>
  )
}

export function AnalystPage() {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<AnalysisContextMessage[]>([])
  const analyst = useMutation({
    mutationFn: ({
      context,
      question,
    }: {
      context: AnalysisContextMessage[]
      question: string
    }) => askAnalyst(question, KNICKS_SEASON, context),
    onSuccess: (data) => {
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: data.answer },
      ])
    },
  })
  const submitQuestion = () => {
    const nextQuestion = question.trim()
    if (!nextQuestion || analyst.isPending) return
    const context = messages.slice(-6)
    setMessages((current) => [...current, { role: 'user', content: nextQuestion }])
    setQuestion('')
    analyst.mutate({ question: nextQuestion, context })
  }
  const handleQuestionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    submitQuestion()
  }

  return (
    <Shell
      title='Analyst'
      description='Ask cited questions against cached Knicks games and documents.'
    >
      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Bot className='size-5 text-primary' />
            Analyst Workspace
          </CardTitle>
          <CardDescription>Questions are grounded in cached season data.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className='space-y-3'
            onSubmit={(event) => {
              event.preventDefault()
              submitQuestion()
            }}
          >
            <Textarea
              value={question}
              maxLength={1200}
              rows={5}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleQuestionKeyDown}
              placeholder='Which Knicks game had the biggest run?'
            />
            <div className='flex items-center justify-between gap-3'>
              <span className='text-xs text-muted-foreground'>{question.length}/1200</span>
              <div className='flex items-center gap-2'>
                {messages.length > 0 && (
                  <Button
                    type='button'
                    variant='outline'
                    onClick={() => {
                      setMessages([])
                      analyst.reset()
                    }}
                  >
                    New Chat
                  </Button>
                )}
                <Button disabled={analyst.isPending || !question.trim()}>
                  {analyst.isPending ? (
                    <Loader2 className='animate-spin' />
                  ) : (
                    <MessageSquareText />
                  )}
                  Ask Analyst
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {analyst.error && <ErrorState label='Analyst request failed.' />}
      {messages.length > 0 && (
        <div className='grid gap-4 lg:grid-cols-[1fr_360px]'>
          <Card>
            <CardHeader>
              <CardTitle>Conversation</CardTitle>
            </CardHeader>
            <CardContent className='space-y-4'>
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={
                    message.role === 'user'
                      ? 'ml-auto max-w-[85%] rounded-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground'
                      : 'max-w-[92%] rounded-md border px-4 py-3 text-sm leading-6 text-muted-foreground whitespace-pre-wrap'
                  }
                >
                  {message.content}
                </div>
              ))}
              {analyst.isPending && (
                <div className='flex items-center gap-2 text-sm text-muted-foreground'>
                  <Loader2 className='size-4 animate-spin' />
                  Analyst is checking cached evidence.
                </div>
              )}
            </CardContent>
          </Card>
          {analyst.data && (
            <Card>
              <CardHeader>
                <CardTitle>Citations</CardTitle>
                <CardDescription>
                  {analyst.data.route === 'table_rag'
                    ? 'Table rows used for the latest answer.'
                    : 'Retrieved evidence used for the latest answer.'}
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-3'>
                {analyst.data.citations.map((citation, index) => (
                  <div key={`${citation.type}-${index}`} className='rounded-md border p-3 text-sm'>
                    <Badge variant='outline'>{citation.type}</Badge>
                    <div className='mt-2 font-medium'>
                      {citation.game_id ? (
                        <Link
                          to='/games/$gameId'
                          params={{ gameId: String(citation.game_id) }}
                          className='hover:text-primary'
                        >
                          {citation.title}
                        </Link>
                      ) : (
                        citation.title
                      )}
                    </div>
                    {citation.source_name && (
                      <p className='text-xs text-muted-foreground'>{citation.source_name}</p>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </Shell>
  )
}

function LoadingState({ label }: { label: string }) {
  return (
    <Card>
      <CardContent className='flex items-center gap-2 pt-6 text-sm text-muted-foreground'>
        <Loader2 className='size-4 animate-spin' />
        {label}
      </CardContent>
    </Card>
  )
}

function EmptyState({ label }: { label: string }) {
  return <p className='text-sm text-muted-foreground'>{label}</p>
}

function ErrorState({ label }: { label: string }) {
  return (
    <Card className='border-destructive/40'>
      <CardContent className='pt-6 text-sm text-destructive'>{label}</CardContent>
    </Card>
  )
}
