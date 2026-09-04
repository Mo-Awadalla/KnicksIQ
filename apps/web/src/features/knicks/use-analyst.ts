import { useEffect, useState, useSyncExternalStore } from 'react'
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
    }: {
      nextQuestion: string
      context: AnalysisContextMessage[]
      state?: AnalysisResponse['conversation_state']
    }) => {
      const response = await askAnalyst(nextQuestion, '2025-26', context, state)
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
    onSuccess: (response) => {
      publish([
        ...thread,
        {
          id: crypto.randomUUID(),
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
    if (!archiveReady || pending || !nextQuestion) return
    const context = messages
      .slice(-4)
      .map(({ role, content }) => ({ role, content }))
    const state = [...messages]
      .reverse()
      .find((message) => message.response?.conversation_state)
      ?.response?.conversation_state
    publish([
      ...messages,
      { id: crypto.randomUUID(), role: 'user', content: nextQuestion },
    ])
    setQuestion('')
    analyst.mutate({ nextQuestion, context, state })
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
