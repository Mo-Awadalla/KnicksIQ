import type { AnalysisCitation, AnalysisResponse } from '@/types'
import { FileText, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { AnalyticsCards } from './analytics-cards'
import './archive.css'
import { SourceValues } from './source-values'

const supportedAlternatives = [
  'How did the Knicks perform against Boston?',
  'Which games had the wildest swings?',
  'When was the longest losing streak?',
]

function dataLimitation(answer: AnalysisResponse) {
  const coverage = answer.analytics?.coverage
  if (
    coverage &&
    (coverage.completeness < 1 || coverage.missing_game_ids.length > 0)
  ) {
    const through = coverage.data_through
      ? ` through ${coverage.data_through}`
      : ''
    return `Available records cover ${coverage.covered_game_count} of ${coverage.expected_game_count} games${through}.`
  }
  if (
    answer.warnings.some((warning) =>
      /possession-level|play-by-play|coverage|missing game/i.test(warning)
    )
  ) {
    return 'Some details needed for this answer are not available in the archived game records.'
  }
  return 'This archive contains available Knicks 2025-26 regular-season and postseason records; it may not include every game detail, does not include live updates, and cannot establish what caused a result.'
}

function publicWarning(warning: string): string | undefined {
  if (warning === 'ambiguous_reference') {
    return 'I could not tell which game or player you meant.'
  }
  if (/could not be committed/i.test(warning)) {
    return 'This answer was not saved to your conversation.'
  }
  if (/possession-level|play-by-play/i.test(warning)) {
    return 'The available play-by-play records do not include enough detail to support this question.'
  }
  if (
    /incomplete_coverage|coverage limitation|archive coverage/i.test(warning)
  ) {
    return 'Some game records related to this answer may be missing from the available archive.'
  }
  return undefined
}

function ReceiptCard({ citation }: { citation: AnalysisCitation }) {
  return (
    <Card className='archive-receipt'>
      <CardContent className='space-y-3 p-4'>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge className='archive-citation-badge'>
            {(
              {
                verified_claim: 'Verified statistic',
                archive: 'Archive source',
                game: 'Game result',
                report: 'Game report',
                player_stat: 'Player statistics',
                play_by_play: 'Play-by-play',
              } as Record<string, string>
            )[citation.type] ?? citation.type.replace(/_/g, ' ')}
          </Badge>
          <span className='archive-game-title archive-ink-text text-sm font-semibold'>
            {citation.title}
          </span>
        </div>
        <div className='archive-ink-soft-text text-sm leading-6'>
          <SourceValues text={citation.claim} />
        </div>
        {import.meta.env.DEV && (
          <details>
            <summary>Developer diagnostics</summary>
            <pre className='overflow-x-auto text-xs'>
              {JSON.stringify(citation.metadata, null, 2)}
            </pre>
          </details>
        )}
        {citation.source_url ? (
          <a
            className='archive-blue-text text-xs font-medium underline underline-offset-2'
            href={citation.source_url}
            rel='noreferrer'
            target='_blank'
          >
            Source: {citation.source_name ?? 'NBA.com'}
            <span className='sr-only'> (opens in a new tab)</span>
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

export function AnswerPanel({
  answer,
  onClarification,
  disabled,
  showFollowUps = false,
}: {
  answer: AnalysisResponse
  onClarification: (value: string) => void
  disabled: boolean
  showFollowUps?: boolean
}) {
  const declined = answer.refused
  const followUps = declined
    ? answer.follow_up_questions?.length
      ? answer.follow_up_questions
      : supportedAlternatives
    : showFollowUps
      ? (answer.follow_up_questions ?? [])
      : []
  const warnings = answer.warnings
    .map(publicWarning)
    .filter((warning): warning is string => !!warning)

  return (
    <section>
      <Card className='archive-answer'>
        <CardHeader>
          <h3 className='archive-answer-heading' tabIndex={-1}>
            <Sparkles
              className='archive-orange-text size-5'
              aria-hidden='true'
            />
            {declined ? "The archive can't answer that one" : 'Answer'}
          </h3>
        </CardHeader>
        <CardContent>
          {(answer.degraded || answer.llm_validated === false) && !declined ? (
            <p className='archive-degraded'>
              This answer is built from archived game facts because a longer
              summary could not be verified. Review the sources below.
            </p>
          ) : null}
          {warnings.map((warning) => (
            <p className='archive-limitation' key={warning}>
              {warning}
            </p>
          ))}
          <p className='archive-answer-copy'>{answer.answer}</p>
          {declined ? (
            <div className='archive-decline'>
              <h4>What this archive covers</h4>
              <p>
                KnicksIQ covers available 2025-26 Knicks regular-season and
                postseason game records, including scores, player statistics,
                streaks, and game reports. It does not include live scores,
                injury updates, trades, or future events.
              </p>
            </div>
          ) : null}
          <p className='archive-data-note'>
            <strong>Data note:</strong> {dataLimitation(answer)}
          </p>
          {followUps.length > 0 ? (
            <div
              className='archive-follow-ups'
              role='group'
              aria-label={
                declined ? 'Supported questions' : 'Follow-up questions'
              }
            >
              <p>{declined ? 'Try one of these instead' : 'Keep exploring'}</p>
              <div className='flex flex-wrap gap-2'>
                {followUps.map((followUp) => (
                  <Button
                    key={followUp}
                    type='button'
                    variant='outline'
                    disabled={disabled}
                    onClick={() => onClarification(followUp)}
                  >
                    {followUp}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
          {answer.analytics?.clarification ? (
            <fieldset className='mt-4'>
              <legend className='mb-3 text-sm font-semibold'>
                {answer.analytics.clarification.prompt}
              </legend>
              <div className='flex flex-wrap gap-2'>
                {answer.analytics.clarification.choices.map((choice) => (
                  <Button
                    key={choice.id}
                    type='button'
                    variant='outline'
                    disabled={disabled}
                    onClick={() => onClarification(choice.value)}
                  >
                    {choice.label}
                  </Button>
                ))}
              </div>
            </fieldset>
          ) : null}
        </CardContent>
      </Card>

      {answer.analytics && answer.analytics.results.length > 0 ? (
        <AnalyticsCards analytics={answer.analytics} />
      ) : null}

      {!declined || answer.citations.length > 0 ? (
        <details>
          <summary className='archive-receipts-heading cursor-pointer'>
            <FileText className='archive-blue-text size-5' aria-hidden='true' />
            Sources ({answer.citations.length})
          </summary>
          {answer.citations.length > 0 ? (
            <div className='archive-receipt-grid'>
              {answer.citations.map((citation, index) => (
                <ReceiptCard
                  key={`${citation.title}-${index}`}
                  citation={citation}
                />
              ))}
            </div>
          ) : (
            <Card className='archive-receipt'>
              <CardContent className='p-4 text-sm text-muted-foreground'>
                No separate game receipt was returned for this answer.
              </CardContent>
            </Card>
          )}
        </details>
      ) : null}
    </section>
  )
}
