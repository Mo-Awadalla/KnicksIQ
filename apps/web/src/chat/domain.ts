export type Interruption =
  | 'disconnected'
  | 'expired'
  | 'unavailable'
  | 'budget'
  | 'deadline'
  | 'incomplete'
export type Reply =
  | { status: 'writing' | 'complete' | 'stopped'; id: string; text: string }
  | { status: 'interrupted'; id: string; text: string; reason: Interruption }
export type Exchange = { id: string; message: string; reply: Reply }
export type Snapshot = { revision: number; exchanges: Exchange[] }
export type Command = { request_id: string; expected_revision: number } & (
  | { kind: 'message'; message: string }
  | { kind: 'retry'; exchange_id: string }
)
export type ChatEvent =
  | {
      kind: 'accepted'
      request_id: string
      exchange_id: string
      revision: number
    }
  | { kind: 'checking'; request_id: string }
  | { kind: 'delta'; request_id: string; text: string }
  | { kind: 'settled'; request_id: string; snapshot: Snapshot }
  | {
      kind: 'recovery'
      request_id: string
      code: 'outcome_unknown' | 'fenced'
      retryable: false
    }
export type Lifecycle =
  | 'ready'
  | 'restoring'
  | 'sending'
  | 'writing'
  | 'checking'
  | 'stopping'
  | 'unknown'
  | 'expired'
  | 'full'
export type View = {
  snapshot: Snapshot
  draft: string
  lifecycle: Lifecycle
  notice: string
  submission: { message: string; status: 'unconfirmed' | 'unsent' } | null
}
export const emptySnapshot = (): Snapshot => ({ revision: 0, exchanges: [] })

export function accept(
  snapshot: Snapshot,
  command: Command,
  exchangeId: string,
  revision: number
): Snapshot {
  const reply: Reply = { id: command.request_id, text: '', status: 'writing' }
  const exchanges =
    command.kind === 'message'
      ? [
          ...snapshot.exchanges,
          { id: exchangeId, message: command.message, reply },
        ]
      : snapshot.exchanges.map((exchange) =>
          exchange.id === exchangeId ? { ...exchange, reply } : exchange
        )
  return { revision, exchanges }
}
export function append(
  snapshot: Snapshot,
  attempt: string,
  text: string
): Snapshot {
  return {
    ...snapshot,
    exchanges: snapshot.exchanges.map((exchange) =>
      exchange.reply.id === attempt && exchange.reply.status === 'writing'
        ? {
            ...exchange,
            reply: { ...exchange.reply, text: exchange.reply.text + text },
          }
        : exchange
    ),
  }
}
