import { useRef, useState, useSyncExternalStore } from 'react'

import { Button } from '@ui-sdk/react/button'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@ui-sdk/react/menu'
import {
  ScrollArea,
  ScrollAreaContent,
  ScrollAreaScrollToEnd,
  ScrollAreaViewport,
} from '@ui-sdk/react/scroll-area'
import { Textarea } from '@ui-sdk/react/textarea'
import { ArrowDown, ArrowUp, MoreHorizontal, Plus, Square } from 'lucide-react'

import type { Conversation } from './controller'

const starters = [
  'Were we really contenders?',
  'Give me your most unpopular Knicks take',
  'Quiz me on the season',
]

export function Chat({ conversation }: { conversation: Conversation }) {
  const view = useSyncExternalStore(
    conversation.subscribe,
    conversation.getSnapshot
  )
  const composer = useRef<HTMLTextAreaElement>(null)
  const [scrollKey, setScrollKey] = useState(0)
  const busy = ['sending', 'writing', 'checking', 'stopping'].includes(
    view.lifecycle
  )
  const canSend =
    view.lifecycle === 'ready' && !view.submission && Boolean(view.draft.trim())
  const status =
    view.notice ||
    {
      sending: 'Starting reply…',
      writing: 'Replying…',
      checking: 'Checking a detail…',
      stopping: 'Stopping reply…',
      restoring: 'Restoring this tab’s chat…',
      ready: '',
      unknown: '',
      expired: '',
      full: '',
    }[view.lifecycle]
  function send() {
    conversation.send()
    composer.current?.focus({ preventScroll: true })
  }
  function newChat() {
    conversation.newChat()
    setScrollKey((key) => key + 1)
    composer.current?.focus({ preventScroll: true })
  }
  return (
    <main className='chat-shell'>
      <header className='chat-header'>
        <div className='brand'>
          <span className='brand-mark' aria-hidden='true'>
            <img
              src='/images/knicksiq-mark-v2.png'
              alt=''
              width='256'
              height='256'
            />
          </span>
          <span>KnicksIQ</span>
        </div>
        <div className='header-actions'>
          <Button className='quiet-button' onClick={newChat}>
            <Plus aria-hidden='true' size={17} />
            New chat
          </Button>
          <Menu>
            <MenuTrigger className='icon-button' aria-label='More options'>
              <MoreHorizontal aria-hidden='true' size={21} />
            </MenuTrigger>
            <MenuContent
              className='utility-menu'
              side='bottom'
              align='end'
              sideOffset={6}
            >
              <MenuItem render={<a href='/privacy.html' />}>Privacy</MenuItem>
              <MenuItem render={<a href='/terms.html' />}>Terms</MenuItem>
              <MenuItem render={<a href='/feedback.html' />}>Feedback</MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </header>
      <ScrollArea className='transcript' stickToEnd key={scrollKey}>
        <ScrollAreaViewport
          className='transcript-viewport'
          role='region'
          aria-label='Conversation'
        >
          <ScrollAreaContent className='transcript-content'>
            {view.snapshot.exchanges.length === 0 &&
              view.lifecycle === 'ready' && (
                <section
                  className='empty-chat'
                  aria-label='Start a conversation'
                >
                  <h1>All Knicks. What’s your take?</h1>
                  <p>The 2025–26 season, the arguments, the what-ifs.</p>
                  <div className='starters'>
                    {starters.map((starter) => (
                      <Button
                        key={starter}
                        className='starter'
                        onClick={() => {
                          conversation.setDraft(starter)
                          composer.current?.focus()
                        }}
                      >
                        {starter}
                        <ArrowUp aria-hidden='true' size={15} />
                      </Button>
                    ))}
                  </div>
                </section>
              )}
            {view.snapshot.exchanges.map((exchange) => (
              <section
                className='exchange'
                key={exchange.id}
                aria-label='Chat exchange'
              >
                <div className='user-message'>
                  <span className='sr-only'>You. </span>
                  {exchange.message}
                </div>
                <div className='assistant-message'>
                  <span className='sr-only'>KnicksIQ. </span>
                  {exchange.reply.text}
                </div>
                {exchange.reply.status === 'stopped' && (
                  <p className='reply-note'>Reply stopped.</p>
                )}
                {exchange.reply.status === 'interrupted' && (
                  <p className='reply-note'>
                    Reply interrupted. You can try again.
                  </p>
                )}
                {['stopped', 'interrupted'].includes(exchange.reply.status) &&
                  exchange.id ===
                    view.snapshot.exchanges[view.snapshot.exchanges.length - 1]
                      ?.id &&
                  view.lifecycle === 'ready' && (
                    <Button
                      className='retry-button'
                      onClick={() => conversation.retry(exchange.id)}
                    >
                      Retry reply
                    </Button>
                  )}
              </section>
            ))}
            {view.submission && (
              <section
                className='reply-note'
                role='region'
                aria-label='Unsent message'
              >
                <p>{view.submission.message}</p>
                <p>
                  {view.submission.status === 'unconfirmed'
                    ? 'Confirming whether this message was sent. Nothing will be sent again automatically.'
                    : 'Not sent. Your next draft stays separate.'}
                </p>
                {view.submission.status === 'unsent' &&
                  view.lifecycle === 'ready' && (
                    <Button
                      className='recovery-button'
                      onClick={conversation.sendUnsent}
                    >
                      Send unsent message
                    </Button>
                  )}
              </section>
            )}
          </ScrollAreaContent>
        </ScrollAreaViewport>
        <ScrollAreaScrollToEnd className='jump-button'>
          <ArrowDown aria-hidden='true' size={16} />
          Jump to latest
        </ScrollAreaScrollToEnd>
      </ScrollArea>
      <footer className='composer-dock'>
        <div
          className='status-line'
          role='status'
          aria-live='polite'
          aria-atomic='true'
        >
          {status}
        </div>
        {view.lifecycle === 'unknown' && (
          <Button className='recovery-button' onClick={conversation.reconcile}>
            Check connection
          </Button>
        )}
        <form
          className='composer'
          onSubmit={(event) => {
            event.preventDefault()
            if (canSend) send()
          }}
        >
          <Textarea
            ref={composer}
            aria-label='Message KnicksIQ'
            placeholder='Talk Knicks…'
            value={view.draft}
            onValueChange={conversation.setDraft}
            autoResize
            rows={1}
            maxLength={1200}
            submitShortcut='enter'
          />
          {busy ? (
            <Button
              className='send-button stop-button'
              aria-label='Stop reply'
              disabled={view.lifecycle === 'stopping'}
              onClick={conversation.stop}
            >
              <Square aria-hidden='true' size={16} fill='currentColor' />
            </Button>
          ) : (
            <Button
              type='submit'
              className='send-button'
              aria-label='Send message'
              disabled={!canSend}
            >
              <ArrowUp aria-hidden='true' size={20} />
            </Button>
          )}
        </form>
        <p className='composer-note'>
          A Knicks conversation, not a live news feed.
        </p>
      </footer>
    </main>
  )
}
