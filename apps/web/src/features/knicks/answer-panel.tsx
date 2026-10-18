import type { AnalysisCitation, AnalysisResponse } from '@/types'
import { FileText, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from '@/components/ui/card'
import { AnalyticsCards } from './analytics-cards'
import './archive.css'
import { SourceValues } from './source-values'

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
  return (
    <section>
      <Card className='archive-answer'>
        <CardHeader>
          <h3 className='archive-answer-heading' tabIndex={-1}>
            <Sparkles className='archive-orange-text size-5' />
            Answer
          </h3>
          {answer.warnings.length > 0 ? (
            <CardDescription>{answer.warnings.join(' ')}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent>
          {answer.degraded ? (
            <p className='archive-degraded'>
              Optional AI or search services are degraded. This answer uses the
              deterministic archive fallback.
            </p>
          ) : null}
          <p className='archive-answer-copy'>{answer.answer}</p>
          {showFollowUps && !!answer.follow_up_questions?.length && (
            <div
              className='mt-4 flex flex-wrap gap-2'
              aria-label='Follow-up questions'
            >
              {answer.follow_up_questions.map((followUp) => (
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
          )}
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

      <details>
        <summary className='archive-receipts-heading cursor-pointer'>
          <FileText className='archive-blue-text size-5' />
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
    </section>
  )
}
