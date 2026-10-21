import { useMemo } from 'react'
import {
  ArrowUpRight,
  BarChart3,
  Loader2,
  MessageSquareText,
  Search,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { AnswerPanel } from './answer-panel'
import { MEMORY_NOTE } from './conversation'
import { AppShell, QuestionProgress, SurfaceState } from './surface-layout'
import { useAnalyst } from './use-analyst'

const SEASON = '2025-26'

export function AnalystPage() {
  const {
    question,
    setQuestion,
    messages,
    analyst,
    submit,
    retry,
    retryQuestion,
    newChat,
    notice,
    archiveReady,
    archiveFailed,
    slow,
    retryReadiness,
    cancel,
    elapsedSeconds,
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
            <div className='mb-3 flex flex-wrap items-center justify-between gap-2'>
              <p className='text-sm text-muted-foreground'>{MEMORY_NOTE}</p>
              <Button
                type='button'
                variant='outline'
                onClick={() => {
                  newChat()
                  requestAnimationFrame(() =>
                    document.getElementById('analyst-question')?.focus()
                  )
                }}
              >
                New chat
              </Button>
            </div>
            {notice && (
              <p role='status' className='mb-3 text-sm'>
                {notice}
              </p>
            )}
            {retryQuestion && !analyst.error && !analyst.isPending && (
              <Button type='button' variant='outline' onClick={retry}>
                Retry question
              </Button>
            )}
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
        <div className='analyst-thread'>
          {analyst.error ? (
            <SurfaceState
              kind='error'
              message={analyst.error}
              onRetry={retryQuestion ? retry : undefined}
            />
          ) : null}
          {analyst.isPending ? (
            <QuestionProgress
              elapsedSeconds={elapsedSeconds}
              onCancel={() => {
                cancel()
                requestAnimationFrame(() =>
                  document.getElementById('analyst-question')?.focus()
                )
              }}
            />
          ) : null}
          <div className='analyst-thread-content' aria-busy={analyst.isPending}>
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
            {messages.map((message, index) => (
              <div key={message.id}>
                {message.boundary ? (
                  <p role='status' className='archive-boundary'>
                    {message.boundary}
                  </p>
                ) : message.response ? (
                  <AnswerPanel
                    answer={message.response}
                    onClarification={submit}
                    disabled={!archiveReady || analyst.isPending}
                    showFollowUps={index === messages.length - 1}
                  />
                ) : (
                  <p className='archive-question'>{message.content}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </AppShell>
  )
}
