import { z } from 'zod'

import type { ChatEvent, Command, Snapshot } from './domain'

const id = z.string().uuid()
const text = z.string().max(32_000)
const reason = z.enum([
  'disconnected',
  'expired',
  'unavailable',
  'budget',
  'deadline',
  'incomplete',
])
const reply = z.discriminatedUnion('status', [
  z
    .object({ status: z.enum(['writing', 'complete', 'stopped']), id, text })
    .strict(),
  z.object({ status: z.literal('interrupted'), id, text, reason }).strict(),
])
const snapshotSchema = z
  .object({
    revision: z.number().int().nonnegative(),
    exchanges: z
      .array(z.object({ id, message: z.string().max(1200), reply }).strict())
      .max(40),
  })
  .strict()
const eventSchema = z.discriminatedUnion('kind', [
  z
    .object({
      kind: z.literal('accepted'),
      request_id: id,
      exchange_id: id,
      revision: z.number().int().nonnegative(),
    })
    .strict(),
  z.object({ kind: z.literal('checking'), request_id: id }).strict(),
  z.object({ kind: z.literal('delta'), request_id: id, text }).strict(),
  z
    .object({
      kind: z.literal('settled'),
      request_id: id,
      snapshot: snapshotSchema,
    })
    .strict(),
  z
    .object({
      kind: z.literal('recovery'),
      request_id: id,
      code: z.enum(['outcome_unknown', 'fenced']),
      retryable: z.literal(false),
    })
    .strict(),
])

export class ChatFailure extends Error {
  constructor(
    readonly kind: 'expired' | 'unknown' | 'full' | 'rate_limited' | 'invalid'
  ) {
    super('Chat request unavailable')
  }
}
const base = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
function headers(token: string) {
  return { 'Content-Type': 'application/json', 'X-Chat-Token': token }
}
async function checked(response: Response): Promise<Response> {
  if (response.ok) return response
  if (response.status === 404 || response.status === 410) {
    await response.body?.cancel()
    throw new ChatFailure('expired')
  }
  const failureSchema = z.object({
    error: z.object({ code: z.string().max(48) }),
  })
  const body = failureSchema.safeParse(await boundedJSON(response))
  const code = body.success ? body.data.error.code : ''
  const kind =
    code === 'conversation_full'
      ? 'full'
      : code === 'rate_limited'
        ? 'rate_limited'
        : code === 'invalid_request' || code === 'request_too_large'
          ? 'invalid'
          : 'unknown'
  throw new ChatFailure(kind)
}
async function boundedJSON(response: Response): Promise<unknown> {
  const reader = response.body?.getReader()
  if (!reader) throw new ChatFailure('unknown')
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let result = ''
  let bytes = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.byteLength
      if (bytes > 1_000_000) throw new ChatFailure('unknown')
      result += decoder.decode(value, { stream: true })
    }
    return JSON.parse(result + decoder.decode())
  } finally {
    await reader.cancel().catch(() => {})
  }
}
export async function current(
  token: string,
  signal?: AbortSignal
): Promise<Snapshot> {
  const response = await checked(
    await fetch(`${base}/chat/current`, {
      headers: headers(token),
      cache: 'no-store',
      signal: signal ?? AbortSignal.timeout(15_000),
    })
  )
  return snapshotSchema.parse(await boundedJSON(response))
}
export async function cancel(
  token: string,
  request_id: string,
  expected_revision: number
): Promise<Snapshot> {
  const response = await checked(
    await fetch(`${base}/chat/cancel`, {
      method: 'POST',
      headers: headers(token),
      cache: 'no-store',
      body: JSON.stringify({ request_id, expected_revision }),
      signal: AbortSignal.timeout(15_000),
      keepalive: true,
    })
  )
  return snapshotSchema.parse(await boundedJSON(response))
}
export async function turn(
  token: string,
  command: Command,
  signal: AbortSignal,
  receive: (event: ChatEvent) => void
): Promise<void> {
  const response = await checked(
    await fetch(`${base}/chat/turns`, {
      method: 'POST',
      headers: { ...headers(token), Accept: 'text/event-stream' },
      body: JSON.stringify(command),
      cache: 'no-store',
      signal,
    })
  )
  if (!response.headers.get('content-type')?.startsWith('text/event-stream')) {
    await response.body?.cancel()
    throw new ChatFailure('unknown')
  }
  const reader = response.body?.getReader()
  if (!reader) throw new ChatFailure('unknown')
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = ''
  let bytes = 0
  let terminal = false
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      bytes += chunk.value.byteLength
      if (bytes > 1_000_000) throw new ChatFailure('unknown')
      buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replace(
        /\r\n/g,
        '\n'
      )
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (frame.length > 100_000) throw new ChatFailure('unknown')
        let name = ''
        const data: string[] = []
        for (const line of frame.split('\n')) {
          if (line.startsWith(':') || line === '') continue
          const colon = line.indexOf(':')
          const field = colon < 0 ? line : line.slice(0, colon)
          const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
          if (field === 'event' && !name) name = value
          else if (field === 'data') data.push(value)
          else throw new ChatFailure('unknown')
        }
        if (!data.length) continue
        if (terminal) throw new ChatFailure('unknown')
        const parsed: unknown = JSON.parse(data.join('\n'))
        if (
          typeof parsed !== 'object' ||
          parsed === null ||
          Array.isArray(parsed)
        )
          throw new ChatFailure('unknown')
        const event = eventSchema.parse({ ...parsed, kind: name })
        if (event.request_id !== command.request_id)
          throw new ChatFailure('unknown')
        terminal = event.kind === 'settled' || event.kind === 'recovery'
        receive(event)
      }
      if (buffer.length > 100_000) throw new ChatFailure('unknown')
    }
    buffer += decoder.decode()
    if (buffer.trim() || !terminal) throw new ChatFailure('unknown')
  } finally {
    await reader.cancel().catch(() => {})
  }
}
