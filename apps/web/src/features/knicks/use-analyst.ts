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
type Chat = {
  messages: Message[]
  activeStart: number
  question: string
  version?: string
  sessionToken?: string
  revision: number
  expiresAt?: string
  retry?: Turn
  pending: boolean
  error?: string
  notice?: string
  generation: number
}
const conversationStorageName = 'knicksiq-conversation-v1'
const fresh = (): Chat => ({
  messages: [],
  activeStart: 0,
  question: '',
  revision: 0,
  pending: false,
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
        retry: chat.retry,
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
    retry,
    pending: false,
    generation: chat.generation + 1,
    error: undefined,
    notice: undefined,
  })
}
function restore() {
  try {
    const raw = sessionStorage.getItem(conversationStorageName)
    if (!raw) return
    const value = JSON.parse(raw) as Partial<Chat> & { schema?: number }
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
      ...fresh(),
      ...value,
      pending: false,
      generation: 0,
      question: value.retry?.question ?? value.question ?? '',
      notice: value.retry
        ? 'A question was interrupted. Retry it when ready.'
        : undefined,
    }
    if (chat.expiresAt && Date.parse(chat.expiresAt) <= Date.now()) {
      const retry = chat.retry && {
        ...chat.retry,
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
    queryFn: async () => {
      let timer: ReturnType<typeof setTimeout> | undefined
      const [status, games] = await Promise.race([
        Promise.all([
          fetchArchiveStatus(),
          fetchGames({ season: '2025-26', teamId: 'NYK', limit: 1 }),
        ]),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error('Readiness deadline exceeded')),
            60000
          )
        }),
      ]).finally(() => clearTimeout(timer))
      if (!status.games || !games.length) throw new Error('Archive unavailable')
      if (chat.version && chat.version !== status.data_version) {
        boundary(
          'Archive updated. Previous messages are history; this is a new conversation.',
          chat.retry && {
            ...chat.retry,
            context: [],
            expected_revision: 0,
            session_token: undefined,
          }
        )
      }
      change({ version: status.data_version })
      return status
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const archiveReady = readiness.isSuccess && !readiness.isFetching
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
    if (!archiveReady || chat.pending || !question) return
    if (chat.expiresAt && Date.parse(chat.expiresAt) <= Date.now()) {
      boundary('Session expired. Start a new conversation from here.')
    }
    const retry = chat.retry?.question === question ? chat.retry : undefined
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
      retry: turn,
      pending: true,
      error: undefined,
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
          boundary(
            'Archive updated. Previous messages are history; this is a new conversation.',
            {
              ...turn,
              context: [],
              expected_revision: 0,
              session_token: undefined,
            }
          )
          change({
            version: response.data_version,
            pending: false,
            error: 'The archive changed. Edit or retry your question.',
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
        const failedCommit = response.warnings.some((warning) =>
          warning.includes('could not be committed')
        )
        const stateless = response.warnings.some((warning) =>
          warning.includes('Stateless factual fallback')
        )
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
          pending: false,
          retry: failedCommit ? turn : undefined,
          sessionToken: committed ? response.session_token! : chat.sessionToken,
          revision: committed ? response.revision! : chat.revision,
          expiresAt: committed
            ? (response.session_expires_at ?? undefined)
            : chat.expiresAt,
          error: failedCommit
            ? 'Conversation state was not saved. Retry this question.'
            : undefined,
        })
        if (stateless) {
          boundary(
            'Conversation state was unavailable. Start a new conversation from here.'
          )
        }
        requestAnimationFrame(() => {
          const headings = document.querySelectorAll<HTMLElement>(
            '.archive-answer-heading'
          )
          headings.item(headings.length - 1)?.focus()
        })
      })
      .catch((error: unknown) => {
        if (generation !== chat.generation || signal.aborted) return
        if (isAxiosError(error) && error.response?.status === 409) {
          const reason = String(error.response.data?.detail?.reason ?? '')
          if (reason === 'session_expired') {
            boundary('Session expired. Previous messages remain readable.', {
              ...turn,
              context: [],
              expected_revision: 0,
              session_token: undefined,
            })
            change({
              pending: false,
              question: turn.question,
              error: 'Your question is ready to retry or edit.',
            })
            return
          }
          if (/^\d+$/.test(reason)) {
            change({
              revision: Number(reason),
              retry: {
                ...turn,
                expected_revision: Number(reason),
              },
            })
          } else if (reason === 'turn_id_reused') {
            change({ retry: undefined })
          }
        }
        change({
          pending: false,
          error: navigator.onLine
            ? 'The analyst could not answer that request. Retry your question.'
            : 'You are offline. Reconnect and retry your question.',
        })
      })
  }
  const retry = () => {
    if (chat.retry) submit(chat.retry.question)
  }
  return {
    question: state.question,
    setQuestion,
    messages: state.messages,
    analyst: {
      error: state.error,
      isPending: state.pending,
      isSuccess: !!state.messages[state.messages.length - 1]?.response,
    },
    submit,
    retry,
    newChat,
    notice: state.notice,
    retryQuestion: state.retry?.question,
    archiveReady,
    archiveFailed: readiness.isError,
    archiveChecking: !archiveReady && !readiness.isError,
    slow,
    retryReadiness,
  }
}
