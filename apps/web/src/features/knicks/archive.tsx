import { type KeyboardEvent, useEffect, useRef } from 'react'
import { Link } from '@tanstack/react-router'
import type { AnalysisCitation, AnalysisResponse } from '@/types'
import { ArrowUpRight, FileText, Loader2, Search, Sparkles } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from '@/components/ui/card'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import { AnalyticsCards } from './analytics-cards'
import './archive.css'
import './landing.css'
import { useAnalyst } from './use-analyst'

const KNICKS_SEASON = '2025-26'
const SUGGESTED_QUESTIONS = [
  'Who beat the Knicks by the most points?',
  'What was their best win?',
  'When was the longest losing streak?',
  'How many games did the Knicks win?',
  'How did they perform against Boston?',
  'Which games had the wildest swings?',
]

function ReceiptCard({ citation }: { citation: AnalysisCitation }) {
  return (
    <Card className='archive-receipt'>
      <CardContent className='space-y-3 p-4'>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge className='archive-citation-badge'>{citation.type}</Badge>
          <span className='archive-game-title archive-ink-text text-sm font-semibold'>
            {citation.title}
          </span>
        </div>
        <p className='archive-ink-soft-text text-sm leading-6'>
          Supports: {citation.claim}
        </p>
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
}: {
  answer: AnalysisResponse
  onClarification: (value: string) => void
  disabled: boolean
}) {
  return (
    <section>
      <Card className='archive-answer'>
        <CardHeader>
          <h3 className='archive-answer-heading' tabIndex={-1}>
            <Sparkles className='archive-orange-text size-5' />
            {answer.refused ? 'Archive boundary' : 'Answer'}
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

      <div>
        <h3 className='archive-receipts-heading'>
          <FileText className='archive-blue-text size-5' />
          Receipts
        </h3>
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
      </div>
    </section>
  )
}

