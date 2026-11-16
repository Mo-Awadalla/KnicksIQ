import { z } from 'zod'

import {
  type Command,
  type Snapshot,
  type View,
  accept,
  append,
  emptySnapshot,
} from './domain'
import { ChatFailure, cancel, current, turn } from './transport'

const storageKey = 'knicksiq-chat-v1'
const commandSchema = z.discriminatedUnion('kind', [
  z
    .object({
      kind: z.literal('message'),
      request_id: z.string().uuid(),
      expected_revision: z.number().int().nonnegative(),
      message: z.string().min(1).max(1200),
    })
    .strict(),
  z
    .object({
      kind: z.literal('retry'),
      request_id: z.string().uuid(),
      expected_revision: z.number().int().nonnegative(),
      exchange_id: z.string().uuid(),
    })
    .strict(),
])
const savedSchema = z
  .object({
    token: z
      .string()
      .regex(/^[a-f0-9]{64}$/)
      .nullable(),
    pending: commandSchema.nullable(),
    draft: z.string().max(1200),
    unsent: z.string().min(1).max(1200).nullable().default(null),
    known: z.boolean().default(false),
    closed: z.literal('full').nullable().default(null),
  })
  .strict()
type Saved = z.infer<typeof savedSchema>
const fresh = (): Saved => ({
  token: null,
  pending: null,
  draft: '',
  unsent: null,
  known: false,
  closed: null,
})

export class Conversation {
  private saved: Saved = fresh()
  private view: View = {
    snapshot: emptySnapshot(),
    draft: '',
    lifecycle: 'ready',
    notice: '',
    submission: null,
  }
  private listeners = new Set<() => void>()
  private epoch = 0
  private stream: AbortController | null = null
  private poll: number | undefined

