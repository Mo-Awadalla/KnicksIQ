import { useRef } from 'react'
import { ArrowUp, ArrowUpRight, Loader2, SquarePen } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group'
import { Marker, MarkerContent } from '@/components/ui/marker'
import { Message, MessageContent } from '@/components/ui/message'
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { Trace, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace'
import './analyst-chat.css'
import { AnswerPanel } from './answer-panel'
import { MEMORY_NOTE } from './conversation'
import { AppShell, SurfaceState } from './surface-layout'
import { useAnalyst } from './use-analyst'

const quickQuestions = [
  'How did the Knicks perform against Boston?',
  'Which games had the wildest swings?',
  'When was the longest losing streak?',
]

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
  } = useAnalyst({ responseFocus: 'preserve' })
  const input = useRef<HTMLTextAreaElement>(null)
  const form = useRef<HTMLFormElement>(null)

  return (
    <AppShell
      layout='chat'
      title='Season analyst'
      description='Questions, follow-ups, and sources in one thread.'
      actions={
        <div className='analyst-chat-actions'>
          <Badge variant='outline'>2025–26</Badge>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={() => {
              newChat()
              requestAnimationFrame(() => input.current?.focus())
            }}
          >
            <SquarePen data-icon='inline-start' aria-hidden='true' />
            New chat
          </Button>
        </div>
      }
    >
      <section
        className='analyst-chat analyst-thread'
        aria-label='Season conversation'
      >
        <MessageScrollerProvider
          key={messages[0]?.id ?? 'new-conversation'}
          autoScroll={messages.length > 0}
          defaultScrollPosition={messages.length ? 'last-anchor' : 'start'}
        >
          <MessageScroller className='analyst-chat-scroller'>
            <MessageScrollerViewport>
              <MessageScrollerContent
                className='analyst-chat-messages'
                aria-label='Conversation'
                aria-busy={analyst.isPending}
              >
                {!archiveReady && (
                  <MessageScrollerItem messageId='archive-readiness'>
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
                  </MessageScrollerItem>
                )}
                {messages.length === 0 && archiveReady && (
                  <MessageScrollerItem
                    messageId='empty-conversation'
                    className='analyst-chat-empty'
                  >
                    <Empty>
                      <EmptyHeader>
                        <img
                          src='/images/knicksiq-mark-v2.png'
                          alt=''
                          width='48'
                          height='48'
                        />
                        <EmptyTitle>
                          <h2>Talk through the tape.</h2>
                        </EmptyTitle>
                        <EmptyDescription>
                          Ask about a game, a player, or a moment. Your answers
                          and their sources stay together.
                        </EmptyDescription>
                      </EmptyHeader>
                      <EmptyContent aria-label='Suggested analyst questions'>
                        {quickQuestions.map((item) => (
                          <Button
                            key={item}
                            variant='outline'
                            disabled={!archiveReady}
                            onClick={() => {
                              setQuestion(item)
                              input.current?.focus()
                            }}
                          >
                            {item}
                            <ArrowUpRight
                              data-icon='inline-end'
                              aria-hidden='true'
                            />
                          </Button>
                        ))}
                      </EmptyContent>
                    </Empty>
                  </MessageScrollerItem>
                )}
                {messages.map((message, index) => (
                  <MessageScrollerItem
                    key={message.id}
                    messageId={message.id}
                    scrollAnchor={message.role === 'user' && !message.boundary}
                  >
                    {message.boundary ? (
                      <Marker variant='separator' role='status'>
                        <MarkerContent>{message.boundary}</MarkerContent>
                      </Marker>
                    ) : (
                      <Message
                        align={message.role === 'user' ? 'end' : 'start'}
                      >
                        <MessageContent>
                          {message.response ? (
                            <div className='analyst-chat-answer'>
                              <AnswerPanel
                                answer={message.response}
                                onClarification={submit}
                                disabled={!archiveReady || analyst.isPending}
                                showFollowUps={index === messages.length - 1}
                              />
                            </div>
                          ) : (
                            <Bubble align='end' variant='muted'>
                              <BubbleContent className='whitespace-pre-wrap'>
                                {message.content}
                              </BubbleContent>
                            </Bubble>
                          )}
                        </MessageContent>
                      </Message>
                    )}
                  </MessageScrollerItem>
                ))}
                {analyst.isPending && (
                  <MessageScrollerItem messageId='pending-answer'>
                    <Message>
                      <MessageContent>
                        <Trace role='status' aria-label='Analyst activity'>
                          <TraceLine status='running'>
                            <TraceIcon>
                              <Loader2 className='animate-spin' />
                            </TraceIcon>
                            <TraceTitle>Reading the season tape…</TraceTitle>
                          </TraceLine>
                        </Trace>
                      </MessageContent>
                    </Message>
                  </MessageScrollerItem>
                )}
                {analyst.error && (
                  <MessageScrollerItem messageId='turn-error'>
                    <SurfaceState
                      kind='error'
                      message={
                        navigator.onLine
                          ? 'The analyst could not answer that request. Retry shortly if it timed out or reached a rate limit.'
                          : 'You are offline. Reconnect to search the archive.'
                      }
                      onRetry={retryQuestion ? retry : undefined}
                    />
                  </MessageScrollerItem>
                )}
              </MessageScrollerContent>
            </MessageScrollerViewport>
            {messages.length > 0 && (
              <MessageScrollerButton aria-label='Jump to latest' />
            )}
          </MessageScroller>
        </MessageScrollerProvider>

        <div className='analyst-chat-composer'>
          {notice && (
            <p role='status' className='analyst-chat-notice'>
              {notice}
            </p>
          )}
          {retryQuestion && !analyst.error && !analyst.isPending && (
            <Button type='button' variant='outline' onClick={retry}>
              Retry question
            </Button>
          )}
          <form
            ref={form}
            onSubmit={(event) => {
              event.preventDefault()
              submit()
            }}
          >
            <FieldGroup>
              <Field data-disabled={!archiveReady}>
                <FieldLabel htmlFor='analyst-question' className='sr-only'>
                  Ask a season question
                </FieldLabel>
                <InputGroup data-disabled={!archiveReady}>
                  <InputGroupTextarea
                    ref={input}
                    id='analyst-question'
                    disabled={!archiveReady}
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
                        form.current?.requestSubmit()
                      }
                    }}
                    placeholder='Ask about a game, streak, opponent, player, or turning point…'
                    aria-describedby='analyst-question-hint analyst-memory-note'
                    enterKeyHint='send'
                    rows={2}
                  />
                  <InputGroupAddon align='block-end'>
                    <span
                      id='analyst-question-hint'
                      className='analyst-chat-keyboard-hint'
                    >
                      Enter to send · Shift + Enter for a new line
                    </span>
                    <InputGroupButton
                      type='submit'
                      variant='default'
                      size='icon-sm'
                      className='ml-auto size-11'
                      aria-label='Ask archive'
                      disabled={
                        !archiveReady || !question.trim() || analyst.isPending
                      }
                    >
                      <ArrowUp data-icon='inline-start' aria-hidden='true' />
                    </InputGroupButton>
                  </InputGroupAddon>
                </InputGroup>
                <FieldDescription id='analyst-memory-note'>
                  {MEMORY_NOTE}
                </FieldDescription>
              </Field>
            </FieldGroup>
          </form>
        </div>
      </section>
    </AppShell>
  )
}
