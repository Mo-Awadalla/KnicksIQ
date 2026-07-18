import { type KeyboardEvent, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { askAnalyst, fetchArchiveStatus, fetchGames } from '@/api'
import type {
  AnalysisCitation,
  AnalysisContextMessage,
  AnalysisResponse,
  GameSummary,
} from '@/types'
import {
  CalendarDays,
  FileText,
  Loader2,
  Search,
  Sparkles,
  Trophy,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { AnalyticsCards } from './analytics-cards'
import { retainLastFour } from './conversation'

const KNICKS_SEASON = '2025-26'
const SUGGESTED_QUESTIONS = [
  'Who beat the Knicks by the most points?',
  'What was their best win?',
  'When was the longest losing streak?',
  'How many games did the Knicks win?',
  'How did they perform against Boston?',
  'Which games had the wildest swings?',
]

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function knicksScore(game: GameSummary) {
  const home = game.home_team_id === 'NYK'
  return {
    points: home ? game.home_score : game.away_score,
    opponentPoints: home ? game.away_score : game.home_score,
    opponent: home ? game.away_team_id : game.home_team_id,
    won: game.winner_team_id === 'NYK',
  }
}

function seasonSummary(games: GameSummary[]) {
  const wins = games.filter((game) => game.winner_team_id === 'NYK').length
  const losses = games.length - wins
  const eventReady = games.filter(
    (game) => game.data_status !== 'summary_only'
  ).length
  const biggestWin = games
    .filter((game) => game.winner_team_id === 'NYK')
    .sort((a, b) => b.margin - a.margin)[0]
  const biggestLoss = games
    .filter((game) => game.winner_team_id !== 'NYK')
    .sort((a, b) => b.margin - a.margin)[0]

  return { wins, losses, eventReady, biggestWin, biggestLoss }
}

function ReceiptCard({
  citation,
  games,
}: {
  citation: AnalysisCitation
  games: GameSummary[]
}) {
  const game = games.find((item) => item.id === citation.game_id)
  const score = game ? knicksScore(game) : null

  return (
    <Card className='border-[#BEC0C2]/70 bg-white'>
      <CardContent className='space-y-3 p-4'>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge className='bg-[#006BB6] text-white'>{citation.type}</Badge>
          <span className='text-sm font-semibold text-[#0d2238]'>
            {citation.title}
          </span>
        </div>
        <p className='text-sm leading-6 text-[#172a3d]'>
          Supports: {citation.claim}
        </p>
        {game && score ? (
          <div className='rounded-md border border-[#BEC0C2]/70 bg-[#f7f8fa] p-3'>
            <div className='text-sm font-semibold text-[#0d2238]'>
              {formatDate(game.game_date)} - NYK {score.points},{' '}
              {score.opponent} {score.opponentPoints}
            </div>
            <div className='mt-1 text-xs text-muted-foreground'>
              Knicks {score.won ? 'win' : 'loss'} by {Math.abs(game.margin)}
            </div>
          </div>
        ) : null}
        {citation.source_url ? (
          <a
            className='text-xs font-medium text-[#006BB6] underline underline-offset-2'
            href={citation.source_url}
            rel='noreferrer'
            target='_blank'
          >
            Source: {citation.source_name ?? 'NBA.com'}
          </a>
        ) : citation.source_name ? (
          <p className='text-xs text-muted-foreground'>
            Source: {citation.source_name}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function AnswerPanel({
  answer,
  games,
  onClarification,
}: {
  answer: AnalysisResponse
  games: GameSummary[]
  onClarification: (value: string) => void
}) {
  return (
    <section className='space-y-4'>
      <Card className='border-[#006BB6]/25 bg-white shadow-sm'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2 text-[#0d2238]'>
            <Sparkles className='size-5 text-[#F58426]' />
            Answer
          </CardTitle>
          {answer.warnings.length > 0 ? (
            <CardDescription>{answer.warnings.join(' ')}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent>
          {answer.degraded ? (
            <p className='mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950'>
              Optional AI or search services are degraded. This answer uses the
              deterministic archive fallback.
            </p>
          ) : null}
          <p className='text-base leading-7 whitespace-pre-wrap text-[#172a3d]'>
            {answer.answer}
          </p>
          {answer.analytics?.clarification ? (
            <div className='mt-4 flex flex-wrap gap-2'>
              {answer.analytics.clarification.choices.map((choice) => (
                <Button
                  key={choice.id}
                  type='button'
                  variant='outline'
                  onClick={() => onClarification(choice.value)}
                >
                  {choice.label}
                </Button>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {answer.analytics && answer.analytics.results.length > 0 ? (
        <AnalyticsCards analytics={answer.analytics} games={games} />
      ) : null}

      <div>
        <h2 className='mb-3 flex items-center gap-2 text-lg font-semibold text-[#0d2238]'>
          <FileText className='size-5 text-[#006BB6]' />
          Receipts
        </h2>
        {answer.citations.length > 0 ? (
          <div className='grid gap-3 md:grid-cols-2'>
            {answer.citations.map((citation, index) => (
              <ReceiptCard
                key={`${citation.title}-${index}`}
                citation={citation}
                games={games}
              />
            ))}
          </div>
        ) : (
          <Card className='border-[#BEC0C2]/70 bg-white'>
            <CardContent className='p-4 text-sm text-muted-foreground'>
              No separate game receipt was returned for this answer.
            </CardContent>
          </Card>
        )}
      </div>
    </section>
  )
}

export function SeasonArchivePage() {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<
    Array<
      AnalysisContextMessage & {
        id: string
        response?: AnalysisResponse
      }
    >
  >([])
  const games = useQuery({
    queryKey: ['games', 'season-archive'],
    queryFn: () =>
      fetchGames({ teamId: 'NYK', season: KNICKS_SEASON, limit: 200 }),
  })
  const archive = useQuery({
    queryKey: ['archive-status'],
    queryFn: fetchArchiveStatus,
  })
  const summary = useMemo(() => seasonSummary(games.data ?? []), [games.data])
  const analyst = useMutation({
    mutationFn: ({
      nextQuestion,
      context,
    }: {
      nextQuestion: string
      context: AnalysisContextMessage[]
    }) =>
      askAnalyst(
        nextQuestion,
        KNICKS_SEASON,
        context,
        [...messages]
          .reverse()
          .find((message) => message.response?.conversation_state)?.response
          ?.conversation_state
      ),
    onSuccess: (response) => {
      setMessages((current) =>
        retainLastFour(current, {
          id: `assistant-${response.request_id || Date.now()}`,
          role: 'assistant' as const,
          content: response.answer,
          response,
        })
      )
    },
  })

  const submit = (value = question) => {
    const nextQuestion = value.trim()
    if (!nextQuestion || analyst.isPending) return
    const context = messages
      .slice(-4)
      .map(({ role, content }) => ({ role, content }))
    setMessages((current) =>
      retainLastFour(current, {
        id: `user-${Date.now()}`,
        role: 'user' as const,
        content: nextQuestion,
      })
    )
    setQuestion('')
    analyst.mutate({ nextQuestion, context })
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return
    }
    event.preventDefault()
    submit()
  }

  return (
    <main className='min-h-screen bg-[#f4f7fb] text-[#0d2238]'>
      <section className='border-b border-[#BEC0C2]/60 bg-[#006BB6] text-white'>
        <div className='mx-auto flex max-w-6xl flex-col gap-8 px-4 py-10 md:px-8 md:py-14'>
          <div className='max-w-3xl space-y-4'>
            <Badge className='w-fit bg-[#F58426] text-[#0d2238]'>
              KnicksIQ Season Archive
            </Badge>
            <h1 className='text-4xl font-semibold tracking-normal md:text-6xl'>
              Relive the Knicks&apos; historic {KNICKS_SEASON} season.
            </h1>
            <p className='max-w-2xl text-base leading-7 text-white md:text-lg'>
              An anonymous, unofficial fan archive of every 2025-26 regular
              season and postseason game. Ask factual questions and inspect the
              receipts behind every answer.
            </p>
            <div className='flex flex-wrap gap-2 text-xs text-white/90'>
              <span className='rounded-full bg-[#004b80] px-3 py-1 text-white'>
                Data {archive.data?.data_version ?? 'loading'}
              </span>
              <span className='rounded-full bg-[#004b80] px-3 py-1 text-white'>
                {archive.data?.games ?? games.data?.length ?? 0} games
              </span>
              <span className='rounded-full bg-[#004b80] px-3 py-1 text-white'>
                Scores, box scores, play-by-play, reviewed reports
              </span>
            </div>
          </div>

          <Card className='border-white/20 bg-white text-[#0d2238] shadow-xl'>
            <CardContent className='space-y-4 p-4 md:p-6'>
              <Textarea
                value={question}
                maxLength={1200}
                rows={4}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder='Ask a Knicks season question...'
                className='min-h-32 resize-none border-[#BEC0C2] text-lg'
              />
              <div className='flex flex-col gap-3 md:flex-row md:items-center md:justify-between'>
                <div className='flex flex-wrap gap-2'>
                  {SUGGESTED_QUESTIONS.slice(0, 4).map((item) => (
                    <button
                      key={item}
                      type='button'
                      className='rounded-md border border-[#BEC0C2]/80 bg-white px-3 py-2 text-left text-xs font-medium text-[#0d2238] transition hover:border-[#F58426] hover:text-[#006BB6]'
                      onClick={() => submit(item)}
                    >
                      {item}
                    </button>
                  ))}
                </div>
                <Button
                  className='bg-[#F58426] text-white hover:bg-[#d96f19]'
                  disabled={analyst.isPending || !question.trim()}
                  onClick={() => submit()}
                >
                  {analyst.isPending ? (
                    <Loader2 className='animate-spin' />
                  ) : (
                    <Search />
                  )}
                  Search archive
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      <section className='mx-auto grid max-w-6xl gap-4 px-4 py-6 md:grid-cols-4 md:px-8'>
        <ArchiveStat
          icon={CalendarDays}
          label='Available games'
          value={games.isLoading ? '...' : String(games.data?.length ?? 0)}
        />
        <ArchiveStat
          icon={Trophy}
          label='Record'
          value={games.isLoading ? '...' : `${summary.wins}-${summary.losses}`}
        />
        <ArchiveStat
          icon={Sparkles}
          label='Event receipts'
          value={games.isLoading ? '...' : String(summary.eventReady)}
        />
        <ArchiveStat
          icon={FileText}
          label='Best margin'
          value={
            summary.biggestWin
              ? `+${summary.biggestWin.margin}`
              : games.isLoading
                ? '...'
                : '-'
          }
        />
      </section>

      <section className='mx-auto grid max-w-6xl gap-6 px-4 pb-12 md:px-8 lg:grid-cols-[1fr_320px]'>
        <div className='space-y-6'>
          {analyst.isPending ? (
            <Card className='border-[#BEC0C2]/70 bg-white'>
              <CardContent className='flex items-center gap-3 p-6 text-sm text-muted-foreground'>
                <Loader2 className='size-4 animate-spin text-[#006BB6]' />
                Searching the season archive...
              </CardContent>
            </Card>
          ) : null}
          {analyst.error ? (
            <Card className='border-[#F58426]/50 bg-white'>
              <CardContent className='p-6 text-sm text-muted-foreground'>
                {navigator.onLine
                  ? 'The archive could not answer that request. It may have timed out or reached a rate limit; try again shortly.'
                  : 'You are offline. Reconnect to search the archive.'}
              </CardContent>
            </Card>
          ) : null}
          {messages.length > 0 ? (
            <div className='space-y-5' aria-live='polite'>
              {messages.map((message) =>
                message.role === 'user' ? (
                  <div
                    key={message.id}
                    className='ml-auto max-w-2xl rounded-lg bg-[#006BB6] px-4 py-3 text-white'
                  >
                    {message.content}
                  </div>
                ) : message.response ? (
                  <AnswerPanel
                    key={message.id}
                    answer={message.response}
                    games={games.data ?? []}
                    onClarification={submit}
                  />
                ) : null
              )}
            </div>
          ) : (
            <Card className='border-[#BEC0C2]/70 bg-white'>
              <CardHeader>
                <CardTitle>Start with a season memory</CardTitle>
                <CardDescription>
                  Pick a prompt or ask your own Knicks question.
                </CardDescription>
              </CardHeader>
              <CardContent className='grid gap-2 sm:grid-cols-2'>
                {SUGGESTED_QUESTIONS.map((item) => (
                  <button
                    key={item}
                    type='button'
                    className='rounded-md border border-[#BEC0C2]/80 bg-[#f7f8fa] p-3 text-left text-sm font-medium transition hover:border-[#F58426] hover:bg-white hover:text-[#006BB6]'
                    onClick={() => submit(item)}
                  >
                    {item}
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        <aside className='space-y-4'>
          <Card className='border-[#BEC0C2]/70 bg-white'>
            <CardHeader>
              <CardTitle className='text-base'>Season receipts</CardTitle>
              <CardDescription>
                Fast reference points from the archive.
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-3 text-sm'>
              {summary.biggestWin ? (
                <ReceiptMini label='Biggest win' game={summary.biggestWin} />
              ) : null}
              {summary.biggestLoss ? (
                <ReceiptMini label='Biggest loss' game={summary.biggestLoss} />
              ) : null}
              {!summary.biggestWin && !summary.biggestLoss ? (
                <p className='text-muted-foreground'>
                  Loading season receipts...
                </p>
              ) : null}
            </CardContent>
          </Card>
        </aside>
      </section>
      <footer className='border-t border-[#BEC0C2]/70 bg-white'>
        <div className='mx-auto grid max-w-6xl gap-6 px-4 py-8 text-sm text-muted-foreground md:grid-cols-2 md:px-8'>
          <div>
            <p className='font-semibold text-[#0d2238]'>About this archive</p>
            <p className='mt-2 leading-6'>
              KnicksIQ is an unofficial fan project and is not affiliated with,
              endorsed by, or sponsored by the New York Knicks or the NBA.
              Tactical claims not supported by the published data are declined.
            </p>
          </div>
          <nav
            aria-label='Policies'
            className='flex flex-wrap content-start gap-4 md:justify-end'
          >
            <a className='underline hover:text-[#006BB6]' href='/privacy.html'>
              Privacy
            </a>
            <a className='underline hover:text-[#006BB6]' href='/terms.html'>
              Terms
            </a>
            <a className='underline hover:text-[#006BB6]' href='/sources.html'>
              Sources
            </a>
            <a className='underline hover:text-[#006BB6]' href='/feedback.html'>
              Feedback
            </a>
          </nav>
        </div>
      </footer>
    </main>
  )
}

function ArchiveStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof CalendarDays
  label: string
  value: string
}) {
  return (
    <Card className='border-[#BEC0C2]/70 bg-white'>
      <CardContent className='flex items-center justify-between p-4'>
        <div>
          <p className='text-xs font-medium tracking-wide text-muted-foreground uppercase'>
            {label}
          </p>
          <p className='mt-1 text-2xl font-semibold text-[#0d2238]'>{value}</p>
        </div>
        <div className='rounded-md bg-[#006BB6]/10 p-2 text-[#006BB6]'>
          <Icon className='size-5' />
        </div>
      </CardContent>
    </Card>
  )
}

function ReceiptMini({ label, game }: { label: string; game: GameSummary }) {
  const score = knicksScore(game)
  return (
    <div className='rounded-md border border-[#BEC0C2]/70 p-3'>
      <div className='flex items-center justify-between gap-2'>
        <span className='font-semibold text-[#0d2238]'>{label}</span>
        <Badge variant={score.won ? 'default' : 'secondary'}>
          {score.won ? '+' : '-'}
          {Math.abs(game.margin)}
        </Badge>
      </div>
      <p className='mt-2 text-xs text-muted-foreground'>
        {formatDate(game.game_date)} - NYK {score.points}, {score.opponent}{' '}
        {score.opponentPoints}
      </p>
    </div>
  )
}