  constructor() {
    try {
      const stored = sessionStorage.getItem(storageKey)
      if (stored) this.saved = savedSchema.parse(JSON.parse(stored))
      this.update({ draft: this.saved.draft })
      if (this.saved.token) {
        this.view = { ...this.view, lifecycle: 'restoring' }
        void this.reconcile()
      }
    } catch {
      this.view = {
        ...this.view,
        lifecycle: 'unknown',
        notice:
          'Your saved chat could not be restored. Start a new chat to continue.',
      }
    }
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  getSnapshot = () => this.view
  private update(change: Partial<View>) {
    const snapshot = change.snapshot ?? this.view.snapshot
    const pending = this.saved.pending
    const message =
      pending?.kind === 'message' &&
      !snapshot.exchanges.some((exchange) => exchange.id === pending.request_id)
        ? pending.message
        : null
    this.view = {
      ...this.view,
      ...change,
      submission: message
        ? { message, status: 'unconfirmed' }
        : this.saved.unsent
          ? { message: this.saved.unsent, status: 'unsent' }
          : null,
    }
    for (const listener of this.listeners) listener()
  }
  private persist(): boolean {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(this.saved))
      return true
    } catch {
      this.update({
        lifecycle: 'unknown',
        notice:
          'This tab cannot save your chat. Enable browser storage, then start a new chat.',
      })
      return false
    }
  }
  setDraft = (draft: string) => {
    this.saved = { ...this.saved, draft: draft.slice(0, 1200) }
    this.update({ draft: this.saved.draft })
    this.persist()
  }
  private canonical(snapshot: Snapshot) {
    if (snapshot.revision < this.view.snapshot.revision) return
    const pending = this.saved.pending
    const absent =
      pending?.kind === 'message' &&
      !snapshot.exchanges.some((exchange) => exchange.id === pending.request_id)
    this.saved = {
      ...this.saved,
      pending: null,
      known: this.saved.known || snapshot.exchanges.length > 0,
      unsent: absent ? pending.message : this.saved.unsent,
    }
    if (!this.persist()) return
    const writing = snapshot.exchanges.some(
      (exchange) => exchange.reply.status === 'writing'
    )
    this.update({
      snapshot,
      lifecycle: writing ? 'writing' : (this.saved.closed ?? 'ready'),
      notice:
        this.saved.closed === 'full'
          ? 'This chat is full. Start a new chat to keep talking. Your unsent message is saved.'
          : this.saved.unsent
            ? 'Your message was not sent. Review the saved chat, then send the unsent message when ready.'
            : '',
    })
    if (writing) this.scheduleRead()
  }
  private scheduleRead() {
    window.clearTimeout(this.poll)
    this.poll = window.setTimeout(() => {
      this.poll = undefined
      void this.reconcile()
    }, 1200)
  }
  reconcile = async () => {
    const { token } = this.saved
    if (!token) return
    const epoch = this.epoch
    try {
      const snapshot = await current(token)
      if (epoch !== this.epoch) return
      if (
        snapshot.exchanges.length === 0 &&
        (this.saved.known || (this.saved.pending?.expected_revision ?? 0) > 0)
      )
        throw new ChatFailure('expired')
      this.canonical(snapshot)
    } catch (error) {
      if (epoch !== this.epoch) return
      const expired = error instanceof ChatFailure && error.kind === 'expired'
      if (expired) {
        const pending = this.saved.pending
        this.saved = {
          ...this.saved,
          known: true,
          pending: null,
          unsent:
            pending?.kind === 'message' ? pending.message : this.saved.unsent,
        }
        if (!this.persist()) return
      }
      this.update({
        ...(expired ? { snapshot: emptySnapshot() } : {}),
        lifecycle: expired ? 'expired' : 'unknown',
        notice: expired
          ? 'This chat has expired or is no longer available. Start a new chat.'
          : 'We could not confirm your reply. Check connection to recover it. Nothing will be sent again automatically.',
      })
    }
  }
  send = () => {
    const message = this.saved.draft.trim()
    if (!message || this.saved.unsent || this.view.lifecycle !== 'ready') return
    this.begin({
      kind: 'message',
      request_id: crypto.randomUUID(),
      expected_revision: this.view.snapshot.revision,
      message,
    })
  }
  sendUnsent = () => {
    const message = this.saved.unsent
    if (!message || this.view.lifecycle !== 'ready') return
    this.begin(
      {
        kind: 'message',
        request_id: crypto.randomUUID(),
        expected_revision: this.view.snapshot.revision,
        message,
      },
      true
    )
  }
  retry = (exchangeId: string) => {
    if (this.view.lifecycle !== 'ready') return
    const exchange = this.view.snapshot.exchanges.find(
      (item) => item.id === exchangeId
    )
    if (
      !exchange ||
      !['stopped', 'interrupted'].includes(exchange.reply.status)
    )
      return
    this.begin({
      kind: 'retry',
      request_id: crypto.randomUUID(),
      expected_revision: this.view.snapshot.revision,
      exchange_id: exchangeId,
    })
  }
  private begin(command: Command, fromOutbox = false) {
    let token = this.saved.token
    if (!token)
      token = Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) =>
        byte.toString(16).padStart(2, '0')
      ).join('')
    this.saved = {
      ...this.saved,
      token,
      pending: command,
      draft: command.kind === 'message' && !fromOutbox ? '' : this.saved.draft,
      unsent: fromOutbox ? null : this.saved.unsent,
    }
    if (!this.persist()) return
    this.update({ lifecycle: 'sending', draft: this.saved.draft, notice: '' })
    const abort = new AbortController()
    this.stream = abort
    void this.deliver(token, command, this.epoch, abort)
  }
  private async deliver(
    token: string,
    command: Command,
    epoch: number,
    abort: AbortController
  ) {
    let accepted = false
    let settled = false
    try {
      await turn(
        token,
        command,
        AbortSignal.any([abort.signal, AbortSignal.timeout(100_000)]),
        (event) => {
          if (epoch !== this.epoch || this.stream !== abort) return
          switch (event.kind) {
            case 'accepted':
              if (
                accepted ||
                event.exchange_id !==
                  (command.kind === 'message'
                    ? command.request_id
                    : command.exchange_id)
              )
                throw new ChatFailure('unknown')
              accepted = true
              this.saved = { ...this.saved, known: true }
              if (!this.persist()) throw new ChatFailure('unknown')
              this.update({
                snapshot: accept(
                  this.view.snapshot,
                  command,
                  event.exchange_id,
                  event.revision
                ),
                lifecycle: 'writing',
              })
              break
            case 'checking':
              if (!accepted) throw new ChatFailure('unknown')
              this.update({ lifecycle: 'checking' })
              break
            case 'delta':
              if (!accepted) throw new ChatFailure('unknown')
              if (
                (this.view.snapshot.exchanges.find(
                  (item) => item.reply.id === event.request_id
                )?.reply.text.length ?? 0) +
                  event.text.length >
                32_000
              )
                throw new ChatFailure('unknown')
              this.update({
                snapshot: append(
                  this.view.snapshot,
                  event.request_id,
                  event.text
                ),
                lifecycle: 'writing',
              })
              break
            case 'settled':
              settled = true
              this.canonical(event.snapshot)
              break
            case 'recovery':
              this.update({
                lifecycle: 'unknown',
                notice:
                  'We could not confirm your reply. Checking the saved chat.',
              })
              break
          }
        }
      )
    } catch (error) {
      if (epoch !== this.epoch || this.stream !== abort) return
      if (
        !accepted &&
        error instanceof ChatFailure &&
        ['full', 'rate_limited', 'invalid'].includes(error.kind)
      ) {
        settled = true
        this.saved = {
          ...this.saved,
          pending: null,
          token: this.view.snapshot.exchanges.length ? token : null,
          closed: error.kind === 'full' ? 'full' : this.saved.closed,
          unsent:
            command.kind === 'message' ? command.message : this.saved.unsent,
        }
        if (!this.persist()) return
        this.update({
          lifecycle: error.kind === 'full' ? 'full' : 'ready',
          draft: this.saved.draft,
          notice:
            error.kind === 'full'
              ? 'This chat is full. Start a new chat to keep talking.'
              : error.kind === 'rate_limited'
                ? 'Too many messages just now. Wait a moment, then send again.'
                : 'That message could not be sent. Keep it under 1,200 characters and try again.',
        })
      }
    } finally {
      if (epoch === this.epoch && this.stream === abort) {
        this.stream = null
        if (!settled) await this.reconcile()
      }
    }
  }
  stop = async () => {
    const { token, pending } = this.saved
    const writing = this.view.snapshot.exchanges.find(
      (exchange) => exchange.reply.status === 'writing'
    )
    const attempt = writing?.reply.id ?? pending?.request_id
    if (!token || !attempt || this.view.lifecycle === 'stopping') return
    const epoch = this.epoch
    const stream = this.stream
    this.update({ lifecycle: 'stopping', notice: 'Stopping reply…' })
    try {
      const snapshot = await cancel(token, attempt, this.view.snapshot.revision)
      if (epoch !== this.epoch) return
      this.stream = null
      stream?.abort()
      this.canonical(snapshot)
    } catch {
      if (epoch === this.epoch) {
        this.stream = null
        stream?.abort()
        await this.reconcile()
      }
    }
  }
  newChat = () => {
    this.epoch += 1
    const { token, pending } = this.saved
    const writing = this.view.snapshot.exchanges.find(
      (exchange) => exchange.reply.status === 'writing'
    )
    const attempt = writing?.reply.id ?? pending?.request_id
    const revision = this.view.snapshot.revision
    window.clearTimeout(this.poll)
    this.poll = undefined
    this.stream?.abort()
    this.stream = null
    const recover = ['expired', 'full'].includes(this.view.lifecycle)
    this.saved = {
      ...fresh(),
      draft: recover ? this.saved.draft : '',
      unsent: recover ? this.saved.unsent : null,
    }
    this.update({
      snapshot: emptySnapshot(),
      draft: this.saved.draft,
      lifecycle: 'ready',
      notice: this.saved.unsent
        ? 'Your unsent message is saved. Send it when ready.'
        : '',
    })
    this.persist()
    if (token && attempt) void cancel(token, attempt, revision).catch(() => {})
  }
}
