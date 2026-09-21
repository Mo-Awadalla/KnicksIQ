import { useEffect, useState, useSyncExternalStore } from 'react'
import { isAxiosError } from 'axios'
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { askAnalyst, fetchArchiveStatus, fetchGames } from '@/api'
import type { AnalysisContextMessage, AnalysisResponse } from '@/types'

type Message = AnalysisContextMessage & {
  id: string
  response?: AnalysisResponse
}
let thread: Message[] = []
let version: string | undefined
let sessionToken: string | undefined
let revision = 0
let submitting = false
let retryTurn:
  | {
      question: string
      context: AnalysisContextMessage[]
      turn_id: string
      expected_revision: number
      session_token?: string
    }
  | undefined
const listeners = new Set<() => void>()
function publish(messages: Message[]) {
  thread = messages
  listeners.forEach((listener) => listener())
}
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAnalyst() {
  const queryClient = useQueryClient()
  const messages = useSyncExternalStore(subscribe, () => thread)
  const [question, setQuestion] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const slowTimer = setTimeout(() => setSlow(true), 5000)
    return () => {
      clearTimeout(slowTimer)
    }
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
      if (version && version !== status.data_version) publish([])
      version = status.data_version
      return status
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const archiveReady = readiness.isSuccess && !readiness.isFetching
  const archiveFailed = readiness.isError
  const retryReadiness = () => {
    setSlow(false)
    setAttempt((value) => value + 1)
  }
  const pending = useIsMutating({ mutationKey: ['archive-analysis'] }) > 0
  const analyst = useMutation({
    mutationKey: ['archive-analysis'],
    mutationFn: async ({
      nextQuestion,
      context,
      state,
      turn,
    }: {
      nextQuestion: string
      context: AnalysisContextMessage[]
      state?: AnalysisResponse['conversation_state']
      turn: NonNullable<typeof retryTurn>
    }) => {
      let response: AnalysisResponse
      try {
        response = await askAnalyst(
          nextQuestion,
          '2025-26',
          context,
          state,
          turn
        )
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 409) {
          const reason = String(error.response.data?.detail?.reason ?? '')
          if (/^\d+$/.test(reason)) {
            revision = Number(reason)
            if (retryTurn) retryTurn.expected_revision = revision
          } else if (reason === 'turn_id_reused') {
            retryTurn = undefined
          }
          throw Object.assign(
            new Error(
              'The conversation changed or is still processing. Retry your question.'
            ),
            { cause: error }
          )
        }
        throw error
      }
      if (
        response.state_committed &&
        response.session_token &&
        response.revision != null
      ) {
        sessionToken = response.session_token
        revision = response.revision
        retryTurn = undefined
      } else if (response.revision === undefined) {
        // Compatibility with the deterministic endpoint before the rollout flag is enabled.
        retryTurn = undefined
      }
      if (
        version &&
        response.data_version &&
        response.data_version !== version
      ) {
        publish([])
        void queryClient.invalidateQueries({ queryKey: ['analyst-readiness'] })
        throw new Error(
          'The archive version changed. Please retry after readiness checks.'
        )
      }
      return response
    },
    onSettled: () => {
      submitting = false
    },
    onSuccess: (response, { turn }) => {
      publish([
        ...thread.filter((message) => message.id !== `${turn.turn_id}:answer`),
        {
          id: `${turn.turn_id}:answer`,
          role: 'assistant',
          content: response.answer,
          response,
        },
      ])
      requestAnimationFrame(() => {
        const headings = document.querySelectorAll<HTMLElement>(
          '.archive-answer-heading'
        )
        headings.item(headings.length - 1)?.focus()
      })
    },
  })
  const submit = (value = question) => {
    const nextQuestion = value.trim()
    if (!archiveReady || pending || submitting || !nextQuestion) return
    submitting = true
    const context = messages
      .slice(-12)
      .map(({ role, content }) => ({ role, content: content.slice(0, 2000) }))
    const state = [...messages]
      .reverse()
      .find((message) => message.response?.conversation_state)
      ?.response?.conversation_state
    const retry = retryTurn?.question === nextQuestion ? retryTurn : undefined
    const turn = retry ?? {
      question: nextQuestion,
      context,
      turn_id: crypto.randomUUID(),
      expected_revision: revision,
      session_token: sessionToken,
    }
    retryTurn = turn
    if (!retry)
      publish([
        ...messages,
        { id: crypto.randomUUID(), role: 'user', content: nextQuestion },
      ])
    setQuestion('')
    analyst.mutate({ nextQuestion, context: turn.context, state, turn })
  }
  return {
    question,
    setQuestion,
    messages,
    analyst: { ...analyst, isPending: pending },
    submit,
    archiveReady,
    archiveFailed,
    archiveChecking: !archiveReady && !archiveFailed,
    slow,
    retryReadiness,
  }
}