export function SeasonArchivePage() {
  const {
    question,
    setQuestion,
    messages,
    analyst,
    submit,
    archiveReady,
    archiveFailed,
    archiveChecking,
    slow,
    retryReadiness,
  } = useAnalyst()
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!analyst.isSuccess) return
    const frame = requestAnimationFrame(() => {
      const headings = resultsRef.current?.querySelectorAll<HTMLElement>(
        '.archive-answer-heading'
      )
      headings?.item(headings.length - 1).focus()
    })
    return () => cancelAnimationFrame(frame)
  }, [analyst.isSuccess, messages.length])

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
    <div className='archive-page archive-landing'>
      <a className='landing-skip' href='#archive-desk'>
        Skip to archive search
      </a>
      <header className='landing-header'>
        <div className='archive-shell'>
          <nav className='landing-nav' aria-label='Archive'>
            <Link className='archive-brand' to='/'>
              <span className='archive-brand-mark' aria-hidden='true'>
                <img
                  src='/images/knicksiq-mark-v2.png'
                  alt=''
                  width='256'
                  height='256'
                />
              </span>
              <span className='archive-brand-name'>KnicksIQ</span>
            </Link>
            <div className='landing-nav-links'>
              <Link to='/' aria-current='page'>
                Archive
              </Link>
              <Link to='/games'>Games</Link>
              <Link to='/reports'>Reports</Link>
              <Link to='/analyst'>
                Analyst <ArrowUpRight aria-hidden='true' />
              </Link>
            </div>
            <span className='landing-edition'>NEW YORK · 2025–26</span>
          </nav>
        </div>
      </header>
      <main>
        <section
          className='landing-hero archive-shell'
          aria-labelledby='landing-title'
        >
          <div className='landing-issue'>
            <span>The Knicks season archive</span>
            <span>Regular season & postseason</span>
          </div>
          <div className='landing-headline-row'>
            <h1 id='landing-title' className='landing-title'>
              <span className='sr-only'>
                {KNICKS_SEASON} Knicks season archive:{' '}
              </span>
              THE SEASON.
              <br />
              <em>STILL ALIVE.</em>
            </h1>
            <div className='landing-intro'>
              <p>
                The nights you remember. <br />
                The details you don’t.
              </p>
              <p>
                Revisit the {KNICKS_SEASON} Knicks through the games, the
                turning points, and the evidence behind every answer.
              </p>
              <Button asChild size='lg' className='landing-primary'>
                <a href='#archive-desk'>
                  Ask the archive{' '}
                  <ArrowUpRight aria-hidden='true' data-icon='inline-end' />
                </a>
              </Button>
            </div>
          </div>
          <figure className='landing-photo'>
            <picture>
              <source
                srcSet='/images/madison-square-garden-arena.webp'
                type='image/webp'
              />
              <img
                src='/images/madison-square-garden-arena.jpg'
                alt='Madison Square Garden basketball court before the crowd arrives'
                width='1600'
                height='2400'
                fetchPriority='high'
              />
            </picture>
            <div className='landing-photo-title' aria-hidden='true'>
              HOME COURT.
              <br />
              <span>EVERY CHAPTER.</span>
            </div>
            <figcaption>
              <span>Madison Square Garden · New York, NY</span>
              <a
                href='https://unsplash.com/photos/eEnokNtvnoo'
                rel='noreferrer'
                target='_blank'
              >
                Photo: With Paul
                <span className='sr-only'> (opens in a new tab)</span>
              </a>
            </figcaption>
          </figure>
          <div className='landing-index' aria-label='Explore the archive'>
            <Link to='/games'>
              <span>Inside the games</span>
              <strong>Box scores & play-by-play</strong>
              <ArrowUpRight aria-hidden='true' />
            </Link>
            <Link to='/reports'>
              <span>Beyond the final score</span>
              <strong>Reviewed game reports</strong>
              <ArrowUpRight aria-hidden='true' />
            </Link>
            <a href='/sources.html'>
              <span>Follow the evidence</span>
              <strong>Sources you can check</strong>
              <ArrowUpRight aria-hidden='true' />
            </a>
          </div>
        </section>

        <section
          id='archive-desk'
          className='landing-desk'
          aria-labelledby='desk-title'
          tabIndex={-1}
        >
          <div className='archive-shell landing-desk-grid'>
            <div className='landing-desk-intro'>
              <h2 id='desk-title'>
                LET’S TALK
                <br />
                <em>KNICKS.</em>
              </h2>
              <p>
                A game you can’t forget. A streak you can’t explain. Start with
                a question. Follow it back to the court.
              </p>
              <span className='landing-desk-note'>
                2025–26 SEASON ARCHIVE <ArrowUpRight aria-hidden='true' />
              </span>
            </div>
            <form
              className='archive-console'
              aria-labelledby='ask-title'
              aria-busy={archiveChecking}
              onSubmit={(event) => {
                event.preventDefault()
                submit()
              }}
            >
              <FieldGroup>
                <Field data-disabled={!archiveReady || analyst.isPending}>
                  <div className='archive-console-heading'>
                    <div>
                      <FieldLabel
                        className='archive-console-label'
                        htmlFor='archive-question'
                      >
                        Ask the archive
                      </FieldLabel>
                      <h3 id='ask-title'>What do you remember?</h3>
                    </div>
                    {archiveReady ? (
                      <p className='archive-console-hint'>
                        Enter to search · Shift + Enter for a new line
                      </p>
                    ) : (
                      <div
                        id='archive-readiness'
                        className='archive-console-readiness'
                        role={archiveFailed ? 'alert' : 'status'}
                        aria-live='polite'
                      >
                        {archiveFailed ? (
                          <>
                            <span>Archive unavailable</span>
                            <button
                              type='button'
                              onClick={() => {
                                retryReadiness()
                              }}
                            >
                              Try again
                            </button>
                          </>
                        ) : (
                          <>
                            <Loader2
                              className='size-3.5 animate-spin'
                              aria-hidden='true'
                            />
                            {slow
                              ? 'The archive is starting slowly. Please wait…'
                              : 'Preparing archive'}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <fieldset
                    className='archive-console-controls'
                    disabled={!archiveReady || analyst.isPending}
                    aria-describedby={
                      !archiveReady ? 'archive-readiness' : undefined
                    }
                  >
                    <Textarea
                      id='archive-question'
                      value={question}
                      maxLength={1200}
                      rows={3}
                      enterKeyHint='search'
                      onChange={(event) => setQuestion(event.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder='Ask about a game, streak, opponent, player, or turning point…'
                      className='archive-textarea'
                    />
                    <div className='archive-console-actions'>
                      <div
                        className='archive-quick-prompts'
                        aria-label='Quick questions'
                      >
                        {SUGGESTED_QUESTIONS.slice(0, 2).map((item) => (
                          <button
                            key={item}
                            type='button'
                            className='archive-prompt'
                            disabled={analyst.isPending}
                            onClick={() => submit(item)}
                          >
                            {item}
                          </button>
                        ))}
                      </div>
                      <Button
                        type='submit'
                        variant='archive'
                        className='landing-search-button'
                        disabled={analyst.isPending || !question.trim()}
                      >
                        {analyst.isPending ? (
                          <Loader2
                            className='animate-spin'
                            aria-hidden='true'
                            data-icon='inline-start'
                          />
                        ) : (
                          <Search aria-hidden='true' data-icon='inline-start' />
                        )}
                        Search archive
                      </Button>
                    </div>
                  </fieldset>
                </Field>
              </FieldGroup>
            </form>
          </div>
        </section>

        <section
          className='archive-shell archive-workspace'
          aria-labelledby='workspace-title'
        >
          <div>
            <header className='archive-workspace-heading'>
              <h2 id='workspace-title'>
                {messages.length
                  ? 'The story. With receipts.'
                  : 'THERE’S A GAME FOR THAT.'}
              </h2>
              <p>
                Explore the season in plain language. KnicksIQ keeps the answer,
                the underlying games, and any data limitations in the same view.
              </p>
            </header>

            <div
              ref={resultsRef}
              className='archive-result-stack'
              aria-busy={analyst.isPending}
            >
              <span className='sr-only' role='status' aria-live='polite'>
                {analyst.isSuccess ? 'Answer ready. Review it below.' : ''}
              </span>
              {analyst.isPending ? (
                <div className='archive-state' role='status'>
                  <Loader2
                    className='archive-blue-text size-4 animate-spin'
                    aria-hidden='true'
                  />
                  Searching the season archive…
                </div>
              ) : null}
              {analyst.error ? (
                <Alert variant='destructive'>
                  <AlertTitle>That question couldn’t be answered.</AlertTitle>
                  <AlertDescription>
                    {navigator.onLine
                      ? 'The archive could not answer that request. It may have timed out or reached a rate limit; try again shortly.'
                      : 'You are offline. Reconnect to search the archive.'}
                    <Button
                      disabled={!archiveReady || analyst.isPending}
                      onClick={() =>
                        analyst.variables && analyst.mutate(analyst.variables)
                      }
                    >
                      Retry question
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : null}
              {messages.length > 0 ? (
                <ol className='archive-message-list'>
                  {messages.map((message) =>
                    message.role === 'user' ? (
                      <li key={message.id}>
                        <p className='archive-question'>
                          <span className='sr-only'>You asked: </span>
                          {message.content}
                        </p>
                      </li>
                    ) : message.response ? (
                      <li key={message.id}>
                        <AnswerPanel
                          answer={message.response}
                          onClarification={submit}
                          disabled={analyst.isPending}
                        />
                      </li>
                    ) : null
                  )}
                </ol>
              ) : (
                <section
                  className='archive-empty'
                  aria-label='Suggested season questions'
                >
                  <div className='archive-prompt-grid'>
                    {SUGGESTED_QUESTIONS.map((item, index) => (
                      <button
                        key={item}
                        type='button'
                        className='archive-prompt-row'
                        disabled={!archiveReady || analyst.isPending}
                        onClick={() => submit(item)}
                      >
                        <span>
                          <small className='landing-question-topic'>
                            {
                              [
                                'The tough nights',
                                'The statement wins',
                                'The rough stretches',
                                'The big picture',
                                'The rivalries',
                                'The turning points',
                              ][index]
                            }
                          </small>
                          {item}
                        </span>
                        <ArrowUpRight aria-hidden='true' />
                      </button>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </div>
        </section>
        <section
          className='landing-method archive-shell'
          aria-labelledby='method-title'
        >
          <div>
            <h2 id='method-title'>
              GOOD QUESTIONS.
              <br />
              CHECKABLE ANSWERS.
            </h2>
            <a href='/sources.html'>
              How we use sources <ArrowUpRight aria-hidden='true' />
            </a>
          </div>
          <dl>
            <div>
              <dt>The answer comes first.</dt>
              <dd>
                Plain-language answers to your season questions, with the key
                evidence close by.
              </dd>
            </div>
            <div>
              <dt>The games tell the story.</dt>
              <dd>
                Follow available receipts into box scores, play-by-play, and
                reviewed reports.
              </dd>
            </div>
            <div>
              <dt>The limits stay visible.</dt>
              <dd>
                When the archive can’t support a claim, the answer should say
                so. There’s always room for a better question.
              </dd>
            </div>
          </dl>
        </section>
      </main>

      <footer className='archive-footer'>
        <div className='archive-shell landing-footer-masthead'>
          <span>
            KNICKSIQ<span className='landing-period'>.</span>
          </span>
          <p>
            For the fans who
            <br />
            remember the details.
          </p>
        </div>
        <div className='archive-shell archive-footer-inner'>
          <div>
            <strong>About this archive</strong>
            <p>
              KnicksIQ is an unofficial fan project and is not affiliated with,
              endorsed by, or sponsored by the New York Knicks or the NBA. Arena
              photograph by{' '}
              <a
                href='https://unsplash.com/photos/eEnokNtvnoo'
                rel='noreferrer'
                target='_blank'
              >
                With Paul on Unsplash
              </a>
              .
            </p>
          </div>
          <nav aria-label='Policies' className='archive-footer-nav'>
            <a href='/privacy.html'>Privacy</a>
            <a href='/terms.html'>Terms</a>
            <a href='/sources.html'>Sources</a>
            <a href='/feedback.html'>Feedback</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
