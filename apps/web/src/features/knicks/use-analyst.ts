import { useEffect, useState, useSyncExternalStore } from 'react'
import { isAxiosError } from 'axios'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { askAnalyst, fetchArchiveStatus, fetchGames } from '@/api'
import type { AnalysisContextMessage, AnalysisResponse } from '@/types'
import { recentContext } from './conversation'

type Message = AnalysisContextMessage & {
  id: string
  response?: AnalysisResponse
  boundary?: string
}
type Turn = {
  question: string
  context: AnalysisContextMessage[]
  turn_id: string
  expected_revision: number
  session_token?: string
}
type TurnState =
  | { status: 'idle' }
  | { status: 'pending'; request: Turn }
  | { status: 'retryable'; request: Turn; error?: string }
type Conflict = { code: string; current_revision?: number }
function conflictOf(error: unknown): Conflict | undefined {
  if (!isAxiosError(error) || error.response?.status !== 409) return undefined
  const body: unknown = error.response.data
  if (!body || typeof body !== 'object' || !('error' in body)) return undefined
  const payload = body.error
  if (!payload || typeof payload !== 'object' || !('code' in payload))
    return undefined
  const code = payload.code
  if (typeof code !== 'string') return undefined
  const revision =
    'current_revision' in payload ? payload.current_revision : undefined
  if (
    typeof revision !== 'number' ||
    !Number.isInteger(revision) ||
    revision < 0
  )
    return { code }
  return { code, current_revision: revision }
}
type Chat = {
  messages: Message[]
  activeStart: number
  question: string
  version?: string
  sessionToken?: string
  revision: number
  expiresAt?: string
  turn: TurnState
  notice?: string
  generation: number
}
type ChatSnapshot = Omit<Chat, 'turn' | 'generation' | 'notice'> & {
  schema: number
  retry?: Turn
  interrupted?: boolean
}
function activeTurn(state: Chat): Turn | undefined {
  return state.turn.status === 'idle' ? undefined : state.turn.request
}
const conversationStorageName = 'knicksiq-conversation-v1'
const fresh = (): Chat => ({
  messages: [],
  activeStart: 0,
  question: '',
  revision: 0,
  turn: { status: 'idle' },
  generation: 0,
})
let chat = fresh()
let controller: AbortController | undefined
const listeners = new Set<() => void>()
const notify = () => listeners.forEach((listener) => listener())
function save() {
  try {
    sessionStorage.setItem(
      conversationStorageName,
      JSON.stringify({
        schema: 1,
        messages: chat.messages,
        activeStart: chat.activeStart,
        question: chat.question,
        version: chat.version,
        sessionToken: chat.sessionToken,
        revision: chat.revision,
        expiresAt: chat.expiresAt,
        retry: activeTurn(chat),
        interrupted: chat.turn.status === 'pending',
      })
    )
  } catch {
    chat = {
      ...chat,
      notice: 'Refresh recovery is unavailable in this browser.',
    }
  }
}
function change(patch: Partial<Chat>) {
  chat = { ...chat, ...patch }
  save()
  notify()
}
function boundary(message: string, retry?: Turn) {
  controller?.abort()
  const retained = retry
    ? chat.messages.filter((item) => item.id !== `${retry.turn_id}:question`)
    : chat.messages
  const question =
    retry &&
    chat.messages.find((item) => item.id === `${retry.turn_id}:question`)
  const messages: Message[] = [
    ...retained,
    {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      boundary: message,
    },
    ...(question ? [question] : []),
  ]
  change({
    messages,
    activeStart: messages.length - (question ? 1 : 0),
    sessionToken: undefined,
    revision: 0,
    expiresAt: undefined,
    turn: retry ? { status: 'retryable', request: retry } : { status: 'idle' },
    generation: chat.generation + 1,
    notice: undefined,
  })
}
function restore() {
  try {
    const raw = sessionStorage.getItem(conversationStorageName)
    if (!raw) return
    const value = JSON.parse(raw) as Partial<ChatSnapshot>
    if (
      value.schema !== 1 ||
      !Array.isArray(value.messages) ||
      typeof value.activeStart !== 'number' ||
      !Number.isInteger(value.activeStart) ||
      value.activeStart < 0 ||
      value.activeStart > value.messages.length ||
      typeof value.revision !== 'number' ||
      !Number.isInteger(value.revision) ||
      value.revision < 0 ||
      typeof value.question !== 'string' ||
      (value.interrupted !== undefined &&
        typeof value.interrupted !== 'boolean') ||
      (value.version !== undefined && typeof value.version !== 'string') ||
      (value.sessionToken !== undefined &&
        (typeof value.sessionToken !== 'string' ||
          !/^[a-f0-9]{64}$/.test(value.sessionToken))) ||
      (value.expiresAt !== undefined &&
        (typeof value.expiresAt !== 'string' ||
          Number.isNaN(Date.parse(value.expiresAt)))) ||
      !value.messages.every(
        (item) =>
          item &&
          typeof item.id === 'string' &&
          typeof item.content === 'string' &&
          (item.role === 'user' || item.role === 'assistant')
      ) ||
      (value.retry &&
        (typeof value.retry.turn_id !== 'string' ||
          typeof value.retry.question !== 'string' ||
          !Array.isArray(value.retry.context) ||
          !Number.isInteger(value.retry.expected_revision) ||
          value.retry.expected_revision < 0 ||
          value.retry.context.length > 10 ||
          !value.retry.context.every(
            (item) =>
              (item.role === 'user' || item.role === 'assistant') &&
              typeof item.content === 'string'
          )))
    ) {
      throw new Error('Invalid conversation snapshot')
    }
    chat = {
      messages: value.messages,
      activeStart: value.activeStart,
      version: value.version,
      sessionToken: value.sessionToken,
      revision: value.revision,
      expiresAt: value.expiresAt,
      turn: value.retry
        ? { status: 'retryable', request: value.retry }
        : { status: 'idle' },
      generation: 0,
      question:
        value.question ||
        (value.interrupted !== false ? value.retry?.question : '') ||
        '',
      notice: value.retry
        ? 'A question was interrupted. Retry it when ready.'
        : undefined,
    }
    if (chat.expiresAt && Date.parse(chat.expiresAt) <= Date.now()) {
      const previous = activeTurn(chat)
      const retry = previous && {
        ...previous,
        context: [],
        expected_revision: 0,
        session_token: undefined,
      }
      boundary('Session expired. Start a new conversation from here.', retry)
    }
  } catch {
    chat = {
      ...fresh(),
      notice: 'Refresh recovery is unavailable in this browser.',
    }
  }
}
restore()
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAnalyst() {
  const queryClient = useQueryClient()
  const state = useSyncExternalStore(subscribe, () => chat)
  const [attempt, setAttempt] = useState(0)
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 5000)
    return () => clearTimeout(timer)
  }, [attempt])
  const readiness = useQuery({
    queryKey: ['analyst-readiness', attempt],
    queryFn: async ({ signal }) => {
      const deadline = new AbortController()
      const timer = setTimeout(
        () => deadline.abort(new Error('Readiness deadline exceeded')),
        60000
      )
      const requestSignal = AbortSignal.any([signal, deadline.signal])
      try {
        const [status, games] = await Promise.all([
          fetchArchiveStatus(undefined, requestSignal),
          fetchGames(
            { season: '2025-26', teamId: 'NYK', limit: 1 },
            requestSignal
          ),
        ])
        if (!status.games || !games.length)
          throw new Error('Archive unavailable')
        return status
      } finally {
        clearTimeout(timer)
        deadline.abort()
      }
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const archiveReady = readiness.isSuccess && !readiness.isFetching
  useEffect(() => {
    const status = readiness.data
    if (!archiveReady || !status || chat.version === status.data_version) return
    // Only the currently observed check may change conversation authority.
    if (chat.version) {
      const previous = activeTurn(chat)
      boundary(
        'Archive updated. Previous messages are history; this is a new conversation.',
        previous && {
          ...previous,
          context: [],
          expected_revision: 0,
          session_token: undefined,
        }
      )
    }
    change({ version: status.data_version })
  }, [archiveReady, readiness.data])
  const retryReadiness = () => {
    setSlow(false)
    setAttempt((value) => value + 1)
  }
  const setQuestion = (question: string) => change({ question })
  const newChat = () => {
    controller?.abort()
    const generation = chat.generation + 1
    chat = { ...fresh(), version: chat.version, generation }
    try {
      sessionStorage.removeItem(conversationStorageName)
    } catch {
      chat.notice = 'Refresh recovery is unavailable in this browser.'
    }
    notify()
  }
  const submit = (value = chat.question) => {
    const question = value.trim()
    if (!archiveReady || chat.turn.status === 'pending' || !question) return
    if (chat.expiresAt && Date.parse(chat.expiresAt) <= Date.now()) {
      boundary('Session expired. Start a new conversation from here.')
    }
    const previous = activeTurn(chat)
    const retry = previous?.question === question ? previous : undefined
    const context = recentContext(
      chat.messages
        .slice(chat.activeStart)
        .filter((message) => !message.boundary)
        .map(({ role, content }) => ({ role, content }))
    )
    const turn: Turn = retry ?? {
      question,
      context,
      turn_id: crypto.randomUUID(),
      expected_revision: chat.revision,
      session_token: chat.sessionToken,
    }
    const conversationState = [...chat.messages.slice(chat.activeStart)]
      .reverse()
      .find((message) => message.response?.conversation_state)
      ?.response?.conversation_state
    const messages = retry
      ? chat.messages
      : [
          ...chat.messages,
          {
            id: `${turn.turn_id}:question`,
            role: 'user' as const,
            content: question,
          },
        ]
    controller = new AbortController()
    const signal = controller.signal
    const generation = chat.generation
    change({
      messages,
      question: '',
      turn: { status: 'pending', request: turn },
      notice: undefined,
    })
    void askAnalyst(
      question,
      '2025-26',
      turn.context,
      conversationState,
      turn,
      signal
    )
      .then((response) => {
        if (generation !== chat.generation) return
        if (
          chat.version &&
          response.data_version &&
          response.data_version !== chat.version
        ) {
          const restart = {
            ...turn,
            context: [],
            expected_revision: 0,
            session_token: undefined,
          }
          boundary(
            'Archive updated. Previous messages are history; this is a new conversation.',
            restart
          )
          change({
            version: response.data_version,
            turn: {
              status: 'retryable',
              request: restart,
              error: 'The archive changed. Edit or retry your question.',
            },
          })
          void queryClient.invalidateQueries({
            queryKey: ['analyst-readiness'],
          })
          return
        }
        const committed =
          response.state_committed &&
          response.session_token &&
          response.revision != null
        const failedCommit = response.session_status === 'retryable'
        const stateless = response.session_status === 'unavailable'
        const updated = [
          ...chat.messages.filter(
            (message) => message.id !== `${turn.turn_id}:answer`
          ),
          {
            id: `${turn.turn_id}:answer`,
            role: 'assistant' as const,
            content: response.answer,
            response,
          },
        ]
        change({
          messages: updated,
          turn: failedCommit
            ? {
                status: 'retryable',
                request: turn,
                error: 'Conversation state was not saved. Retry this question.',
              }
            : { status: 'idle' },
          sessionToken: committed ? response.session_token! : chat.sessionToken,
          revision: committed ? response.revision! : chat.revision,
          expiresAt: committed
            ? (response.session_expires_at ?? undefined)
            : chat.expiresAt,
        })
        if (stateless) {
          boundary(
            'Conversation state was unavailable. Start a new conversation from here.'
          )
        }
        const focusAtResponse = document.activeElement
        requestAnimationFrame(() => {
          if (
            generation !== chat.generation ||
            chat.turn.status === 'pending' ||
            chat.question.trim() ||
            document.activeElement !== focusAtResponse
          )
            return
          const headings = document.querySelectorAll<HTMLElement>(
            '.archive-answer-heading'
          )
          headings.item(headings.length - 1)?.focus()
        })
      })
      .catch((error: unknown) => {
        if (generation !== chat.generation || signal.aborted) return
        const conflict = conflictOf(error)
        if (conflict?.code === 'session_expired') {
          const restart = {
            ...turn,
            context: [],
            expected_revision: 0,
            session_token: undefined,
          }
          boundary(
            'Session expired. Previous messages remain readable.',
            restart
          )
          change({
            question: turn.question,
            turn: {
              status: 'retryable',
              request: restart,
              error: 'Your question is ready to retry or edit.',
            },
          })
          return
        }
        let retry = turn
        if (
          conflict?.code === 'revision_conflict' &&
          conflict.current_revision !== undefined
        ) {
          retry = { ...turn, expected_revision: conflict.current_revision }
          change({ revision: conflict.current_revision })
        } else if (conflict?.code === 'turn_id_reused') {
          retry = {
            question: turn.question,
            context: turn.context,
            turn_id: crypto.randomUUID(),
            expected_revision: chat.revision,
            session_token: chat.sessionToken,
          }
        }
        // turn_in_progress leaves the identical request replayable through UI retry.
        change({
          turn: {
            status: 'retryable',
            request: retry,
            error: navigator.onLine
              ? 'The analyst could not answer that request. Retry your question.'
              : 'You are offline. Reconnect and retry your question.',
          },
        })
      })
  }
  const retry = () => {
    const previous = activeTurn(chat)
    if (previous) submit(previous.question)
  }
  return {
    question: state.question,
    setQuestion,
    messages: state.messages,
    analyst: {
      error: state.turn.status === 'retryable' ? state.turn.error : undefined,
      isPending: state.turn.status === 'pending',
      isSuccess: !!state.messages[state.messages.length - 1]?.response,
    },
    submit,
    retry,
    newChat,
    notice: state.notice,
    retryQuestion: activeTurn(state)?.question,
    archiveReady,
    archiveFailed: readiness.isError,
    archiveChecking: !archiveReady && !readiness.isError,
    slow,
    retryReadiness,
  }
}
